"""DeepSeek LLM client — bypass broken system proxy by default."""

from __future__ import annotations

import httpx
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from packages.settings import get_settings

# Reuse one async client (trust_env=False avoids HTTP_PROXY/HTTPS_PROXY TLS failures on Windows)
_http_client: httpx.AsyncClient | None = None


def get_deepseek_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        settings = get_settings()
        _http_client = httpx.AsyncClient(
            trust_env=settings.deepseek_trust_env,
            timeout=httpx.Timeout(settings.deepseek_timeout, connect=30.0),
        )
    return _http_client


def create_deepseek_provider() -> DeepSeekProvider:
    """Use DeepSeekProvider so v4-flash gets correct tool_choice / thinking profile."""
    settings = get_settings()
    openai_client = AsyncOpenAI(
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        http_client=get_deepseek_http_client(),
    )
    return DeepSeekProvider(openai_client=openai_client)


def get_deepseek_model(model_name: str | None = None) -> OpenAIChatModel:
    settings = get_settings()
    name = model_name or settings.deepseek_model
    return OpenAIChatModel(name, provider=create_deepseek_provider())
