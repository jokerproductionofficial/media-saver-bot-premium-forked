"""utils/helpers.py — Registry for Premium Emojis and aiogram v3 helpers."""

import logging
import re
from typing import Dict, Optional, Union

from aiogram import Bot, types
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
)
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest

from config import CHANNEL_ID, CHANNEL_URL, ADMIN_ID, FORCE_JOIN_ENABLED, BOT_TOKEN
from database import db

logger = logging.getLogger(__name__)

# Registry: Maps standard Unicode emojis to their Premium Custom Emoji IDs
# IDs provided by the user for custom rendering.
CUSTOM_EMOJI_IDS: Dict[str, str] = {
    "⚙️": "4988254788001989201",
    "⚠️": "6314510813214284503",
    "⚡": "6320983775605955181",
    "⚡️": "6320983775605955181",
    "✅": "6111789662513141300",
    "✈️": "6321126853851487144",
    "❌": "6114167897574086974",
    "❓": "5377316857231450742",
    "❤️": "5307606342561705418",
    "🌍": "5080104639311906227",
    "🌐": "5082400599979329029",
    "🌟": "6323375024417807663",
    "🎉": "5235711785482341993",
    "🎬": "5368653135101310687",
    "🎵": "5377402498879333489",
    "🏆": "5312315739842026755",
    "🐦": "5314741073514346217",
    "👀": "6314425974725288033",
    "👁": "6026233591854272586",
    "👇": "6201847752251416401",
    "👋": "6167856028156171147",
    "👑": "6320806230247874333",
    "👤": "6032994772321309200",
    "👥": "6032609071373226027",
    "💪": "5440477791587943702",
    "💯": "6114156344112060970",
    "📅": "5890937706803894250",
    "📊": "6258267877170745815",
    "📋": "5926764846518376076",
    "📌": "6111736632551937935",
    "📖": "5226512880362332956",
    "📡": "5256134032852278918",
    "📢": "5780405967527089720",
    "📤": "5433614747381538714",
    "📥": "6201809243574638159",
    "📦": "5884479287171485878",
    "📨": "5406631276042002796",
    "📸": "6141162896605843133",
    "📹": "5375309569905938163",
    "🔒": "5393302369024882368",
    "🔙": "5253997076169115797",
    "🔞": "5420331611830886484",
    "🔥": "4981327074473018715",
    "🕐": "5445010743021818722",
    "🖼": "5895654525787705071",
    "🗓": "6111762200492251387",
    "🚀": "6321353301707203203",
    "🚫": "6111841240775400694",
    "🧹": "6314192620562161224",
    "ℹ️": "5226512880362332956", # Mapping Info to Book emoji
}

def get_eid(emoji: str) -> Optional[str]:
    """Return the Premium Custom Emoji ID for the given Unicode emoji."""
    return CUSTOM_EMOJI_IDS.get(emoji)

def get_etag(emoji: str) -> str:
    """Return the HTML <tg-emoji> tag for the given emoji."""
    eid = get_eid(emoji)
    if eid:
        return f'<tg-emoji emoji-id="{eid}">{emoji}</tg-emoji>'
    return emoji

async def safe_edit(query: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup = None):
    """
    Smarter edit function that handles both text-only and media messages
    to avoid DOCUMENT_INVALID and other common aiogram errors.
    """
    try:
        if query.message.photo or query.message.video or query.message.animation or query.message.document:
            return await query.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="HTML")
        return await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message process failed" in str(e) or "DOCUMENT_INVALID" in str(e):
            # Fallback to a new message if editing fails
            return await query.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
        logger.warning(f"Edit failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected edit error: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════════════
#  Force Join
# ═════════════════════════════════════════════════════════════════════════════

async def check_force_join(bot: Bot, user_id: int) -> bool:
    if not FORCE_JOIN_ENABLED or user_id == ADMIN_ID or not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status not in ["left", "kicked"]
    except Exception as e:
        if "member list is inaccessible" in str(e):
            return True 
        logger.error(f"Force join check error on {CHANNEL_ID}: {e}")
        return True

def force_join_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for force join message."""
    url = CHANNEL_URL if CHANNEL_URL else "https://t.me/Notethicalteam"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=to_small_caps("Join Channel"), url=url, style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text=to_small_caps("Check Again"), callback_data="check_join", style=ButtonStyle.PRIMARY)]
    ])

# ═════════════════════════════════════════════════════════════════════════════
#  Guards
# ═════════════════════════════════════════════════════════════════════════════

async def guard_user(event: Union[Message, CallbackQuery], bot: Bot) -> bool:
    """Combined user guard: Force Join + Daily Limit + Ban."""
    user_id = event.from_user.id

    # 1. Ban Check
    if db.is_banned(user_id):
        text = f"🚫 <b>{to_small_caps('You are banned from using this bot.')}</b>"
        if isinstance(event, Message):
            await event.answer(text, parse_mode="HTML")
        else:
            await event.answer(text, show_alert=True)
        return False

    # 2. Force Join Check
    if not await check_force_join(bot, user_id):
        text = (
            f"❌ <b>{to_small_caps('Access Denied')}</b>\n\n"
            f"{to_small_caps('You must join our channel to use this bot.')}"
        )
        if isinstance(event, Message):
            await event.answer(text, reply_markup=force_join_keyboard(), parse_mode="HTML")
        else:
            await event.message.edit_text(text, reply_markup=force_join_keyboard(), parse_mode="HTML")
        return False

    return True

def format_views(count: int) -> str:
    if count >= 1_000_000:
        return f"{count/1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count/1_000:.1f}K"
    return str(count)

def to_small_caps(text: str) -> str:
    """Convert standard A-Z characters to Small Caps Unicode, preserving HTML tags."""
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    small  = "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ₀₁₂₃₄₅₆₇₈₉"
    trans = str.maketrans(normal, small)
    
    # Use regex to find text outside of < > tags
    def replace(match):
        return match.group(0).translate(trans)
        
    return re.sub(r'(?:^|>)[^<]+(?:<|$)', replace, text)

# ═════════════════════════════════════════════════════════════════════════════
#  UI & Progress
# ═════════════════════════════════════════════════════════════════════════════

def format_bytes(size: float) -> str:
    """Format bytes into human readable format (KB, MB, GB)."""
    if not size: return "0 B"
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}B"

def get_progress_bar(current: int, total: int) -> str:
    """Generate a visual progress bar using ASCII characters."""
    percentage = (current / total) * 100
    finished = int(percentage / 5) # 20 blocks total
    bar = "▓" * finished + "░" * (20 - finished)
    return bar
