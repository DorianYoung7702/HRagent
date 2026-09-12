"""Run Liepin LPT demo via API (visible browser, single process, no SQLite lock)."""

import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEMO_PAYLOAD = {
    "name": "西班牙语海外销售 Demo",
    "keywords": "西班牙语 美签 海外销售",
    "city": "深圳",
    "experience": "3-5年",
    "target_count": 20,
    "job_id": "demo_overseas_sales",
    "job_description": (
        "岗位：海外销售（西班牙语方向）。"
        "要求：西班牙语流利、有美签、海外销售经验、base深圳、3-5年经验。"
    ),
    "min_score": 60.0,
    "top_k": 3,
}

API_BASE = "http://localhost:8001"


def wait_for_api(timeout_sec: int = 30) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            r = httpx.get(f"{API_BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1)
    return False


def main() -> None:
    print("=== Liepin LPT Demo (visible browser) ===")
    print("1. Ensure you ran: .\\scripts\\login_liepin.ps1")
    print("2. Browser opens from API process - watch the Chromium window")
    print("3. This request may take several minutes...")
    print()

    if not wait_for_api():
        print(f"ERROR: API not reachable at {API_BASE}")
        print("Start API first: .\\scripts\\start_api.ps1")
        sys.exit(1)

    print("Calling run-visible endpoint (fetch + screen in API process)...")
    with httpx.Client(timeout=httpx.Timeout(3600.0)) as client:
        r = client.post(
            f"{API_BASE}/workflows/demo/liepin-lpt/run-visible",
            json=DEMO_PAYLOAD,
        )
        r.raise_for_status()
        result = r.json()

    wf_id = result.get("id")
    status = result.get("status")
    error_msg = result.get("error_message")
    success = result.get("success", False)

    print()
    print(f"Workflow: {wf_id}")
    print(f"Status: {status}")
    if error_msg:
        print(f"ERROR: {error_msg}")
    print(f"Admin: {API_BASE}/admin/workflows/{wf_id}")
    print()
    print(result.get("message", "Done."))

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
