"""downloader.py - Media downloader with dynamic resolutions."""

import asyncio
import logging
import os
import re
from typing import Callable, Dict, List, Optional

import aiohttp
import yt_dlp

from config import COOKIES_FILE, DOWNLOAD_DIR, MAX_FILE_SIZE_MB, YT_COOKIES_FILE

logger = logging.getLogger(__name__)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)


def detect_platform(url: str) -> Optional[str]:
    url = url.lower()
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "instagram.com" in url:
        return "instagram"
    if "tiktok.com" in url:
        return "tiktok"
    if "twitter.com" in url or "x.com" in url:
        return "twitter"
    if "pinterest.com" in url or "pin.it" in url:
        return "pinterest"
    if "facebook.com" in url or "fb.watch" in url:
        return "facebook"
    if "t.me" in url or "telegram.me" in url:
        return "telegram"
    return "generic"


def _get_cookie_file(platform: str) -> Optional[str]:
    if platform == "youtube":
        return YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None
    return COOKIES_FILE if os.path.exists(COOKIES_FILE) else None


def get_ytdl_opts(platform: str = "generic") -> Dict:
    # Keep shared options format-agnostic so metadata extraction can fetch
    # title, thumbnail, views, and formats without tripping format errors.
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "logtostderr": False,
        "no_color": True,
        "no_playlist": True,
        "extract_flat": False,
        "socket_timeout": 30,
        "retries": 3,
    }

    opts["headers"] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    cookie_file = _get_cookie_file(platform)
    if cookie_file:
        opts["cookiefile"] = cookie_file

    return opts


async def fetch_info(url: str) -> Dict:
    platform = detect_platform(url)
    opts = get_ytdl_opts(platform)
    opts.pop("format", None)
    opts["ignoreerrors"] = False

    loop = asyncio.get_event_loop()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
    except Exception as e:
        logger.warning("yt-dlp failed, trying fallback for %s: %s", url, e)
        return await _fetch_fallback_info(url, platform)

    if not info_dict:
        raise ValueError("Could not extract any info from this URL.")

    formats = info_dict.get("formats", [])
    info = {
        "id": info_dict.get("id"),
        "title": info_dict.get("title", "Unknown Title"),
        "thumbnail": info_dict.get("thumbnail"),
        "url": url,
        "platform": platform,
        "uploader": info_dict.get("uploader", "Unknown"),
        "duration": _format_duration(info_dict.get("duration", 0)),
        "duration_string": _format_duration(info_dict.get("duration", 0)),
        "view_count": info_dict.get("view_count"),
        "is_youtube": platform == "youtube",
        "media_types": [],
        "available_qualities": _extract_available_resolutions(formats),
    }

    if platform == "youtube":
        info["media_types"] = ["video", "audio"]
    else:
        is_video = False
        is_audio = False
        is_image = False

        if platform in ["tiktok", "instagram", "facebook", "telegram"]:
            is_video = True
        elif formats:
            is_video = any(f.get("vcodec") not in (None, "none") for f in formats)

        if any(f.get("acodec") not in (None, "none") for f in formats):
            is_audio = True

        if platform == "pinterest" or info_dict.get("ext") in ["jpg", "jpeg", "png", "webp"]:
            is_image = not is_video

        if is_video:
            info["media_types"].append("video")
        if is_audio:
            info["media_types"].append("audio")
        if is_image:
            info["media_types"].append("image")

        if not info["media_types"]:
            info["media_types"] = ["video"]

    info["duration_raw"] = info_dict.get("duration", 0)
    info["width"] = info_dict.get("width")
    info["height"] = info_dict.get("height")

    return info


def _format_duration(seconds) -> str:
    if not seconds:
        return "N/A"
    try:
        seconds = int(float(seconds))
        mins, secs = divmod(seconds, 60)
        hours, mins = divmod(mins, 60)
        if hours:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"
    except Exception:
        return "N/A"


def _extract_available_resolutions(formats: List[Dict]) -> List[str]:
    heights = set()
    for fmt in formats:
        height = fmt.get("height")
        vcodec = fmt.get("vcodec")
        if height and height >= 144:
            if vcodec and vcodec.lower() != "none":
                heights.add(height)
            elif vcodec is None and fmt.get("acodec") == "none":
                heights.add(height)
            elif fmt.get("ext") == "mp4" and not vcodec:
                heights.add(height)

    if not heights:
        return ["360p", "720p"]

    available = []
    for height in sorted(heights, reverse=True):
        if height >= 2160:
            label = "4K"
        elif height >= 1440:
            label = "1440p"
        else:
            label = f"{height}p"
        if label not in available:
            available.append(label)

    return available


def _build_video_format_candidates(quality: str) -> List[str]:
    if quality == "best":
        return [
            "bestvideo+bestaudio/best",
            "bv*+ba/b",
            "best",
        ]

    if quality.endswith("p") or quality in ["4K", "8K"]:
        height = 2160 if quality == "4K" else 4320 if quality == "8K" else int(quality[:-1])
        return [
            f"bestvideo[height<={height}]+bestaudio/best[height<={height}]",
            f"bv*[height<={height}]+ba/b[height<={height}]",
            f"best[height<={height}]",
            "bestvideo+bestaudio/best",
            "bv*+ba/b",
            "best",
        ]

    return [
        "bestvideo+bestaudio/best",
        "bv*+ba/b",
        "best",
    ]


def _build_audio_format_candidates() -> List[str]:
    return [
        "bestaudio/best",
        "ba/best",
        "best",
    ]


def _iter_download_attempt_opts(platform: str, format_candidates: List[str]) -> List[Dict]:
    attempts = []
    base_opts = get_ytdl_opts(platform)
    has_cookiefile = "cookiefile" in base_opts

    for keep_cookies in ([True, False] if has_cookiefile else [True]):
        for format_selector in format_candidates:
            attempt_opts = get_ytdl_opts(platform)
            attempt_opts["ignoreerrors"] = False
            attempt_opts["format"] = format_selector
            if not keep_cookies:
                attempt_opts.pop("cookiefile", None)
            attempts.append(attempt_opts)

    return attempts


async def download_media(
    url: str,
    platform: str,
    user_id: int,
    quality: str = "best",
    progress_hook: Callable = None,
) -> Dict:
    filename = f"{user_id}_{quality}_{int(asyncio.get_event_loop().time())}"
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{filename}.%(ext)s")

    loop = asyncio.get_event_loop()
    info = None
    last_error = None

    for attempt_number, opts in enumerate(
        _iter_download_attempt_opts(platform, _build_video_format_candidates(quality)),
        start=1,
    ):
        opts["outtmpl"] = outtmpl
        if progress_hook:
            opts["progress_hooks"] = [progress_hook]
        opts["merge_output_format"] = "mp4"
        opts["postprocessor_args"] = {"ffmpeg": ["-movflags", "+faststart"]}

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                if not info:
                    raise ValueError("yt-dlp returned no info for the selected format.")

                filesize = info.get("filesize") or info.get("filesize_approx")
                if filesize and filesize > MAX_FILE_SIZE_MB * 1024 * 1024:
                    raise ValueError(
                        f"File too large: {filesize / (1024 * 1024):.1f}MB (Max: {MAX_FILE_SIZE_MB}MB)"
                    )

                await loop.run_in_executor(None, lambda: ydl.download([url]))
            break
        except Exception as e:
            last_error = e
            info = None
            logger.warning(
                "Download attempt %s failed for %s with format '%s' (cookies=%s): %s",
                attempt_number,
                url,
                opts["format"],
                "cookiefile" in opts,
                e,
            )
    else:
        raise last_error or ValueError("Download failed: no compatible format found.")

    filepath = None
    for file_name in os.listdir(DOWNLOAD_DIR):
        if file_name.startswith(filename):
            filepath = os.path.join(DOWNLOAD_DIR, file_name)
            break

    if not filepath:
        raise Exception("Download failed: File not found after download.")

    return {
        "filepath": filepath,
        "duration": info.get("duration", 0),
        "duration_raw": info.get("duration", 0),
        "width": info.get("width"),
        "height": info.get("height"),
        "thumbnail": info.get("thumbnail"),
    }


async def download_audio(url: str, quality: str, user_id: int, progress_hook: Callable = None) -> str:
    platform = detect_platform(url)
    filename = f"{user_id}_audio_{int(asyncio.get_event_loop().time())}"
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{filename}.%(ext)s")

    loop = asyncio.get_event_loop()
    last_error = None

    for attempt_number, opts in enumerate(
        _iter_download_attempt_opts(platform, _build_audio_format_candidates()),
        start=1,
    ):
        opts["outtmpl"] = outtmpl
        if progress_hook:
            opts["progress_hooks"] = [progress_hook]
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": quality,
        }]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                if not info:
                    raise ValueError("yt-dlp returned no info for the selected audio format.")
                await loop.run_in_executor(None, lambda: ydl.download([url]))
            break
        except Exception as e:
            last_error = e
            logger.warning(
                "Audio attempt %s failed for %s with format '%s' (cookies=%s): %s",
                attempt_number,
                url,
                opts["format"],
                "cookiefile" in opts,
                e,
            )
    else:
        raise last_error or Exception("Audio download failed.")

    for file_name in os.listdir(DOWNLOAD_DIR):
        if file_name.startswith(filename):
            return os.path.join(DOWNLOAD_DIR, file_name)

    raise Exception("Audio download failed: File not found after download.")


async def _fetch_fallback_info(url: str, platform: str) -> Dict:
    """Manual scraping for basic OpenGraph meta tags when yt-dlp fails."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    raise ValueError(f"Site returned status {resp.status}")
                html = await resp.text()

                title_match = re.search(
                    r'<meta[^>]+(?:property|name)="(?:og:title|twitter:title)"[^>]+content="([^"]+)"',
                    html,
                ) or re.search(r"<title>([^<]+)</title>", html)
                img_match = re.search(
                    r'<meta[^>]+(?:property|name)="(?:og:image|twitter:image)"[^>]+content="([^"]+)"',
                    html,
                )
                uploader_match = re.search(
                    r'<meta[^>]+(?:property|name)="og:site_name"[^>]+content="([^"]+)"',
                    html,
                )

                title = title_match.group(1) if title_match else "Shared Media"
                image = img_match.group(1) if img_match else None
                uploader = uploader_match.group(1) if uploader_match else platform.title()

                if platform == "youtube":
                    media_types = ["video", "audio"]
                    available_qualities = ["360p", "720p"]
                else:
                    media_types = []
                    if image:
                        media_types.append("image")

                    if platform in ["tiktok", "instagram", "facebook", "telegram"] or "video" in html.lower():
                        media_types.insert(0, "video")

                    if not media_types:
                        media_types = ["video"]

                    available_qualities = ["best"]

                return {
                    "id": f"fallback_{int(asyncio.get_event_loop().time())}",
                    "title": title,
                    "thumbnail": image,
                    "url": url,
                    "platform": platform,
                    "uploader": uploader,
                    "duration": "N/A",
                    "duration_string": "N/A",
                    "view_count": None,
                    "is_youtube": platform == "youtube",
                    "media_types": media_types,
                    "available_qualities": available_qualities,
                }
    except Exception as e:
        logger.error("Fallback extraction failed: %s", e)
        raise ValueError(f"Could not extract info from this link: {str(e)[:50]}")


def cleanup_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        logger.error("Cleanup error: %s", e)


def cleanup_old_files(max_age_hours: int = 1):
    import time

    now = time.time()
    for file_name in os.listdir(DOWNLOAD_DIR):
        file_path = os.path.join(DOWNLOAD_DIR, file_name)
        if os.path.isfile(file_path):
            if os.stat(file_path).st_mtime < now - (max_age_hours * 3600):
                cleanup_file(file_path)
