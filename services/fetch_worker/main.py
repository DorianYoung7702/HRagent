"""Standalone fetch worker entry point for Docker."""

import asyncio
import json
import sys

from packages.schemas.candidate import FetchInput
from services.fetch_worker.runner import run_fetch_task


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m services.fetch_worker.main '<json_input>'")
        sys.exit(1)

    data = json.loads(sys.argv[1])
    fetch_input = FetchInput(**data)
    result = await run_fetch_task(fetch_input)
    print(json.dumps(result.model_dump(), ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
