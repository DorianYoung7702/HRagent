import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from packages.settings import get_settings
from services.reply_ingestion_worker.scan_conversations import scan_active_conversations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        scan_active_conversations,
        "interval",
        minutes=settings.reply_scan_interval_minutes,
        id="reply_scan",
    )

    scheduler.start()
    logger.info(
        "Reply ingestion worker started, scanning every %d minutes",
        settings.reply_scan_interval_minutes,
    )

    await scan_active_conversations()

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
