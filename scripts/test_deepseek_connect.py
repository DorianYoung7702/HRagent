"""Quick DeepSeek connectivity check."""
from __future__ import annotations

import asyncio

from packages.settings import get_settings
from services.agent_service.llm import get_deepseek_http_client


async def main() -> int:
    settings = get_settings()
    print(f"trust_env={settings.deepseek_trust_env}")
    print(f"base_url={settings.deepseek_base_url}")
    print(f"model={settings.deepseek_model}")
    print(f"api_key_set={bool(settings.deepseek_api_key)}")

    if not settings.deepseek_api_key:
        print("ERROR: DEEPSEEK_API_KEY not configured")
        return 1

    client = get_deepseek_http_client()
    try:
        url = f"{settings.deepseek_base_url.rstrip('/')}/models"
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
        )
        print(f"status={resp.status_code}")
        print(f"body_preview={resp.text[:300]}")
        return 0 if resp.status_code < 500 else 1
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
