"""config.py — Environment variables and bot constants."""

import base64
import binascii
import os
from dotenv import load_dotenv

load_dotenv()

# ── Required ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "5817712676"))
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "Talk_with_joker_bot")

# ── MTProto (For 2GB Support) ────────────────────────────────────────────────
API_ID: int = int(os.getenv("API_ID", "0"))
API_HASH: str = os.getenv("API_HASH", "")

# ── Force Join ────────────────────────────────────────────────────────────────
CHANNEL_ID: str = os.getenv("CHANNEL_ID", "")
CHANNEL_URL: str = os.getenv("CHANNEL_URL", "")
FORCE_JOIN_ENABLED: bool = os.getenv("FORCE_JOIN_ENABLED", "false").lower() == "true"

# ── Limits ────────────────────────────────────────────────────────────────────
DAILY_LIMIT: int = int(os.getenv("DAILY_LIMIT", "10"))
RATE_LIMIT_SECONDS: int = int(os.getenv("RATE_LIMIT_SECONDS", "10"))
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "2000"))
FAST_UPLOAD_DOCUMENT_THRESHOLD_MB: int = int(
    os.getenv("FAST_UPLOAD_DOCUMENT_THRESHOLD_MB", "150")
)

# ── Paths ─────────────────────────────────────────────────────────────────────
DOWNLOAD_DIR: str = os.getenv("DOWNLOAD_DIR", "downloads")
DB_PATH: str = os.getenv("DB_PATH", "database/bot.db")
LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")

# ── Cookie Files (STRICT SEPARATION) ─────────────────────────────────────────
# YT_COOKIES_FILE: ONLY for YouTube — NEVER use for any other platform.
# COOKIES_FILE:    For Instagram and other platforms (NOT YouTube).
YT_COOKIES_FILE: str = os.getenv("YT_COOKIES_FILE", "yt_cookies.txt")
COOKIES_FILE: str = os.getenv("COOKIES_FILE", "cookies.txt")
YT_COOKIES_CONTENT: str = os.getenv("YT_COOKIES_CONTENT", "")
YT_COOKIES_B64: str = os.getenv("YT_COOKIES_B64", "")
COOKIES_CONTENT: str = os.getenv("COOKIES_CONTENT", "")
COOKIES_B64: str = os.getenv("COOKIES_B64", "")

# ── Cache ─────────────────────────────────────────────────────────────────────
CACHE_ENABLED: bool = os.getenv("CACHE_ENABLED", "true").lower() == "true"
CACHE_EXPIRY_HOURS: int = int(os.getenv("CACHE_EXPIRY_HOURS", "24"))

# ── Queue ─────────────────────────────────────────────────────────────────────
MAX_QUEUE_SIZE: int = int(os.getenv("MAX_QUEUE_SIZE", "5"))
MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))

# ── Quality options ───────────────────────────────────────────────────────────
# VIDEO_QUALITIES is no longer hardcoded — resolutions are fetched dynamically
# from each video's available formats via yt-dlp.
AUDIO_QUALITIES = {"128kbps": "128", "320kbps": "320"}

# ── Bot Name ──────────────────────────────────────────────────────────────────
BOT_NAME: str = os.getenv("BOT_NAME", "Media Saver Bot")

# ── Supported platforms ───────────────────────────────────────────────────────
SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "instagram.com",
    "tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "twitter.com", "x.com", "t.co",
    "pinterest.com", "pin.it",
    "facebook.com", "fb.watch", "fb.com",
    "t.me", "telegram.me",
]
from utils.helpers import to_small_caps

# ═══════════════════════════════════════════════════════════════════
#  Dynamic messages — env vars read at runtime
# ═══════════════════════════════════════════════════════════════════

def get_start_message() -> str:
    return (
        f'<tg-emoji emoji-id="5368653135101310687">🎬</tg-emoji> <b>{to_small_caps("Welcome to " + BOT_NAME.upper())}!</b>\n\n'
        f'<tg-emoji emoji-id="6320983775605955181">⚡️</tg-emoji> <b>{to_small_caps("Fast • Free • No Watermark")}</b> <tg-emoji emoji-id="4981327074473018715">🔥</tg-emoji>\n\n'
        f'<tg-emoji emoji-id="6201809243574638159">📥</tg-emoji> <b>{to_small_caps("Paste any link below to start:")}</b>\n\n'
        f'<tg-emoji emoji-id="5368653135101310687">▶️</tg-emoji> {to_small_caps("YouTube")} — {to_small_caps("Videos & MP3")}\n'
        f'<tg-emoji emoji-id="6141162896605843133">📸</tg-emoji> {to_small_caps("Instagram")} — {to_small_caps("Reels & Posts")}\n'
        f'<tg-emoji emoji-id="5377402498879333489">🎵</tg-emoji> {to_small_caps("TikTok")} — {to_small_caps("No watermark")}\n'
        f'<tg-emoji emoji-id="5314741073514346217">🐦</tg-emoji> {to_small_caps("X / Twitter")} — {to_small_caps("Videos & GIFs")}\n'
        f'<tg-emoji emoji-id="6111736632551937935">📌</tg-emoji> {to_small_caps("Pinterest")} — {to_small_caps("Videos & Images")}\n'
        f'<tg-emoji emoji-id="5082400599979329029">🌐</tg-emoji> {to_small_caps("Facebook")} — {to_small_caps("Public Videos")}\n'
        f'<tg-emoji emoji-id="6321126853851487144">✈️</tg-emoji> {to_small_caps("Telegram")} — {to_small_caps("Public Media")}\n\n'
        f'<tg-emoji emoji-id="6321353301707203203">🚀</tg-emoji> {to_small_caps("Just paste a link to get started!")}'
    )


def get_help_message() -> str:
    return (
        f"""<tg-emoji emoji-id="5226512880362332956">📖</tg-emoji> <b>{to_small_caps("How to use:")}</b>\n\n"""
        f"""1️⃣ {to_small_caps("Paste a supported link in chat")}\n"""
        f"""2️⃣ {to_small_caps("Choose Video or Audio")}\n"""
        f"""3️⃣ {to_small_caps("Pick quality")}\n"""
        f"""4️⃣ {to_small_caps("Get your file!")} <tg-emoji emoji-id="5235711785482341993">🎉</tg-emoji>\n\n"""
        f"""<tg-emoji emoji-id="6314510813214284503">⚠️</tg-emoji> <b>{to_small_caps("Known Limits:")}</b>\n"""
        f"""• {to_small_caps("Instagram: some reels need cookies")}\n"""
        f"""• {to_small_caps("YouTube: may need cookies if blocked")}\n"""
        f"""• {to_small_caps("Pinterest: fallback to image if video fails")}\n"""
        f"""• {to_small_caps("Facebook: public videos only")}\n\n"""
        f"""<tg-emoji emoji-id="5884479287171485878">📦</tg-emoji> {to_small_caps("Max size:")} <b>{MAX_FILE_SIZE_MB}MB</b>\n"""
        f"""<tg-emoji emoji-id="6258267877170745815">📊</tg-emoji> {to_small_caps("Daily limit:")} <b>{DAILY_LIMIT}/day</b>\n\n"""
        f"""<tg-emoji emoji-id="5377316857231450742">❓</tg-emoji> {to_small_caps("Issues? Contact")} @{ADMIN_USERNAME}"""
    )


if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set in Railway environment variables!")


def _decode_cookie_payload(raw_text: str, raw_b64: str) -> str:
    if raw_text:
        return raw_text.replace("\r\n", "\n").strip() + "\n"

    if not raw_b64:
        return ""

    try:
        decoded = base64.b64decode(raw_b64).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid base64 cookie payload: {exc}") from exc

    return decoded.replace("\r\n", "\n").strip() + "\n"


def _write_cookie_file(path: str, content: str) -> bool:
    if not content:
        return False

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return True


def sync_cookie_files_from_env() -> dict:
    result = {"youtube": False, "generic": False}

    yt_content = _decode_cookie_payload(YT_COOKIES_CONTENT, YT_COOKIES_B64)
    if yt_content:
        result["youtube"] = _write_cookie_file(YT_COOKIES_FILE, yt_content)

    generic_content = _decode_cookie_payload(COOKIES_CONTENT, COOKIES_B64)
    if generic_content:
        result["generic"] = _write_cookie_file(COOKIES_FILE, generic_content)

    return result
