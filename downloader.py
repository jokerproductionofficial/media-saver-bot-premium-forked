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


# Chrome version string kept in sync with latest stable for convincing UA
_CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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

    # Use Linux UA everywhere — Railway runs Linux, Windows UA triggers
    # Instagram's bot-detection fingerprint mismatch.
    opts["headers"] = {
        "User-Agent": _CHROME_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

    # ── Instagram: must send x-ig-app-id or the API returns 404 / rate-limit ──
    if platform == "instagram":
        opts["headers"].update({
            "x-ig-app-id": "936619743392459",
            "x-requested-with": "XMLHttpRequest",
            "Referer": "https://www.instagram.com/",
            "Origin": "https://www.instagram.com",
        })
        # Tell yt-dlp to use the mobile API endpoint which is less strict
        opts["extractor_args"] = {
            "instagram": {"api": ["graphql"]}
        }

    # ── Twitter/X: send a browser-like referer ──
    elif platform == "twitter":
        opts["headers"].update({
            "Referer": "https://twitter.com/",
            "Origin": "https://twitter.com",
        })

    # ── YouTube: skip dash/hls storyboards that cause format errors ──
    elif platform == "youtube":
        opts["extractor_args"] = {
            "youtube": {
                "skip": ["hls", "dash"],
                "player_client": ["android", "web"],
                "player_skip": ["webpage", "configs"],
            }
        }
        # Add a specific header that helps bypass some bot detection
        opts["headers"].update({
            "X-YouTube-Client-Name": "1",
            "X-YouTube-Client-Version": "2.20240320.00.00",
        })

    cookie_file = _get_cookie_file(platform)
    if cookie_file:
        opts["cookiefile"] = cookie_file

    return opts


def _extract_view_count(info_dict: Dict) -> Optional[int]:
    """
    Extract the best available view/play count from yt-dlp info dicts.
    Different platforms expose this under different field names:
      - YouTube/generic:   view_count
      - Instagram Reels:   play_count, video_view_count
      - Twitter/X:         view_count (sometimes missing → use like_count)
      - TikTok:            view_count or play_count
    Also checks nested entries[0] for playlist-wrapped responses.
    """
    # Some extractors (like Pinterest) use different field names for views
    _VIEW_FIELDS = [
        "view_count", "play_count", "video_view_count",
        "repost_count", "repin_count", "like_count",
        "comment_count", "follower_count"
    ]
    # Try top-level first
    for field in _VIEW_FIELDS:
        val = info_dict.get(field)
        if val is not None:
            return int(val)

    # Check nested entries
    entries = info_dict.get("entries") or []
    if entries:
        first = entries[0] if isinstance(entries, list) else None
        if isinstance(first, dict):
            for field in _VIEW_FIELDS:
                val = first.get(field)
                if val is not None:
                    return int(val)

    return None


async def _fetch_instagram_api_info(url: str) -> Optional[Dict]:
    """
    Fetch Instagram reel/post info using the public embed API — no login needed.
    Works from server IPs even when yt-dlp is blocked by rate-limiting.
    """
    # Extract shortcode from URL, e.g. /reel/ABC123/ or /p/ABC123/
    match = re.search(r"/(?:reel|p|tv)/([A-Za-z0-9_-]+)", url)
    if not match:
        return None
    shortcode = match.group(1)

    embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    media_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"

    headers = {
        "User-Agent": _CHROME_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
        "x-ig-app-id": "936619743392459",
    }

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as session:
            # Try embed page first (always public, no rate-limit)
            async with session.get(embed_url) as resp:
                html = await resp.text() if resp.status == 200 else ""

            if html:
                # Extract video URL from embed page
                video_match = re.search(r'"video_url":"([^"]+)"', html)
                thumb_match = re.search(r'"display_url":"([^"]+)"', html)
                owner_match = re.search(r'"username":"([^"]+)"', html)
                title_match = re.search(r'"accessibility_caption":"([^"]+)"', html)
                plays_match = re.search(r'"play_count":(\d+)', html)
                likes_match = re.search(r'"like_count":(\d+)', html)

                # Unescape unicode sequences
                def unescape(s: str) -> str:
                    return s.encode().decode("unicode_escape") if s else s

                video_url = unescape(video_match.group(1)) if video_match else None
                thumbnail = unescape(thumb_match.group(1)) if thumb_match else None
                uploader = owner_match.group(1) if owner_match else "Instagram User"
                title_raw = title_match.group(1) if title_match else f"Instagram Reel"
                title = title_raw[:80]
                view_count = int(plays_match.group(1)) if plays_match else (
                    int(likes_match.group(1)) if likes_match else None
                )

                if video_url:
                    logger.info("Instagram embed API succeeded for %s", shortcode)
                    return {
                        "id": shortcode,
                        "title": title,
                        "thumbnail": thumbnail,
                        "url": url,
                        "_direct_video_url": video_url,  # used by download to skip yt-dlp
                        "platform": "instagram",
                        "uploader": uploader,
                        "duration": "N/A",
                        "duration_string": "N/A",
                        "view_count": view_count,
                        "is_youtube": False,
                        "media_types": ["video"],
                        "available_qualities": ["best"],
                        "quality_candidates": {},
                    }
    except Exception as e:
        logger.warning("Instagram embed API failed for %s: %s", shortcode, e)

    return None


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
        # For Instagram, try the embed API before the generic HTML scraper
        if platform == "instagram":
            ig_info = await _fetch_instagram_api_info(url)
            if ig_info:
                return ig_info
        return await _fetch_fallback_info(url, platform)

    formats = info_dict.get("formats", [])
    duration_raw = info_dict.get("duration", 0)
    quality_candidates = (
        _build_quality_candidate_map(formats, duration=duration_raw)
        if platform == "youtube"
        else {}
    )
    available_qualities = list(quality_candidates) or _extract_available_resolutions(
        formats,
        duration=duration_raw,
    )

    if platform == "youtube":
        # Always merge with a set of standard qualities to ensure 4K/1080p appear 
        # even if cookies/IP restrict the initial metadata extraction.
        standard_list = ["4K", "1440p", "1080p", "720p", "480p", "360p", "240p"]
        existing = set(available_qualities)
        for q in standard_list:
            if q not in existing:
                available_qualities.append(q)
        
        # Re-sort available qualities
        available_qualities = sorted(
            list(set(available_qualities)), 
            key=lambda x: _quality_to_height(x) or 0, 
            reverse=True
        )

    title = info_dict.get("title") or info_dict.get("description") or "Unknown Title"
    if title == "Unknown Title" and platform == "pinterest":
        title = info_dict.get("description", "Pinterest Pin")

    uploader = (
        info_dict.get("uploader") or 
        info_dict.get("uploader_id") or 
        info_dict.get("channel") or 
        info_dict.get("channel_id") or
        info_dict.get("owner") or
        info_dict.get("creator") or
        info_dict.get("pinner") or
        info_dict.get("author") or
        info_dict.get("author_name") or
        "Unknown"
    )

    info = {
        "id": info_dict.get("id"),
        "title": title[:100],
        "thumbnail": info_dict.get("thumbnail"),
        "url": url,
        "platform": platform,
        "uploader": uploader,
        "duration": _format_duration(info_dict.get("duration", 0)),
        "duration_string": _format_duration(info_dict.get("duration", 0)),
        "view_count": _extract_view_count(info_dict),
        "is_youtube": platform == "youtube",
        "media_types": [],
        "available_qualities": available_qualities,
        "quality_candidates": quality_candidates,
    }

    if platform == "youtube":
        info["media_types"] = ["video", "audio"]
    else:
        is_video = False
        is_audio = False
        is_image = False

        if platform in ["tiktok", "instagram", "facebook", "telegram", "pinterest"]:
            is_video = True
        elif formats:
            is_video = any(
                f.get("vcodec") not in (None, "none") or 
                f.get("ext") in ["mp4", "m3u8", "ts"] or
                "video" in str(f.get("format_id", "")).lower()
                for f in formats
            )

        if info_dict.get("duration", 0) > 0:
            is_video = True

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

    # CRITICAL: Force to int to prevent Pyrogram "float' object has no attribute 'to_bytes'" error on servers
    info["duration_raw"] = int(float(duration_raw)) if duration_raw else 0
    info["width"] = int(float(info_dict.get("width") or 0))
    info["height"] = int(float(info_dict.get("height") or 0))

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


def _is_downloadable_video_format(fmt: Dict) -> bool:
    format_id = str(fmt.get("format_id") or "")
    if format_id.startswith("sb"):
        return False
    if fmt.get("ext") == "mhtml":
        return False
    
    # Check vcodec, ext, and common video indicators
    has_vcodec = fmt.get("vcodec") not in (None, "none")
    is_video_ext = fmt.get("ext") in ["mp4", "m3u8", "ts", "mov", "avi", "mkv"] # added common exts
    
    return has_vcodec or is_video_ext or "video" in format_id.lower()


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
        if fmt.get("height") and fmt.get("height") >= 144 and _is_downloadable_video_format(fmt)
    }
    if not heights:
        return []

    fallback = []
    for height in sorted(heights, reverse=True):
        label = _height_to_quality(height)
        if label not in fallback:
            fallback.append(label)
    return fallback


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
    direct_video_url: Optional[str] = None,
) -> Dict:
    filename = f"{user_id}_{quality}_{int(asyncio.get_event_loop().time())}"
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{filename}.%(ext)s")

    # ── Fast path: embed API gave us a direct CDN URL — skip yt-dlp entirely ──
    if direct_video_url:
        filepath = os.path.join(DOWNLOAD_DIR, f"{filename}.mp4")
        logger.info("Downloading via direct URL for %s", url)
        try:
            headers = {
                "User-Agent": _CHROME_UA,
                "Referer": "https://www.instagram.com/",
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(direct_video_url) as resp:
                    if resp.status != 200:
                        raise ValueError(f"Direct download returned status {resp.status}")
                    total = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk_size = 1024 * 256  # 256 KB
                    with open(filepath, "wb") as f:
                        async for chunk in resp.content.iter_chunked(chunk_size):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_hook and total:
                                progress_hook({
                                    "status": "downloading",
                                    "downloaded_bytes": downloaded,
                                    "total_bytes": total,
                                    "speed": 0,
                                })
            return {"filepath": filepath, "duration_raw": 0, "width": 0, "height": 0, "thumbnail": None}
        except Exception as e:
            logger.warning("Direct download failed, falling back to yt-dlp: %s", e)
            if os.path.exists(filepath):
                os.remove(filepath)

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

    if platform == "youtube" and quality != "best" and not format_candidates:
        # Don't hard-error — let the generic fallback candidates try
        logger.warning("YouTube: no exact format candidates found, using generic fallbacks.")

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
        "duration": int(float(info.get("duration") or 0)),
        "duration_raw": int(float(info.get("duration") or 0)),
        "width": int(float(info.get("width") or 0)),
        "height": int(float(info.get("height") or 0)),
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
