"""downloader.py — Media Downloader with Dynamic Resolutions."""

import os
import re
import logging
import asyncio
import aiohttp
import yt_dlp
from typing import Dict, List, Optional, Callable
from config import YT_COOKIES_FILE, COOKIES_FILE, DOWNLOAD_DIR, MAX_FILE_SIZE_MB

logger = logging.getLogger(__name__)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def detect_platform(url: str) -> Optional[str]:
    url = url.lower()
    if 'youtube.com' in url or 'youtu.be' in url: return 'youtube'
    if 'instagram.com' in url: return 'instagram'
    if 'tiktok.com' in url: return 'tiktok'
    if 'twitter.com' in url or 'x.com' in url: return 'twitter'
    if 'pinterest.com' in url or 'pin.it' in url: return 'pinterest'
    if 'facebook.com' in url or 'fb.watch' in url: return 'facebook'
    if 't.me' in url or 'telegram.me' in url: return 'telegram'
    return 'generic'

def _get_cookie_file(platform: str) -> Optional[str]:
    if platform == "youtube":
        return YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None
    return COOKIES_FILE if os.path.exists(COOKIES_FILE) else None

def get_ytdl_opts(platform: str = "generic") -> Dict:
    opts = {
        "format": "bestvideo+bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "nocheckcertificate": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        },
    }

    cookie_file = _get_cookie_file(platform)
    if cookie_file:
        opts["cookiefile"] = cookie_file

    if platform == "youtube":
        # Ensure robust format selection
        opts["format"] = "bestvideo+bestaudio/best"
        pass
        
    return opts

async def fetch_info(url: str) -> Dict:
    platform = detect_platform(url)
    opts = get_ytdl_opts(platform)
    
    # We use a separate instance for info extraction to be faster
    loop = asyncio.get_event_loop()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
    except Exception as e:
        logger.warning(f"yt-dlp failed, trying fallback for {url}: {e}")
        # Try fallback for Pinterest and other image-heavy sites
        return await _fetch_fallback_info(url, platform)

    if not info_dict:
        raise ValueError("Could not extract any info from this URL.")

    # Basic info
    info = {
        'id': info_dict.get('id'),
        'title': info_dict.get('title', 'Unknown Title'),
        'thumbnail': info_dict.get('thumbnail'),
        'url': url,
        'platform': platform,
        'uploader': info_dict.get('uploader', 'Unknown'),
        'duration': _format_duration(info_dict.get('duration', 0)),
        'view_count': info_dict.get('view_count'),
        'is_youtube': platform == 'youtube',
        'media_types': []
    }

    # Extract unique heights
    formats = info_dict.get('formats', [])
    info['available_qualities'] = _extract_available_resolutions(formats)
    
    # Determine media types logically
    is_video = False
    is_audio = False
    is_image = False

    # Check for video
    # 1. Has specific resolutions
    if info['available_qualities'] and info['available_qualities'] != ["360p", "720p"]:
        is_video = True
    # 2. Has formats with vcodec != 'none'
    elif any(f.get('vcodec') != 'none' for f in formats if f.get('vcodec')):
        is_video = True
    # 3. Known video-primary platform
    elif platform in ['youtube', 'tiktok', 'instagram', 'facebook', 'telegram']:
        is_video = True
    
    # Check for audio
    if any(f.get('acodec') != 'none' for f in formats if f.get('ext') in ['mp3', 'm4a', 'wav', 'ogg']):
        is_audio = True
    elif platform == 'youtube': # YouTube always has audio
        is_audio = True

    # Check for image
    if info_dict.get('ext') in ['jpg', 'jpeg', 'png', 'webp']:
        is_image = True
    elif not is_video and not is_audio and (info_dict.get('thumbnails') or platform == 'pinterest'):
        is_image = True

    # Assign final media types
    if is_video: info['media_types'].append('video')
    if is_audio: info['media_types'].append('audio')
    if is_image: info['media_types'].append('image')

    # Ensure at least one type
    if not info['media_types']:
        info['media_types'] = ['video']

    # Extract unique heights
    formats = info_dict.get('formats', [])
    info['available_qualities'] = _extract_available_resolutions(formats)
    
    # Extract metadata properties
    info['duration_raw'] = info_dict.get('duration', 0)
    info['width'] = info_dict.get('width')
    info['height'] = info_dict.get('height')
    
    return info

def _format_duration(seconds) -> str:
    if not seconds: return "N/A"
    try:
        seconds = int(float(seconds))
        mins, secs = divmod(seconds, 60)
        hours, mins = divmod(mins, 60)
        if hours: return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"
    except Exception:
        return "N/A"

def _extract_available_resolutions(formats: List[Dict]) -> List[str]:
    """Finds EVERY unique height in the metadata."""
    heights = set()
    for f in formats:
        h = f.get("height")
        vcodec = f.get("vcodec")
        # For YouTube and most sites, high quality are often DASH (vcodec != None)
        if h and h >= 144:
            if vcodec and vcodec.lower() != "none":
                heights.add(h)
            elif vcodec is None and f.get("acodec") == "none":
                # DASH video-only
                heights.add(h)
            elif f.get('ext') == 'mp4' and not vcodec:
                # Fallback for some formats
                heights.add(h)

    if not heights:
        return ["360p", "720p"]

    # Sort descending
    sorted_heights = sorted(list(heights), reverse=True)
    available = []
    for h in sorted_heights:
        if h >= 2160: label = "4K"
        elif h >= 1440: label = "1440p"
        else: label = f"{h}p"
        if label not in available:
            available.append(label)

    return available

async def download_media(url: str, platform: str, user_id: int, quality: str = "best", progress_hook: Callable = None) -> str:
    opts = get_ytdl_opts(platform)
    
    # Correct format string based on quality
    if quality == "best":
        opts["format"] = "bestvideo+bestaudio/best"
    elif quality.endswith("p") or quality in ["4K", "8K"]:
        h = 2160 if quality == "4K" else 4320 if quality == "8K" else int(quality[:-1])
        # Find best video with this height + best audio, with fallbacks to avoid errors
        opts["format"] = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
    
    filename = f"{user_id}_{quality}_{int(asyncio.get_event_loop().time())}"
    filepath = os.path.join(DOWNLOAD_DIR, f"{filename}.%(ext)s")
    opts["outtmpl"] = filepath
    
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    # Ensure MP4 output for best compatibility
    opts["merge_output_format"] = "mp4"
    
    # Passing faststart to ffmpeg for streamability
    opts["postprocessor_args"] = {
        "ffmpeg": ["-movflags", "+faststart"]
    }

    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(opts) as ydl:
        # Check size before downloading if possible
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
        filesize = info.get('filesize') or info.get('filesize_approx')
        if filesize and filesize > MAX_FILE_SIZE_MB * 1024 * 1024:
            raise ValueError(f"⚠️ File too large: {filesize/(1024*1024):.1f}MB (Max: {MAX_FILE_SIZE_MB}MB)")

        await loop.run_in_executor(None, lambda: ydl.download([url]))

    # Find the actual file (yt-dlp adds extension)
    filepath = None
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(filename):
            filepath = os.path.join(DOWNLOAD_DIR, f)
            break
    
    if not filepath:
        raise Exception("Download failed: File not found after download.")

    return {
        'filepath': filepath,
        'duration': info.get('duration', 0),
        'width': info.get('width'),
        'height': info.get('height'),
        'thumbnail': info.get('thumbnail')
    }

async def download_audio(url: str, quality: str, user_id: int, progress_hook: Callable = None) -> str:
    platform = detect_platform(url)
    opts = get_ytdl_opts(platform)
    opts.update({
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": quality,
        }],
    })
    
    filename = f"{user_id}_audio_{int(asyncio.get_event_loop().time())}"
    filepath = os.path.join(DOWNLOAD_DIR, f"{filename}.%(ext)s")
    opts["outtmpl"] = filepath

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(opts) as ydl:
        await loop.run_in_executor(None, lambda: ydl.download([url]))

    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(filename):
            return os.path.join(DOWNLOAD_DIR, f)
    
    raise Exception("Audio download failed.")

async def _fetch_fallback_info(url: str, platform: str) -> Dict:
    """Manual scraping for basic OpenGraph meta tags when yt-dlp fails."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    raise ValueError(f"Site returned status {resp.status}")
                html = await resp.text()

                # Basic regex for OG tags
                title_match = re.search(r'<meta[^>]+(?:property|name)="(?:og:title|twitter:title)"[^>]+content="([^"]+)"', html) or \
                              re.search(r'<title>([^<]+)</title>', html)
                img_match = re.search(r'<meta[^>]+(?:property|name)="(?:og:image|twitter:image)"[^>]+content="([^"]+)"', html)
                uploader_match = re.search(r'<meta[^>]+(?:property|name)="og:site_name"[^>]+content="([^"]+)"', html)

                title = title_match.group(1) if title_match else "Shared Media"
                image = img_match.group(1) if img_match else None
                uploader = uploader_match.group(1) if uploader_match else platform.title()

                if not image and platform == 'pinterest':
                    # Sometimes Pinterest has images in a different script tag or meta
                    pass 

                # Improved detection for fallback
                media_types = []
                if image: media_types.append('image')
                
                # If it's a known video site, always allow video
                if platform in ['youtube', 'tiktok', 'instagram', 'facebook', 'telegram'] or 'video' in html.lower():
                    media_types.insert(0, 'video')
                
                if not media_types: media_types = ['video']

                return {
                    'id': f"fallback_{int(asyncio.get_event_loop().time())}",
                    'title': title,
                    'thumbnail': image,
                    'url': url,
                    'platform': platform,
                    'uploader': uploader,
                    'duration': "N/A",
                    'view_count': None,
                    'is_youtube': False,
                    'media_types': media_types,
                    'available_qualities': ["best"]
                }
    except Exception as e:
        logger.error(f"Fallback extraction failed: {e}")
        raise ValueError(f"Could not extract info from this link: {str(e)[:50]}")


def cleanup_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

def cleanup_old_files(max_age_hours: int = 1):
    import time
    now = time.time()
    for f in os.listdir(DOWNLOAD_DIR):
        fpath = os.path.join(DOWNLOAD_DIR, f)
        if os.path.isfile(fpath):
            if os.stat(fpath).st_mtime < now - (max_age_hours * 3600):
                cleanup_file(fpath)
