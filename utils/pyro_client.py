"""utils/pyro_client.py — Pyrogram client for MTProto 2GB uploads."""

import asyncio
import logging
from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN

logger = logging.getLogger(__name__)

# Initialize Pyrogram Client as a Bot
# This allows us to use MTProto for uploads up to 2GB
pyro_app = Client(
    name="media_saver_pyro",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True, # Avoid creating .session file on disk in Railway
    workers=50,      # Handle more concurrent uploads
    sleep_threshold=60 # Avoid disconnects
)

async def start_pyro():
    if not API_ID or not API_HASH:
        logger.warning("⚠️ API_ID or API_HASH missing. 2GB support disabled (fallback to 50MB).")
        return False
    
    try:
        pyro_app.loop = asyncio.get_running_loop()
        await pyro_app.start()
        pyro_app.loop = asyncio.get_running_loop()
        logger.info("✅ Pyrogram (MTProto) started for 2GB support.")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to start Pyrogram: {e}")
        return False

async def stop_pyro():
    try:
        await pyro_app.stop()
        logger.info("👋 Pyrogram (MTProto) stopped.")
    except Exception:
        pass
