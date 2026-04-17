"""utils/progress.py — Live download progress updater."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from telegram import Message
from telegram.error import TelegramError

from utils.helpers import format_size, to_small_caps

logger = logging.getLogger(__name__)

# Minimum seconds between Telegram edits (avoid flood)
_EDIT_INTERVAL = 2.0


class ProgressTracker:
    """
    Wraps a Telegram message and updates it with live download progress.

    Usage:
        tracker = ProgressTracker(message, "Downloading video…")
        hook = tracker.get_hook()
        # Pass hook to yt-dlp progress_hooks
        await tracker.done("✅ Complete!")
    """

    def __init__(self, message: Message, header: str = "⬇️ Downloading…") -> None:
        self.message = message
        self.header = header
        self._last_edit = 0.0
        self._last_text = ""
        self._loop = asyncio.get_event_loop()

    # ── yt-dlp hook (called from thread) ─────────────────────────────────────

    def get_hook(self):
        def hook(d: dict) -> None:
            if d["status"] == "downloading":
                pct = d.get("_percent_str", "?%").strip()
                speed = d.get("_speed_str", "?/s").strip()
                eta = d.get("_eta_str", "?s").strip()
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)

                bar = self._make_bar(pct)
                text = (
                    f"<b>{to_small_caps(self.header)}</b>\n\n"
                    f"{bar} <b>{pct}</b>\n\n"
                    f"⚡ {to_small_caps('Speed')}: <code>{speed}</code>\n"
                    f"⏱ {to_small_caps('ETA')}: <code>{eta}</code>\n"
                    f"📦 {to_small_caps('Size')}: <code>{format_size(downloaded)}"
                    f"{' / ' + format_size(total) if total else ''}</code>"
                )
                self._schedule_edit(text)

        return hook

    # ── Public helpers ────────────────────────────────────────────────────────

    async def done(self, text: str) -> None:
        try:
            await self.message.edit_text(text, parse_mode="HTML")
        except TelegramError:
            pass

    async def error(self, text: str) -> None:
        try:
            await self.message.edit_text(f"❌ {text}", parse_mode="HTML")
        except TelegramError:
            pass

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_bar(pct_str: str) -> str:
        """Convert '42.5%' → a 10-block progress bar."""
        try:
            pct = float(pct_str.replace("%", ""))
        except ValueError:
            return "░" * 10
        filled = int(pct / 10)
        return "█" * filled + "░" * (10 - filled)

    def _schedule_edit(self, text: str) -> None:
        now = time.monotonic()
        if now - self._last_edit < _EDIT_INTERVAL:
            return
        if text == self._last_text:
            return
        self._last_edit = now
        self._last_text = text
        asyncio.run_coroutine_threadsafe(
            self._edit(text), self._loop
        )

    async def _edit(self, text: str) -> None:
        try:
            await self.message.edit_text(text, parse_mode="HTML")
        except TelegramError:
            pass
