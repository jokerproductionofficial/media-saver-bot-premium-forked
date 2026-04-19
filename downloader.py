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
        "ignoreconfig": True,
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
    info_dict = None
    last_error = None

    try:
        if platform == "youtube":
            info_dict = await _extract_youtube_info(url)
        else:
            info_dict = await _extract_raw_info(url, platform, process=False)
    except Exception as e:
        last_error = e

    if not info_dict:
        logger.warning("yt-dlp failed, trying fallback for %s: %s", url, last_error)
        return await _fetch_fallback_info(url, platform)

    formats = info_dict.get("formats", [])
    duration_raw = info_dict.get("duration", 0)
    quality_candidates = (
        _build_quality_candidate_map(formats, duration=duration_raw)
        if platform == "youtube"
        else {}
    )
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
        "available_qualities": list(quality_candidates)
        or _extract_available_resolutions(formats, duration=duration_raw),
        "quality_candidates": quality_candidates,
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

    info["duration_raw"] = duration_raw
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


def _get_filesize(fmt: Dict) -> int:
    return fmt.get("filesize") or fmt.get("filesize_approx") or 0


def _estimate_filesize(fmt: Dict, duration: Optional[float] = None) -> int:
    size = _get_filesize(fmt)
    if size:
        return size

    tbr = fmt.get("tbr")
    if not tbr or not duration:
        return 0

    try:
        return int((float(tbr) * 1000 / 8) * float(duration))
    except (TypeError, ValueError):
        return 0


def _quality_to_height(label: str) -> Optional[int]:
    if label == "best":
        return None
    if label == "4K":
        return 2160
    if label == "8K":
        return 4320
    if label.endswith("p"):
        try:
            return int(label[:-1])
        except ValueError:
            return None
    return None


def _height_to_quality(height: int) -> str:
    if height >= 2000:
        return "4K"
    if height >= 1400:
        return "1440p"
    return f"{height}p"


def _height_matches_quality(height: int, target_height: int) -> bool:
    if target_height == 2160:
        return height >= 2000
    if target_height == 1440:
        return 1400 <= height < 2000
    return abs(height - target_height) <= 20


def _is_audio_only(fmt: Dict) -> bool:
    return fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none")


def _is_video_only(fmt: Dict) -> bool:
    return fmt.get("vcodec") not in (None, "none") and fmt.get("acodec") in (None, "none")


def _is_muxed_video(fmt: Dict) -> bool:
    return fmt.get("vcodec") not in (None, "none") and fmt.get("acodec") not in (None, "none")


def _sort_audio_formats(formats: List[Dict], preferred_exts: Optional[List[str]] = None) -> List[Dict]:
    preferred_exts = preferred_exts or []

    def sort_key(fmt: Dict):
        ext = fmt.get("ext")
        if ext in preferred_exts:
            ext_rank = preferred_exts.index(ext)
        elif ext in {"m4a", "mp4"}:
            ext_rank = len(preferred_exts)
        elif ext == "webm":
            ext_rank = len(preferred_exts) + 1
        else:
            ext_rank = len(preferred_exts) + 2

        abr = -(fmt.get("abr") or 0)
        asr = -(fmt.get("asr") or 0)
        size = -(_get_filesize(fmt) or 0)
        return (ext_rank, abr, asr, size)

    return sorted(formats, key=sort_key)


def _sort_video_formats(formats: List[Dict]) -> List[Dict]:
    def sort_key(fmt: Dict):
        ext = fmt.get("ext")
        if ext == "mp4":
            ext_rank = 0
        elif ext == "webm":
            ext_rank = 1
        else:
            ext_rank = 2

        size = -(_get_filesize(fmt) or 0)
        fps = -(fmt.get("fps") or 0)
        height = -(fmt.get("height") or 0)
        return (ext_rank, fps, height, size)

    return sorted(formats, key=sort_key)


def _build_exact_video_format_candidates(
    formats: List[Dict],
    quality: str,
    *,
    allow_lower: bool,
    duration: Optional[float] = None,
) -> List[str]:
    target_height = _quality_to_height(quality)
    if target_height is None:
        return []

    size_limit = MAX_FILE_SIZE_MB * 1024 * 1024
    selectors: List[str] = []
    seen = set()

    audio_formats = [fmt for fmt in formats if _is_audio_only(fmt)]
    mp4_audio_formats = _sort_audio_formats(audio_formats, preferred_exts=["m4a", "mp4"])
    webm_audio_formats = _sort_audio_formats(audio_formats, preferred_exts=["webm"])

    exact_heights = sorted(
        {
            fmt.get("height")
            for fmt in formats
            if fmt.get("height") and fmt.get("height") <= target_height
        },
        reverse=True,
    )
    if not allow_lower:
        exact_heights = [
            height for height in exact_heights if _height_matches_quality(height, target_height)
        ]

    for height in exact_heights:
        height_formats = [fmt for fmt in formats if fmt.get("height") == height]
        video_only_formats = _sort_video_formats([fmt for fmt in height_formats if _is_video_only(fmt)])

        for video_fmt in video_only_formats:
            video_size = _estimate_filesize(video_fmt, duration)
            preferred_audio = mp4_audio_formats if video_fmt.get("ext") == "mp4" else webm_audio_formats
            if not preferred_audio:
                preferred_audio = _sort_audio_formats(audio_formats)

            selectors_added = 0
            for audio_fmt in preferred_audio:
                audio_size = _estimate_filesize(audio_fmt, duration)
                total_size = video_size + audio_size if video_size and audio_size else 0
                if total_size and total_size > size_limit:
                    continue

                selector = f"{video_fmt['format_id']}+{audio_fmt['format_id']}"
                if selector not in seen:
                    seen.add(selector)
                    selectors.append(selector)
                    selectors_added += 1

                # Some videos reject a specific companion audio track, so keep
                # a few alternates instead of betting everything on one pair.
                if selectors_added >= 3:
                    break

        muxed_formats = _sort_video_formats([fmt for fmt in height_formats if _is_muxed_video(fmt)])
        for muxed_fmt in muxed_formats:
            muxed_size = _estimate_filesize(muxed_fmt, duration)
            if muxed_size and muxed_size > size_limit:
                continue

            selector = str(muxed_fmt["format_id"])
            if selector not in seen:
                seen.add(selector)
                selectors.append(selector)

    return selectors


def _build_quality_candidate_map(
    formats: List[Dict],
    duration: Optional[float] = None,
) -> Dict[str, List[str]]:
    quality_map: Dict[str, List[str]] = {}
    heights = sorted(
        {fmt.get("height") for fmt in formats if fmt.get("height") and fmt.get("height") >= 144},
        reverse=True,
    )

    for height in heights:
        label = _height_to_quality(height)
        if label in quality_map:
            continue

        selectors = _build_exact_video_format_candidates(
            formats,
            label,
            allow_lower=False,
            duration=duration,
        )
        if selectors:
            quality_map[label] = selectors

    return quality_map


def _extract_available_resolutions(
    formats: List[Dict],
    duration: Optional[float] = None,
) -> List[str]:
    quality_map = _build_quality_candidate_map(formats, duration=duration)
    if quality_map:
        return list(quality_map)

    heights = {
        fmt.get("height")
        for fmt in formats
        if fmt.get("height") and fmt.get("height") >= 144
    }
    if not heights:
        return ["360p", "720p"]

    fallback = []
    for height in sorted(heights, reverse=True):
        label = _height_to_quality(height)
        if label not in fallback:
            fallback.append(label)
    return fallback or ["360p", "720p"]


def _score_youtube_formats(
    formats: List[Dict],
    duration: Optional[float] = None,
) -> tuple[int, int]:
    quality_map = _build_quality_candidate_map(formats, duration=duration)
    return (len(quality_map), len(formats))


def _build_video_format_candidates(quality: str) -> List[str]:
    if quality == "best":
        return [
            "bestvideo+bestaudio/best",
            "best[ext=mp4]/best",
            "best",
            "bv*+ba/b",
        ]

    if quality.endswith("p") or quality in ["4K", "8K"]:
        height = 2160 if quality == "4K" else 4320 if quality == "8K" else int(quality[:-1])
        candidates = [
            f"best[height<={height}][ext=mp4]/best[height<={height}]",
            f"bestvideo[height<={height}]+bestaudio/best[height<={height}]",
            f"bv*[height<={height}]+ba/b[height<={height}]",
        ]
        if height >= 360:
            candidates.append("18")
        return candidates

    return [
        "best[ext=mp4]/best",
        "best",
        "bestvideo+bestaudio/best",
        "bv*+ba/b",
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

    if platform == "youtube" and has_cookiefile:
        cookie_attempts = [True, False]
    else:
        cookie_attempts = [True, False] if has_cookiefile else [True]

    for keep_cookies in cookie_attempts:
        for format_selector in format_candidates:
            attempt_opts = get_ytdl_opts(platform)
            attempt_opts["ignoreerrors"] = False
            attempt_opts["format"] = format_selector
            if not keep_cookies:
                attempt_opts.pop("cookiefile", None)
            attempts.append(attempt_opts)

    return attempts


async def _extract_raw_info(
    url: str,
    platform: str,
    *,
    process: bool,
    prefer_cookies: Optional[bool] = None,
) -> Dict:
    loop = asyncio.get_running_loop()
    info_dict = None
    last_error = None
    cookie_file = _get_cookie_file(platform)

    if cookie_file:
        if prefer_cookies is True:
            extract_attempts = [True, False]
        elif prefer_cookies is False:
            extract_attempts = [False, True]
        else:
            extract_attempts = [True, False] if platform == "youtube" else [True, False]
    else:
        extract_attempts = [False]

    for use_cookies in extract_attempts:
        opts = get_ytdl_opts(platform)
        opts.pop("format", None)
        opts["ignoreerrors"] = False
        if not use_cookies:
            opts.pop("cookiefile", None)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = await loop.run_in_executor(
                    None,
                    lambda: ydl.extract_info(url, download=False, process=process),
                )
            if info_dict:
                return info_dict
        except Exception as e:
            last_error = e
            logger.warning(
                "Metadata attempt failed for %s (cookies=%s): %s",
                url,
                use_cookies,
                e,
            )

    if last_error:
        raise last_error
    raise ValueError("yt-dlp returned no metadata.")


async def _extract_youtube_info(url: str) -> Dict:
    return await _extract_raw_info(
        url,
        "youtube",
        process=False,
        prefer_cookies=True,
    )


async def download_media(
    url: str,
    platform: str,
    user_id: int,
    quality: str = "best",
    progress_hook: Callable = None,
    preferred_formats: Optional[List[str]] = None,
) -> Dict:
    filename = f"{user_id}_{quality}_{int(asyncio.get_event_loop().time())}"
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{filename}.%(ext)s")

    loop = asyncio.get_event_loop()
    info = None
    last_error = None
    format_candidates: List[str] = []

    try:
        if platform == "youtube":
            raw_info = await _extract_youtube_info(url)
        else:
            raw_info = await _extract_raw_info(url, platform, process=False)

        exact_candidates = _build_exact_video_format_candidates(
            raw_info.get("formats", []),
            quality,
            allow_lower=True,
            duration=raw_info.get("duration"),
        )
        format_candidates.extend(exact_candidates)
    except Exception as e:
        logger.warning("Could not pre-resolve formats for %s: %s", url, e)

    format_candidates.extend(preferred_formats or [])

    fallback_candidates = _build_video_format_candidates(quality)
    for candidate in fallback_candidates:
        if candidate not in format_candidates:
            format_candidates.append(candidate)

    for attempt_number, opts in enumerate(
        _iter_download_attempt_opts(platform, format_candidates),
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
