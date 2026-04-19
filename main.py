import sys
import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, DOWNLOAD_DIR, LOG_FILE, sync_cookie_files_from_env
from database.db import init_db
from downloader import cleanup_old_files
from handlers import admin, download, start
from utils.pyro_client import start_pyro, stop_pyro

# Force UTF-8 for console output on Windows to prevent encoding errors
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logging.getLogger("aiogram").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    try:
        cookie_sync = sync_cookie_files_from_env()
        if cookie_sync["youtube"] == "environment":
            logger.info("✅ YouTube cookies loaded from environment.")
        elif cookie_sync["youtube"] == "file":
            logger.info("✅ YouTube cookies loaded from file.")

        if cookie_sync["generic"] == "environment":
            logger.info("✅ Generic cookies loaded from environment.")
        elif cookie_sync["generic"] == "file":
            logger.info("✅ Generic cookies loaded from file.")
    except Exception as exc:
        logger.error(f"❌ Could not load cookies from environment: {exc}")

    try:
        import subprocess

        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
        logger.info("✅ System FFmpeg detected.")
    except (FileNotFoundError, subprocess.CalledProcessError):
        logger.warning("⚠️ System FFmpeg not found, attempting to use static-ffmpeg...")
        try:
            import static_ffmpeg

            static_ffmpeg.add_paths()
            logger.info("✅ static-ffmpeg activated.")
        except Exception as exc:
            logger.error(f"❌ Could not initialize FFmpeg: {exc}")

    init_db()
    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
    cleanup_old_files(max_age_hours=1)

    me = await bot.get_me()
    logger.info(f"Bot Started: @{me.username}")
    logger.info("Custom Emojis & icon_custom_emoji_id active.")


async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(download.router)
    dp.include_router(admin.router)
    dp.startup.register(on_startup)

    logger.info("Starting Polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await start_pyro()

    try:
        await dp.start_polling(bot)
    finally:
        await stop_pyro()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Bot Stopped.")
