"""handlers/start.py — aiogram v3 Start and Help handlers."""

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ButtonStyle

from config import (
    BOT_NAME, ADMIN_USERNAME, DAILY_LIMIT, MAX_FILE_SIZE_MB,
    get_start_message, get_help_message
)
from database import db
from utils.helpers import get_eid, get_etag, guard_user, safe_edit, to_small_caps

router = Router()

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=to_small_caps("How to Download"), callback_data="help", icon_custom_emoji_id=get_eid("📖"), style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text=to_small_caps("My Stats"), callback_data="my_stats", icon_custom_emoji_id=get_eid("📊"), style=ButtonStyle.PRIMARY),
        ],
        [
            InlineKeyboardButton(text=to_small_caps("Supported Sites"), callback_data="supported", icon_custom_emoji_id=get_eid("🌐"), style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text=to_small_caps("About Bot"), callback_data="about", icon_custom_emoji_id=get_eid("📋"), style=ButtonStyle.PRIMARY),
        ],
    ])

@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
    user = message.from_user
    db.upsert_user(user.id, user.username, user.full_name)

    if not await guard_user(message, bot):
        return

    text = get_start_message()
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    text = get_help_message()
    await message.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "help")
async def cb_help(query: types.CallbackQuery):
    await query.answer()
    text = (
        f"{get_etag('📖')} <b>{to_small_caps('How to use:')}</b>\n\n"
        f"1️⃣ {to_small_caps('Paste a supported link in chat')}\n"
        f"2️⃣ {to_small_caps('Choose Video or Audio')}\n"
        f"3️⃣ {to_small_caps('Pick quality')}\n"
        f"4️⃣ {to_small_caps('Get your file!')} 🎉\n\n"
        f"{get_etag('📦')} <b>{to_small_caps('Max size:')}</b> {MAX_FILE_SIZE_MB}MB\n"
        f"{get_etag('📊')} <b>{to_small_caps('Daily limit:')}</b> {DAILY_LIMIT}\n\n"
        f"❓ {to_small_caps('Issues? Contact')} @{ADMIN_USERNAME}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=to_small_caps("Back"), callback_data="back_start", icon_custom_emoji_id=get_eid("🔙"), style=ButtonStyle.PRIMARY)]
    ])
    await safe_edit(query, text, reply_markup=kb)

@router.callback_query(F.data == "supported")
async def cb_supported(query: types.CallbackQuery):
    await query.answer()
    text = (
        f"{get_etag('🌟')} <b>{to_small_caps('Supported Platforms')}</b>\n\n"
        f"{get_etag('🎬')} {to_small_caps('YouTube (All Res + Audio)')}\n"
        f"{get_etag('📸')} {to_small_caps('Instagram')}\n"
        f"{get_etag('🎵')} {to_small_caps('TikTok')}\n"
        f"{get_etag('🐦')} {to_small_caps('X / Twitter')}\n"
        f"{get_etag('📌')} {to_small_caps('Pinterest')}\n"
        f"{get_etag('✈️')} {to_small_caps('Facebook')}\n\n"
        f"{get_etag('⚠️')} <b>{to_small_caps('Private content is not supported.')}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=to_small_caps("Back"), callback_data="back_start", icon_custom_emoji_id=get_eid("🔙"), style=ButtonStyle.PRIMARY)]
    ])
    await safe_edit(query, text, reply_markup=kb)

@router.callback_query(F.data == "about")
async def cb_about(query: types.CallbackQuery):
    await query.answer()
    total = db.get_total_users()
    text = (
        f"{get_etag('🚀')} <b>{to_small_caps('About')} {to_small_caps(BOT_NAME)}</b>\n\n"
        f"{get_etag('👥')} <b>{to_small_caps('Total users:')}</b> {total}\n"
        f"{get_etag('📦')} <b>{to_small_caps('Max size:')}</b> {MAX_FILE_SIZE_MB}MB\n"
        f"{get_etag('📊')} <b>{to_small_caps('Limit:')}</b> {DAILY_LIMIT}/day\n\n"
        f"{get_etag('⚡')} {to_small_caps('Powered by yt-dlp')}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=to_small_caps("Back"), callback_data="back_start", icon_custom_emoji_id=get_eid("🔙"), style=ButtonStyle.PRIMARY)]
    ])
    await safe_edit(query, text, reply_markup=kb)

@router.callback_query(F.data == "back_start")
async def cb_back_start(query: types.CallbackQuery):
    await query.answer()
    text = get_start_message()
    await safe_edit(query, text, reply_markup=main_menu_kb())

@router.callback_query(F.data == "my_stats")
async def cb_my_stats(query: types.CallbackQuery):
    await query.answer()
    user = query.from_user
    info = db.get_user(user.id)
    usage = db.get_daily_usage(user.id)
    text = (
        f"{get_etag('📊')} <b>{to_small_caps('Your Statistics')}</b>\n\n"
        f"👤 <b>{to_small_caps('Name:')}</b> {user.full_name}\n"
        f"🆔 <b>{to_small_caps('ID:')}</b> <code>{user.id}</code>\n"
        f"📥 <b>{to_small_caps('Total:')}</b> {info['total_downloads'] if info else 0}\n"
        f"📅 <b>{to_small_caps('Today:')}</b> {usage}/{DAILY_LIMIT}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=to_small_caps("Back"), callback_data="back_start", icon_custom_emoji_id=get_eid("🔙"), style=ButtonStyle.PRIMARY)]
    ])
    await safe_edit(query, text, reply_markup=kb)

@router.callback_query(F.data == "check_join")
async def cb_check_join(query: types.CallbackQuery, bot: Bot):
    from utils.helpers import check_force_join
    joined = await check_force_join(bot, query.from_user.id)
    if joined:
        await query.answer(to_small_caps("Verified! 🎉"))
        await safe_edit(query, get_start_message(), reply_markup=main_menu_kb())
    else:
        await query.answer(to_small_caps("❌ Not joined yet!"), show_alert=True)
