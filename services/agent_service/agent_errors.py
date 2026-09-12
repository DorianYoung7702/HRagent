"""Agent inference errors — no rule-based fallback in production paths."""


class AgentInferenceError(RuntimeError):
    """Raised when LLM inference fails or returns incomplete output."""
