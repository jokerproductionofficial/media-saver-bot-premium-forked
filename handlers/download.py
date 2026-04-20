"""handlers/download.py — aiogram v3 download flow with premium UI."""

import os
import aiohttp
import asyncio
import logging
import time
from typing import Dict

from aiogram import Bot, F, Router, types
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import downloader as dl
from config import BOT_NAME, FAST_UPLOAD_DOCUMENT_THRESHOLD_MB
from database import db
from utils.helpers import (
    format_bytes,
    format_views,
    get_eid,
    get_etag,
    get_progress_bar,
    guard_user,
    safe_edit,
    to_small_caps,
    math_bold_italic,
)
from utils.pyro_client import pyro_app

logger = logging.getLogger(__name__)
router = Router()

# active tasks
_active: Dict[int, asyncio.Task] = {}

_PLATFORM_EMOJI = {
    "youtube": "🎬",
    "instagram": "📸",
    "tiktok": "🎵",
    "twitter": "🐦",
    "pinterest": "📌",
    "telegram": "✈️",
    "facebook": "🌍",
    "generic": "🌐",
}

_DEFAULT_AUDIO_QUALITY = "320"
_FAST_UPLOAD_DOCUMENT_THRESHOLD_BYTES = FAST_UPLOAD_DOCUMENT_THRESHOLD_MB * 1024 * 1024


def _build_info_caption(info: Dict, title_limit: int = 60) -> str:
    title = info.get("title", "Media")
    if len(title) > title_limit:
        title = title[: title_limit - 3] + "..."

    duration = info.get("duration_string", info.get("duration", "N/A"))
    views = format_views(info.get("view_count"))
    
    caption = (
        f"{get_etag(_PLATFORM_EMOJI.get(info.get('platform', 'generic'), '🌐'))} "
        f"<b>{to_small_caps(title)}</b>\n\n"
        f"{get_etag('👤')} <b>{to_small_caps('Uploader:')}</b> "
        f"{to_small_caps(info.get('uploader', 'Unknown'))}\n"
    )

    if views and views != "N/A" and views != "0":
        caption += f"{get_etag('👁')} <b>{to_small_caps('Views:')}</b> {views}\n"
    
    if duration and duration != "N/A" and duration != "00:00":
        caption += f"{get_etag('🕐')} <b>{to_small_caps('Duration:')}</b> {duration}\n"

    caption += f"\n{get_etag('👇')} <b>{to_small_caps('Choose Download Type:')}</b>"
    return caption


def _build_media_keyboard(info: Dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if "video" in info["media_types"]:
        if info.get("is_youtube"):
            builder.row(
                InlineKeyboardButton(
                    text=to_small_caps("Video"),
                    callback_data=f"type:v:{info['id']}",
                    icon_custom_emoji_id=get_eid("🎬"),
                    style=ButtonStyle.SUCCESS,
                )
            )
        else:
            builder.row(
                InlineKeyboardButton(
                    text=to_small_caps("Download Video"),
                    callback_data=f"dl:v:{info['id']}:best",
                    icon_custom_emoji_id=get_eid("🎬"),
                    style=ButtonStyle.SUCCESS,
                )
            )

    if "audio" in info["media_types"]:
        builder.row(
            InlineKeyboardButton(
                text=to_small_caps("Audio (MP3)"),
                callback_data=f"dl:a:{info['id']}:{_DEFAULT_AUDIO_QUALITY}",
                icon_custom_emoji_id=get_eid("🎵"),
                style=ButtonStyle.PRIMARY,
            )
        )

    if "image" in info["media_types"]:
        builder.row(
            InlineKeyboardButton(
                text=to_small_caps("Image"),
                callback_data=f"dl:i:{info['id']}:best",
                icon_custom_emoji_id=get_eid("🖼"),
                style=ButtonStyle.SUCCESS,
            )
        )

    builder.row(
        InlineKeyboardButton(
            text=to_small_caps("Cancel"),
            callback_data="cancel",
            icon_custom_emoji_id=get_eid("❌"),
            style=ButtonStyle.DANGER,
        )
    )

    return builder.as_markup()


async def _queue_download(
    query: types.CallbackQuery,
    bot: Bot,
    info: Dict,
    mtype: str,
    quality: str,
):
    user_id = query.from_user.id
    if user_id in _active:
        _active[user_id].cancel()

    prog_msg = await query.message.answer(
        f"{get_etag('📥')} <b>{to_small_caps('Preparing...')}</b>",
        parse_mode="HTML",
    )

    task = asyncio.create_task(_run_download(query, bot, info, mtype, quality, prog_msg))
    _active[user_id] = task


@router.message(F.text.regexp(r"(https?://\S+)"))
async def handle_link(message: types.Message, bot: Bot):
    url = message.text.strip()
    platform = dl.detect_platform(url)
    if not platform:
        return

    if not await guard_user(message, bot):
        return

    emoji = _PLATFORM_EMOJI.get(platform, "🌐")
    status = await message.answer(
        f"{get_etag(emoji)} {to_small_caps('Fetching info...')}",
        parse_mode="HTML",
    )

    try:
        info = await dl.fetch_info(url)
    except Exception as e:
        await status.edit_text(
            f"❌ <b>{to_small_caps('Error:')}</b> {to_small_caps(str(e)[:100])}",
            parse_mode="HTML",
        )
        return

    if not hasattr(bot, "_media_info"):
        bot._media_info = {}
    bot._media_info[info["id"]] = info

    caption = _build_info_caption(info)
    keyboard = _build_media_keyboard(info)

    await status.delete()
    if info.get("thumbnail"):
        try:
            await message.answer_photo(
                info["thumbnail"],
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return
        except Exception:
            pass

    await message.answer(caption, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("type:"))
async def cb_type_select(query: types.CallbackQuery, bot: Bot):
    data = query.data.split(":")
    mtype = data[1]
    vid_id = data[2]

    info = getattr(bot, "_media_info", {}).get(vid_id)
    if not info:
        await query.answer()
        await safe_edit(query, "❌ Session expired. Please send the link again.")
        return

    if mtype != "v":
        await query.answer("📥 Starting MP3...")
        await _queue_download(query, bot, info, "a", _DEFAULT_AUDIO_QUALITY)
        return

    await query.answer()

    builder = InlineKeyboardBuilder()
    qualities = list(dict.fromkeys(info.get("available_qualities") or ["360p", "720p"]))
    for quality in qualities:
        builder.add(
            InlineKeyboardButton(
                text=to_small_caps(quality),
                callback_data=f"dl:v:{vid_id}:{quality}",
                icon_custom_emoji_id=get_eid("🎬"),
                style=ButtonStyle.SUCCESS,
            )
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(
            text=to_small_caps("Back"),
            callback_data=f"back_info:{vid_id}",
            icon_custom_emoji_id=get_eid("🔙"),
            style=ButtonStyle.PRIMARY,
        )
    )

    await safe_edit(
        query,
        f"{get_etag('📊')} <b>{to_small_caps('Select')} {to_small_caps('Video Quality')}:</b>",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("back_info:"))
async def cb_back_info(query: types.CallbackQuery, bot: Bot):
    await query.answer()
    vid_id = query.data.split(":")[1]
    info = getattr(bot, "_media_info", {}).get(vid_id)
    if not info:
        return

    await safe_edit(query, _build_info_caption(info), reply_markup=_build_media_keyboard(info))


@router.callback_query(F.data.startswith("dl:"))
async def cb_start_download(query: types.CallbackQuery, bot: Bot):
    await query.answer("📥 Starting...")
    data = query.data.split(":")
    mtype = data[1]
    vid_id = data[2]
    quality = data[3]

    info = getattr(bot, "_media_info", {}).get(vid_id)
    if not info:
        return

    await _queue_download(query, bot, info, mtype, quality)


def progress_callback(current, total, msg, start_time, bot_name, loop):
    """Thread-safe callback for Pyrogram upload progress."""
    if not total:
        return

    now = time.time()
    diff = now - start_time
    if diff < 1:
        return

    # Throttle updates to ~2 seconds for better feel.
    last_update = getattr(msg, "_last_progress_update", 0)
    if now - last_update < 2 and current < total:
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
        f"<b>{to_small_caps('Status')}:</b> {format_bytes(current)} "
        f"{to_small_caps('of')} {format_bytes(total)}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<b>{to_small_caps('Smooth Transfer → Activated')}</b> {get_etag('✅')}"
    )

    try:
        coro = msg.edit_text(text, parse_mode="HTML")
        asyncio.run_coroutine_threadsafe(coro, loop)
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
            if d["status"] == "downloading":
                now = time.time()
                last_update = getattr(prog_msg, "_last_dl_update", 0)
                if now - last_update < 4:
                    return
                prog_msg._last_dl_update = now

                current = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                if not total:
                    return

                percentage = (current / total) * 100
                speed = d.get("speed", 0)
                bar = get_progress_bar(current, total)

                text = (
                    f"<b>{BOT_NAME} {to_small_caps('Download Progress Bar')}</b> {get_etag('✅')}\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"<code>{bar}</code>\n"
                    f"<b>{to_small_caps('Percentage')}:</b> {percentage:.2f}%\n"
                    f"<b>{to_small_caps('Speed')}:</b> {format_bytes(speed)}/s\n"
                    f"<b>{to_small_caps('Status')}:</b> {format_bytes(current)} "
                    f"{to_small_caps('of')} {format_bytes(total)}\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"<b>{to_small_caps('Smooth Transfer → Activated')}</b> {get_etag('✅')}"
                )

                coro = bot.edit_message_text(
                    text=text,
                    chat_id=prog_msg.chat.id,
                    message_id=prog_msg.message_id,
                    parse_mode="HTML",
                )
                asyncio.run_coroutine_threadsafe(coro, loop)

        if mtype == "v":
            preferred_formats = (info.get("quality_candidates") or {}).get(quality)
            filepath = await dl.download_media(
                info["url"],
                info["platform"],
                user_id,
                quality,
                download_hook,
                preferred_formats=preferred_formats,
                direct_video_url=info.get("_direct_video_url"),
            )
        elif mtype == "a":
            filepath = await dl.download_audio(info["url"], quality, user_id, download_hook)
        elif mtype == "i":
            filepath = await dl.download_media(
                info["url"],
                info["platform"],
                user_id,
                "best",
                download_hook,
                direct_video_url=info.get("_direct_video_url"),
            )

        if not filepath:
            raise Exception("File could not be downloaded.")

        # Capture metadata for better Telegram display.
        results = {}
        if isinstance(filepath, dict):
            results = filepath
            filepath = results.get("filepath")

        try:
            await prog_msg.edit_text(
                f"{get_etag('📤')} <b>{to_small_caps('Uploading...')}</b>",
                parse_mode="HTML",
            )
        except TelegramBadRequest as _e:
            if "message is not modified" not in str(_e):
                raise

        # Download thumbnail if available for direct video view.
        thumb_path = None
        thumb_url = results.get("thumbnail") or info.get("thumbnail")
        if thumb_url:
            try:
                thumb_name = f"thumb_{user_id}_{int(time.time())}.jpg"
                thumb_path = os.path.join(dl.DOWNLOAD_DIR, thumb_name)
                async with aiohttp.ClientSession() as session:
                    async with session.get(thumb_url) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            with open(thumb_path, "wb") as f:
                                f.write(content)
            except Exception:
                thumb_path = None

        # Final Premium Caption
        caption = (
            f"{get_etag('✅')} <b>{math_bold_italic(info['title'][:60])}</b>\n\n"
            f"{get_etag('🎬')} <b>{to_small_caps('Platform')}:</b> {to_small_caps(info['platform'])}\n"
            f"{get_etag('📊')} <b>{to_small_caps('Quality')}:</b> {to_small_caps(quality)}"
        )

        file_size = os.path.getsize(filepath)
        use_fast_upload = mtype == "v" and file_size >= _FAST_UPLOAD_DOCUMENT_THRESHOLD_BYTES
        
        caption += (
            f"\n{get_etag('📦')} <b>{to_small_caps('Size')}:</b> "
            f"{format_bytes(file_size)}"
        )

        start_time = time.time()
        args = (prog_msg, start_time, BOT_NAME, loop)

        upload_text = (
            f"{get_etag('⚡')} <b>{to_small_caps('Fast Upload Mode')}</b>\n"
            f"{get_etag('📦')} <b>{to_small_caps('Large File')}</b>: "
            f"{format_bytes(file_size)}\n"
            f"{get_etag('📁')} <b>{to_small_caps('Sending as file for faster delivery')}</b>"
            if use_fast_upload
            else f"{get_etag('📤')} <b>{to_small_caps('Uploading...')}</b>"
        )

        try:
            await prog_msg.edit_text(upload_text, parse_mode="HTML")
        except TelegramBadRequest as _e:
            if "message is not modified" not in str(_e):
                raise
        pyro_app.loop = loop

        try:
            if mtype == "a":
                await pyro_app.send_audio(
                    user_id,
                    filepath,
                    caption=caption,
                    parse_mode="html",
                    progress=progress_callback,
                    progress_args=args,
                )
            elif mtype == "i":
                await pyro_app.send_photo(
                    user_id,
                    filepath,
                    caption=caption,
                    parse_mode="html",
                    progress=progress_callback,
                    progress_args=args,
                )
            elif use_fast_upload:
                await pyro_app.send_document(
                    chat_id=user_id,
                    document=filepath,
                    caption=caption,
                    parse_mode="html",
                    progress=progress_callback,
                    progress_args=args,
                )
            else:
                await pyro_app.send_video(
                    chat_id=user_id,
                    video=filepath,
                    caption=caption,
                    parse_mode="html",
                    duration=int(float(results.get("duration_raw") or info.get("duration_raw") or 0)),
                    width=int(float(results.get("width") or 0)),
                    height=int(float(results.get("height") or 0)),
                    thumb=thumb_path,
                    supports_streaming=True,
                    progress=progress_callback,
                    progress_args=args,
                )
        finally:
            if thumb_path:
                dl.cleanup_file(thumb_path)

        db.increment_daily_usage(user_id)
        db.increment_total_downloads(user_id)
        db.log_download(user_id, info["url"], quality, mtype, "success")

        await prog_msg.delete()

    except Exception as e:
        err_str = str(e)
        if "message is not modified" in err_str:
            # Harmless race: progress hook already showed this text, skip logging.
            return
        logger.error(f"Download failed: {e}")
        try:
            await prog_msg.edit_text(
                f"{get_etag('❌')} <b>Failed:</b> {err_str[:100]}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as _e2:
            if "message is not modified" not in str(_e2):
                logger.warning(f"Could not update failure message: {_e2}")
        db.log_download(user_id, info["url"], quality, mtype, "failed")
    finally:
        if filepath:
            dl.cleanup_file(filepath)
        _active.pop(user_id, None)


@router.callback_query(F.data == "cancel")
async def cb_cancel(query: types.CallbackQuery):
    await query.answer(to_small_caps("Cancelled"))
    uid = query.from_user.id
    if uid in _active:
        _active[uid].cancel()
    await query.message.delete()
