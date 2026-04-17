"""handlers/admin.py — aiogram v3 Admin Panel."""

import asyncio
from datetime import datetime
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ButtonStyle
from aiogram.utils.keyboard import InlineKeyboardBuilder

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from config import ADMIN_ID, BOT_NAME, DAILY_LIMIT, MAX_FILE_SIZE_MB
from database import db
from downloader import cleanup_old_files
from utils.helpers import get_eid, get_etag, safe_edit, to_small_caps

router = Router()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_ban_id = State()
    waiting_for_unban_id = State()

def admin_only(func):
    """Decorator: restrict to ADMIN_ID."""
    async def wrapper(event: types.Message | types.CallbackQuery, **kwargs):
        if event.from_user.id != ADMIN_ID:
            if isinstance(event, types.Message):
                await event.answer(f"{get_etag('❌')} {to_small_caps('Admin only.')}")
            else:
                await event.answer(f"{get_etag('❌')} {to_small_caps('Admin only.')}", show_alert=True)
            return
        return await func(event, **kwargs)
    return wrapper

def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=to_small_caps("Stats"), callback_data="adm:stats", icon_custom_emoji_id=get_eid("📊"), style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text=to_small_caps("Logs"), callback_data="adm:logs_menu", icon_custom_emoji_id=get_eid("📋"), style=ButtonStyle.PRIMARY),
        ],
        [
            InlineKeyboardButton(text=to_small_caps("Users"), callback_data="adm:users_menu", icon_custom_emoji_id=get_eid("👥"), style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text=to_small_caps("Cleanup"), callback_data="adm:cleanup", icon_custom_emoji_id=get_eid("🧹"), style=ButtonStyle.DANGER),
        ],
        [
            InlineKeyboardButton(text=to_small_caps("Broadcast Message"), callback_data="adm:broadcast", icon_custom_emoji_id=get_eid("📢"), style=ButtonStyle.SUCCESS),
        ],
    ])

@router.message(Command("admin"))
@admin_only
async def cmd_admin(message: types.Message, **kwargs):
    stats = db.get_stats()
    text = (
        f"{get_etag('👑')} <b>{to_small_caps('Admin Panel')} — {to_small_caps(BOT_NAME)}</b>\n\n"
        f"👥 <b>{to_small_caps('Total Users:')}</b> {stats['total_users']}\n"
        f"📥 <b>{to_small_caps('Total Downloads:')}</b> {stats['total_downloads']}\n"
        f"📅 <b>{to_small_caps('Today Downloads:')}</b> {stats['today_downloads']}\n"
        f"✅ <b>{to_small_caps('Success Rate:')}</b> {stats.get('success_rate', 0)}%\n"
    )
    await message.answer(text, reply_markup=admin_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("adm:"))
@admin_only
async def cb_admin(query: types.CallbackQuery, bot: Bot, state: FSMContext, **kwargs):
    action = query.data.split(":")[1]
    
    if action == "broadcast":
        await state.set_state(AdminStates.waiting_for_broadcast)
        text = (
            f"{get_etag('📢')} <b>{to_small_caps('Broadcast Mode')}</b>\n\n"
            f"{to_small_caps('Send the message you want to broadcast.')}\n"
            f"<i>{to_small_caps('Supports Text, Photos, Videos, and Stickers')}</i>\n\n"
            f"{to_small_caps('Type')} <code>/cancel</code> {to_small_caps('to stop.')}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=to_small_caps("Cancel"), callback_data="adm:back", style=ButtonStyle.DANGER)]])
        await safe_edit(query, text, reply_markup=kb)
        return

    if action == "stats":
        stats = db.get_stats()
        text = (
            f"{get_etag('📊')} <b>Bot Statistics</b>\n\n"
            f"{get_etag('👥')} Total users: {stats['total_users']}\n"
            f"{get_etag('📥')} Total downloads: {stats['total_downloads']}\n"
            f"{get_etag('📅')} Today's downloads: {stats['today_downloads']}\n"
            f"🕐 Server time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )
    
    elif action == "users_menu":
        stats = db.get_stats()
        text = (
            f"{get_etag('👥')} <b>{to_small_caps('User Management')}</b>\n\n"
            f"• <b>{to_small_caps('Total Users:')}</b> {stats['total_users']}\n\n"
            f"{to_small_caps('Choose an action below:')}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=to_small_caps("Ban User"), callback_data="adm:ban_ask", style=ButtonStyle.DANGER),
                InlineKeyboardButton(text=to_small_caps("Unban User"), callback_data="adm:unban_ask", style=ButtonStyle.SUCCESS),
            ],
            [InlineKeyboardButton(text=to_small_caps("Back"), callback_data="adm:back", style=ButtonStyle.PRIMARY)]
        ])
        await safe_edit(query, text, reply_markup=kb)
        return

    elif action == "ban_ask":
        await AdminStates.waiting_for_ban_id.set_state(kwargs.get('state')) # Handle state if passed
        # Workaround for aiogram v3 state in cb
        from aiogram.fsm.context import FSMContext
        state: FSMContext = kwargs.get('state') 
        if state: await state.set_state(AdminStates.waiting_for_ban_id)
        
        text = f"{get_etag('🚫')} <b>{to_small_caps('Ban User')}</b>\n\n{to_small_caps('Enter the User ID you want to ban:')}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=to_small_caps("Cancel"), callback_data="adm:users_menu", style=ButtonStyle.DANGER)]])
        await safe_edit(query, text, reply_markup=kb)
        return

    elif action == "unban_ask":
        from aiogram.fsm.context import FSMContext
        state: FSMContext = kwargs.get('state')
        if state: await state.set_state(AdminStates.waiting_for_unban_id)
        
        text = f"{get_etag('✅')} <b>{to_small_caps('Unban User')}</b>\n\n{to_small_caps('Enter the User ID you want to unban:')}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=to_small_caps("Cancel"), callback_data="adm:users_menu", style=ButtonStyle.DANGER)]])
        await safe_edit(query, text, reply_markup=kb)
        return

    elif action == "logs_menu":
        logs = db.get_recent_logs(15)
        if not logs:
            text = f"{get_etag('📋')} <b>{to_small_caps('Recent Logs')}</b>\n\n{to_small_caps('No recent logs found.')}"
        else:
            lines = [f"{get_etag('📋')} <b>{to_small_caps('Recent Downloads')}</b>\n"]
            for log in logs:
                icon = "✅" if log['status'] == 'success' else '❌'
                time = log['created_at'][11:16]
                lines.append(f"{get_etag(icon)} <code>{log['user_id']}</code> | {log['file_type']} | {time}")
            text = "\n".join(lines)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=to_small_caps("Back"), callback_data="adm:back", style=ButtonStyle.PRIMARY)]])
        await safe_edit(query, text, reply_markup=kb)
        return

    elif action == "back":
        stats = db.get_stats()
        text = (
            f"{get_etag('👑')} <b>{to_small_caps('Admin Panel')} — {to_small_caps(BOT_NAME)}</b>\n\n"
            f"{get_etag('👥')} <b>{to_small_caps('Users:')}</b> {stats['total_users']}\n"
            f"{get_etag('📥')} <b>{to_small_caps('Total Downloads:')}</b> {stats['total_downloads']}\n"
            f"{get_etag('📅')} <b>{to_small_caps('Today:')}</b> {stats['today_downloads']}\n\n"
            f"{get_etag('👇')} <b>{to_small_caps('Choose an option:')}</b>"
        )
        await safe_edit(query, text, reply_markup=admin_menu_kb())
        return

    else:
        text = to_small_caps("Admin Section")

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=to_small_caps("Back"), callback_data="adm:back", icon_custom_emoji_id=get_eid("🔙"), style=ButtonStyle.PRIMARY))
    await safe_edit(query, text, reply_markup=kb.as_markup())

@router.message(Command("cancel"))
@admin_only
async def cmd_cancel_admin(message: types.Message, state: FSMContext, **kwargs):
    await state.clear()
    await message.answer(f"{get_etag('✅')} {to_small_caps('State cleared/Mode cancelled.')}", reply_markup=admin_menu_kb())

@router.message(AdminStates.waiting_for_broadcast)
@admin_only
async def process_broadcast(message: types.Message, state: FSMContext, bot: Bot, **kwargs):
    if message.text == "/cancel":
        await state.clear()
        await message.answer(f"{get_etag('✅')} {to_small_caps('Broadcast cancelled.')}")
        return

    users = db.get_all_users()
    count = 0
    failed = 0
    
    status_msg = await message.answer(f"{get_etag('⏳')} <b>{to_small_caps('Sending broadcast to')} {len(users)} {to_small_caps('users...')}</b>")
    
    for user_id in users:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            count += 1
            if count % 10 == 0:
                await status_msg.edit_text(f"{get_etag('⏳')} <b>{to_small_caps('Progress:')} {count}/{len(users)}</b>")
        except Exception:
            failed += 1
        await asyncio.sleep(0.05) # Rate limiting
    
    await state.clear()
    db.log_broadcast(str(message.text or "Media"), count)
    
    final_text = (
        f"{get_etag('✅')} <b>{to_small_caps('Broadcast Completed')}</b>\n\n"
        f"📊 <b>{to_small_caps('Success:')}</b> {count}\n"
        f"❌ <b>{to_small_caps('Failed:')}</b> {failed}"
    )
    await message.answer(final_text, reply_markup=admin_menu_kb())

@router.message(AdminStates.waiting_for_ban_id)
@admin_only
async def process_ban(message: types.Message, state: FSMContext, **kwargs):
    try:
        user_id = int(message.text)
        db.ban_user(user_id)
        await state.clear()
        await message.answer(f"{get_etag('🚫')} <b>{to_small_caps('User')} <code>{user_id}</code> {to_small_caps('has been banned.')}</b>", reply_markup=admin_menu_kb())
    except ValueError:
        await message.answer(f"❌ {to_small_caps('Please enter a valid numerical User ID.')}")

@router.message(AdminStates.waiting_for_unban_id)
@admin_only
async def process_unban(message: types.Message, state: FSMContext, **kwargs):
    try:
        user_id = int(message.text)
        db.unban_user(user_id)
        await state.clear()
        await message.answer(f"{get_etag('✅')} <b>{to_small_caps('User')} <code>{user_id}</code> {to_small_caps('has been unbanned.')}</b>", reply_markup=admin_menu_kb())
    except ValueError:
        await message.answer(f"❌ {to_small_caps('Please enter a valid numerical User ID.')}")
