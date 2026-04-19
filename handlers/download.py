"""handlers/download.py — aiogram v3 Download flow with ALL resolutions."""

import os
import aiohttp
import asyncio
import logging
from typing import Dict

from aiogram import Router, types, F, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ButtonStyle

import downloader as dl
from config import AUDIO_QUALITIES
from database import db
from utils.helpers import (
    get_eid, get_etag, guard_user, format_views, safe_edit, to_small_caps,
    format_bytes, get_progress_bar
)
from utils.pyro_client import pyro_app
from config import BOT_NAME
import time

logger = logging.getLogger(__name__)
router = Router()

# active tasks
_active: Dict[int, asyncio.Task] = {}

_PLATFORM_EMOJI = {
    "youtube": "🎬", "instagram": "📸", "tiktok": "🎵", "twitter": "🐦",
    "pinterest": "📌", "telegram": "✈️", "facebook": "🌍", "generic": "🌐",
}

@router.message(F.text.regexp(r"(https?://\S+)"))
async def handle_link(message: types.Message, bot: Bot):
    url = message.text.strip()
    platform = dl.detect_platform(url)
    if not platform: return

    if not await guard_user(message, bot):
        return

    emoji = _PLATFORM_EMOJI.get(platform, "🌐")
    status = await message.answer(f"{get_etag(emoji)} {to_small_caps('Fetching info...')}")

    try:
        info = await dl.fetch_info(url)
    except Exception as e:
        await status.edit_text(f"❌ <b>{to_small_caps('Error:')}</b> {to_small_caps(str(e)[:100])}", parse_mode="HTML")
        return

    title = info['title']
    caption = (
        f"{get_etag(emoji)} <b>{to_small_caps(title)}</b>\n\n"
        f"{get_etag('👤')} <b>{to_small_caps('Uploader:')}</b> {to_small_caps(info['uploader'])}\n"
    )
    if info['duration'] != "N/A":
        caption += f"{get_etag('🕐')} <b>{to_small_caps('Duration:')}</b> {info['duration']}\n"
    if info['view_count']:
        caption += f"{get_etag('👁')} <b>{to_small_caps('Views:')}</b> {format_views(info['view_count'])}\n"
    
    caption += f"\n{get_etag('👇')} <b>{to_small_caps('Choose download type:')}</b>"

    builder = InlineKeyboardBuilder()
    if "video" in info['media_types']:
        if info['is_youtube']:
            builder.row(InlineKeyboardButton(text=to_small_caps("Video"), callback_data=f"type:v:{info['id']}", icon_custom_emoji_id=get_eid("🎬"), style=ButtonStyle.SUCCESS))
        else:
            builder.row(InlineKeyboardButton(text=to_small_caps("Download Video"), callback_data=f"dl:v:{info['id']}:best", icon_custom_emoji_id=get_eid("🎬"), style=ButtonStyle.SUCCESS))
    
    if "audio" in info['media_types']:
        builder.row(InlineKeyboardButton(text=to_small_caps("Audio (MP3)"), callback_data=f"type:a:{info['id']}", icon_custom_emoji_id=get_eid("🎵"), style=ButtonStyle.PRIMARY))
    
    if "image" in info['media_types']:
        builder.row(InlineKeyboardButton(text=to_small_caps("Image"), callback_data=f"dl:i:{info['id']}:best", icon_custom_emoji_id=get_eid("🖼"), style=ButtonStyle.SUCCESS))

    builder.row(InlineKeyboardButton(text=to_small_caps("Cancel"), callback_data="cancel", icon_custom_emoji_id=get_eid("❌"), style=ButtonStyle.DANGER))

    if not hasattr(bot, "_media_info"): bot._media_info = {}
    bot._media_info[info['id']] = info

    await status.delete()
    if info['thumbnail']:
        try:
            await message.answer_photo(info['thumbnail'], caption=caption, reply_markup=builder.as_markup(), parse_mode="HTML")
        except Exception:
            await message.answer(caption, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(caption, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("type:"))
async def cb_type_select(query: types.CallbackQuery, bot: Bot):
    await query.answer()
    data = query.data.split(":")
    mtype = data[1]
    vid_id = data[2]
    
    info = getattr(bot, "_media_info", {}).get(vid_id)
    if not info:
        await safe_edit(query, "❌ Session expired. Please send the link again.")
        return

    builder = InlineKeyboardBuilder()
    if mtype == 'v':
        quals = info['available_qualities']
        for q in quals:
            builder.add(InlineKeyboardButton(text=to_small_caps(q), callback_data=f"dl:v:{vid_id}:{q}", icon_custom_emoji_id=get_eid("🎬"), style=ButtonStyle.SUCCESS))
        builder.adjust(2)
    else:
        for label, kbps in AUDIO_QUALITIES.items():
            builder.row(InlineKeyboardButton(text=to_small_caps(label), callback_data=f"dl:a:{vid_id}:{kbps}", icon_custom_emoji_id=get_eid("🎵"), style=ButtonStyle.PRIMARY))
    
    builder.row(InlineKeyboardButton(text=to_small_caps("Back"), callback_data=f"back_info:{vid_id}", icon_custom_emoji_id=get_eid("🔙"), style=ButtonStyle.PRIMARY))
    
    label = to_small_caps("Video Quality") if mtype == 'v' else to_small_caps("Audio Quality")
    await safe_edit(query, f"{get_etag('📊')} <b>{to_small_caps('Select')} {label}:</b>", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("back_info:"))
async def cb_back_info(query: types.CallbackQuery, bot: Bot):
    await query.answer()
    vid_id = query.data.split(":")[1]
    info = getattr(bot, "_media_info", {}).get(vid_id)
    if not info: return

    platform = info.get('platform', 'generic')
    emoji = _PLATFORM_EMOJI.get(platform, "🌐")
    
    caption = (
        f"{get_etag(emoji)} <b>{to_small_caps(info['title'])}</b>\n\n"
        f"{get_etag('👤')} <b>{to_small_caps('Uploader:')}</b> {to_small_caps(info['uploader'])}\n"
    )
    if info['duration'] != "N/A":
        caption += f"{get_etag('🕐')} <b>{to_small_caps('Duration:')}</b> {info['duration']}\n"
    if info['view_count']:
        caption += f"{get_etag('👁')} <b>{to_small_caps('Views:')}</b> {format_views(info['view_count'])}\n"
    
    caption += f"\n{get_etag('👇')} <b>{to_small_caps('Choose download type:')}</b>"

    builder = InlineKeyboardBuilder()
    if "video" in info['media_types']:
        if info['is_youtube']:
            builder.row(InlineKeyboardButton(text=to_small_caps("Video"), callback_data=f"type:v:{info['id']}", icon_custom_emoji_id=get_eid("🎬"), style=ButtonStyle.SUCCESS))
        else:
            builder.row(InlineKeyboardButton(text=to_small_caps("Download Video"), callback_data=f"dl:v:{info['id']}:best", icon_custom_emoji_id=get_eid("🎬"), style=ButtonStyle.SUCCESS))
    
    if "audio" in info['media_types']:
        builder.row(InlineKeyboardButton(text=to_small_caps("Audio (MP3)"), callback_data=f"type:a:{info['id']}", icon_custom_emoji_id=get_eid("🎵"), style=ButtonStyle.PRIMARY))
    
    if "image" in info['media_types']:
        builder.row(InlineKeyboardButton(text=to_small_caps("Image"), callback_data=f"dl:i:{info['id']}:best", icon_custom_emoji_id=get_eid("🖼"), style=ButtonStyle.SUCCESS))

    builder.row(InlineKeyboardButton(text=to_small_caps("Cancel"), callback_data="cancel", icon_custom_emoji_id=get_eid("❌"), style=ButtonStyle.DANGER))

    await safe_edit(query, caption, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("dl:"))
async def cb_start_download(query: types.CallbackQuery, bot: Bot):
    await query.answer("📥 Starting...")
    data = query.data.split(":")
    mtype = data[1]
    vid_id = data[2]
    quality = data[3]
    
    info = getattr(bot, "_media_info", {}).get(vid_id)
    if not info: return

    user_id = query.from_user.id
    if user_id in _active: _active[user_id].cancel()

    prog_msg = await query.message.answer(f"{get_etag('📥')} <b>{to_small_caps('Preparing...')}</b>", parse_mode="HTML")
    
    task = asyncio.create_task(_run_download(query, bot, info, mtype, quality, prog_msg))
    _active[user_id] = task

async def progress_callback(current, total, msg, start_time, bot_name):
    """Callback for Pyrogram upload progress."""
    now = time.time()
    diff = now - start_time
    if diff < 1: return # Wait at least 1s for first update
    
    # Throttle updates to ~3 seconds to stay safe
    last_update = getattr(msg, "_last_progress_update", 0)
    if now - last_update < 3 and current < total:
        return
    msg._last_progress_update = now

    percentage = current * 100 / total
    speed = current / diff
    
    bar = get_progress_bar(current, total)
    
    text = (
        f"<b>{bot_name} {to_small_caps('Upload Progress Bar')}</b> {get_etag('✅')}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<code>{bar}</code>\n"
        f"<b>{to_small_caps('Percentage')}:</b> {percentage:.2f}%\n"
        f"<b>{to_small_caps('Speed')}:</b> {format_bytes(speed)}/s\n"
        f"<b>{to_small_caps('Status')}:</b> {format_bytes(current)} {to_small_caps('of')} {format_bytes(total)}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<b>{to_small_caps('Smooth Transfer → Activated')}</b> {get_etag('✅')}"
    )
    
    try:
        await msg.edit_text(text, parse_mode="HTML")
    except Exception:
        pass


async def _run_download(query, bot, info, mtype, quality, prog_msg):
    user_id = query.from_user.id
    filepath = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    
    try:
        def download_hook(d):
            if d['status'] == 'downloading':
                now = time.time()
                last_update = getattr(prog_msg, "_last_dl_update", 0)
                if now - last_update < 4: return # Slightly longer throttle for safety
                prog_msg._last_dl_update = now

                current = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                if not total: return
                
                percentage = (current / total) * 100
                speed = d.get('speed', 0)
                
                bar = get_progress_bar(current, total)
                
                text = (
                    f"<b>{BOT_NAME} {to_small_caps('Download Progress Bar')}</b> {get_etag('✅')}\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"<code>{bar}</code>\n"
                    f"<b>{to_small_caps('Percentage')}:</b> {percentage:.2f}%\n"
                    f"<b>{to_small_caps('Speed')}:</b> {format_bytes(speed)}/s\n"
                    f"<b>{to_small_caps('Status')}:</b> {format_bytes(current)} {to_small_caps('of')} {format_bytes(total)}\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"<b>{to_small_caps('Smooth Transfer → Activated')}</b> {get_etag('✅')}"
                )
                
                # Using bot.edit_message_text directly for better thread safety with aiogram
                coro = bot.edit_message_text(
                    text=text,
                    chat_id=prog_msg.chat.id,
                    message_id=prog_msg.message_id,
                    parse_mode="HTML"
                )
                asyncio.run_coroutine_threadsafe(coro, loop)

        if mtype == 'v':
            filepath = await dl.download_media(info['url'], info['platform'], user_id, quality, download_hook)
        elif mtype == 'a':
            filepath = await dl.download_audio(info['url'], quality, user_id, download_hook)
        elif mtype == 'i': # image
            # For images, we can often just pick the best thumbnail if download_media fails
            try:
                filepath = await dl.download_media(info['url'], info['platform'], user_id, "best")
            except Exception:
                if info.get('thumbnail'):
                    # Fallback to downloading thumbnail directly
                    async with aiohttp.ClientSession() as session:
                        async with session.get(info['thumbnail']) as resp:
                            if resp.status == 200:
                                ext = info['thumbnail'].split('.')[-1].split('?')[0]
                                if len(ext) > 4: ext = 'jpg'
                                filename = f"{user_id}_img_{int(asyncio.get_event_loop().time())}.{ext}"
                                filepath = os.path.join(dl.DOWNLOAD_DIR, filename)
                                with open(filepath, 'wb') as f:
                                    f.write(await resp.read())
                if not filepath: raise

        await prog_msg.edit_text(f"{get_etag('📤')} <b>{to_small_caps('Uploading...')}</b>", parse_mode="HTML")
        
        caption = (
            f"{get_etag('✅')} <b>{to_small_caps(info['title'][:50])}</b>\n"
            f"{get_etag(_PLATFORM_EMOJI.get(info['platform'], '🌐'))} <b>{to_small_caps('Platform')}:</b> {to_small_caps(info['platform'])}\n"
            f"<b>{to_small_caps('Quality')}:</b> {to_small_caps(quality)}"
        )

        # Use Pyrogram (MTProto) for sending to support up to 2GB
        start_time = time.time()
        args = (prog_msg, start_time, BOT_NAME)

        if mtype == 'a':
            await pyro_app.send_audio(user_id, filepath, caption=caption, progress=progress_callback, progress_args=args)
        elif mtype == 'i':
            await pyro_app.send_photo(user_id, filepath, caption=caption, progress=progress_callback, progress_args=args)
        else:
            await pyro_app.send_video(user_id, filepath, caption=caption, supports_streaming=True, progress=progress_callback, progress_args=args)

        db.increment_daily_usage(user_id)
        db.increment_total_downloads(user_id)
        db.log_download(user_id, info['url'], quality, mtype, "success")
        
        await prog_msg.delete()

    except Exception as e:
        logger.error(f"Download failed: {e}")
        await prog_msg.edit_text(f"{get_etag('❌')} <b>Failed:</b> {str(e)[:100]}", parse_mode="HTML")
        db.log_download(user_id, info['url'], quality, mtype, "failed")
    finally:
        if filepath: dl.cleanup_file(filepath)
        _active.pop(user_id, None)

@router.callback_query(F.data == "cancel")
async def cb_cancel(query: types.CallbackQuery):
    await query.answer(to_small_caps("Cancelled"))
    uid = query.from_user.id
    if uid in _active: _active[uid].cancel()
    await query.message.delete()
