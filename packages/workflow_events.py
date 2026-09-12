"""In-memory workflow event bus for console SSE streaming."""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_BUFFER = 2_000
_SENSITIVE_META_KEYS = frozenset(
    {"api_key", "authorization", "cookie", "cookies", "password", "raw_text", "resume_text", "dom", "html"}
)

_current_workflow_id: ContextVar[str | None] = ContextVar("workflow_id", default=None)
_counters: dict[str, int] = defaultdict(int)
_buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_BUFFER))
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


@dataclass
class WorkflowEvent:
    id: int
    ts: str
    level: str
    category: str
    message: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_sse_data(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _event_log_root() -> Path | None:
    explicit = os.environ.get("HRAGENT_EVENT_LOG_DIR")
    if explicit:
        return Path(explicit)
    data_root = os.environ.get("HRAGENT_DATA_DIR", "data")
    return Path(data_root) / "logs" / "workflow_events"


def _safe_workflow_filename(workflow_id: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in workflow_id)


def _event_log_path(workflow_id: str) -> Path | None:
    root = _event_log_root()
    if root is None:
        return None
    return root / f"{_safe_workflow_filename(workflow_id)}.jsonl"


def _load_persisted_events(workflow_id: str) -> list[WorkflowEvent]:
    path = _event_log_path(workflow_id)
    if path is None or not path.exists():
        return []
    events: list[WorkflowEvent] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                continue
            events.append(
                WorkflowEvent(
                    id=int(data.get("id") or 0),
                    ts=str(data.get("ts") or ""),
                    level=str(data.get("level") or "info"),
                    category=str(data.get("category") or "system"),
                    message=str(data.get("message") or ""),
                    meta=data.get("meta") if isinstance(data.get("meta"), dict) else {},
                )
            )
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    return events[-MAX_BUFFER:]


def _persist_event(workflow_id: str, event: WorkflowEvent) -> None:
    path = _event_log_path(workflow_id)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(event.to_sse_data())
            fh.write("\n")
    except OSError:
        return


def _safe_meta(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Keep diagnostics useful without persisting credentials or source resume content."""
    if key.lower() in _SENSITIVE_META_KEYS:
        return "[redacted]"
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {str(k): _safe_meta(v, key=str(k), depth=depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [_safe_meta(item, depth=depth + 1) for item in value[:30]]
    if isinstance(value, str):
        return value[:800] + ("..." if len(value) > 800 else "")
    return value


def _ensure_counter_from_persisted(workflow_id: str) -> None:
    if _counters.get(workflow_id):
        return
    persisted = _load_persisted_events(workflow_id)
    if persisted:
        _counters[workflow_id] = max(e.id for e in persisted)


@contextmanager
def workflow_context(workflow_id: str):
    token = _current_workflow_id.set(workflow_id)
    try:
        yield
    finally:
        _current_workflow_id.reset(token)


def emit(
    level: str,
    message: str,
    *,
    category: str = "system",
    meta: dict[str, Any] | None = None,
    workflow_id: str | None = None,
) -> WorkflowEvent | None:
    wf_id = workflow_id or _current_workflow_id.get()
    if not wf_id:
        return None

    _ensure_counter_from_persisted(wf_id)
    _counters[wf_id] += 1
    event = WorkflowEvent(
        id=_counters[wf_id],
        ts=datetime.now(timezone.utc).isoformat(),
        level=level,
        category=category,
        message=message,
        meta=_safe_meta(meta or {}),
    )
    _buffers[wf_id].append(event)
    _persist_event(wf_id, event)

    for q in list(_subscribers.get(wf_id, [])):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
    return event


def _merged_events(workflow_id: str) -> list[WorkflowEvent]:
    persisted = _load_persisted_events(workflow_id)
    by_id: dict[int, WorkflowEvent] = {event.id: event for event in persisted}
    for event in _buffers.get(workflow_id, deque()):
        by_id[event.id] = event
    return [by_id[event_id] for event_id in sorted(by_id)]


def get_workflow_log_summary(workflow_id: str) -> dict[str, Any]:
    events = _merged_events(workflow_id)
    path = _event_log_path(workflow_id)
    persisted = bool(path and path.exists())
    if not events:
        return {
            "event_count": 0,
            "last_message": "",
            "last_ts": None,
            "last_level": "info",
            "persisted": persisted,
        }
    last = events[-1]
    return {
        "event_count": len(events),
        "last_message": (last.message or "")[:240],
        "last_ts": last.ts or None,
        "last_level": last.level or "info",
        "persisted": persisted,
    }


def get_events(workflow_id: str, since_id: int = 0) -> list[dict[str, Any]]:
    if workflow_id not in _buffers or not _buffers[workflow_id]:
        persisted = _load_persisted_events(workflow_id)
        if persisted:
            _buffers[workflow_id].extend(persisted)
            _counters[workflow_id] = max(_counters.get(workflow_id, 0), max(e.id for e in persisted))
    elif _event_log_path(workflow_id):
        persisted = _load_persisted_events(workflow_id)
        if persisted:
            existing_ids = {event.id for event in _buffers[workflow_id]}
            for event in persisted:
                if event.id not in existing_ids:
                    _buffers[workflow_id].append(event)
            _counters[workflow_id] = max(_counters.get(workflow_id, 0), max(e.id for e in persisted))
    buf = _buffers.get(workflow_id, deque())
    return [e.to_dict() for e in buf if e.id > since_id]


async def subscribe(workflow_id: str, *, since_id: int = 0) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers[workflow_id].append(q)
    for e in _buffers.get(workflow_id, deque()):
        if e.id > since_id:
            await q.put(e)
    return q


def unsubscribe(workflow_id: str, q: asyncio.Queue) -> None:
    subs = _subscribers.get(workflow_id, [])
    if q in subs:
        subs.remove(q)


def clear_workflow(workflow_id: str, *, clear_persisted: bool = True) -> None:
    """Reset buffer for a workflow (testing)."""
    _buffers.pop(workflow_id, None)
    _counters.pop(workflow_id, None)
    _subscribers.pop(workflow_id, None)
    if clear_persisted:
        path = _event_log_path(workflow_id)
        if path and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
