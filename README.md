# 🎬 YouTube Downloader Telegram Bot

A production-ready Telegram bot for downloading YouTube videos and audio with progress tracking, caching, user management, and admin controls.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🎬 Video Download | 144p, 360p, 720p, 1080p |
| 🎵 Audio Download | MP3 at 128kbps or 320kbps |
| ⚡ Progress Bar | Live speed, ETA, percentage |
| 💾 Cache System | Reuse Telegram file_ids |
| 🚦 Rate Limiting | Anti-spam per user |
| 📊 Daily Limits | Configurable download cap |
| 👑 Admin Panel | Stats, ban, broadcast, cleanup |
| 📢 Force Join | Channel membership check |
| 🧹 Auto Cleanup | Temp files deleted after send |

---

## 🗂 Project Structure

```
ytbot/
├── main.py              # Entry point
├── config.py            # All env variables
├── downloader.py        # yt-dlp download logic
├── database/
│   └── db.py            # SQLite layer
├── handlers/
│   ├── start.py         # /start, /help
│   ├── download.py      # Full download flow
│   └── admin.py         # Admin commands
├── utils/
│   ├── helpers.py       # Guards, formatting
│   └── progress.py      # Live progress tracker
├── requirements.txt
├── Procfile             # Railway/Render
└── .env.example
```

---

## ⚙️ Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | BotFather token |
| `ADMIN_ID` | ✅ | — | Your Telegram user ID |
| `CHANNEL_USERNAME` | ☑️ | — | Force-join channel (e.g. `@mychan`) |
| `DAILY_LIMIT` | ☑️ | 10 | Max downloads per user per day |
| `RATE_LIMIT_SECONDS` | ☑️ | 10 | Seconds between requests |
| `MAX_FILE_SIZE_MB` | ☑️ | 50 | Max file size (Telegram limit) |
| `CACHE_ENABLED` | ☑️ | true | Reuse file_ids for same videos |
| `CACHE_EXPIRY_HOURS` | ☑️ | 24 | Hours before cache expires |
| `DOWNLOAD_DIR` | ☑️ | downloads | Temp download folder |
| `DB_PATH` | ☑️ | database/bot.db | SQLite file location |

---

## 🚀 Local Setup

```bash
git clone <your-repo>
cd ytbot

# Install FFmpeg (required)
# Ubuntu/Debian:
sudo apt install ffmpeg
# macOS:
brew install ffmpeg

# Install Python deps
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your values

# Run
python main.py
```

---

## ☁️ Deploy on Railway

1. Push project to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Add environment variables in **Variables** tab
4. Add a **FFmpeg** buildpack:
   - Go to **Settings** → **Buildpacks** → Add: `https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git`
5. Railway uses the `Procfile` automatically → `worker: python main.py`

---

## ☁️ Deploy on Render

1. Push to GitHub
2. New **Background Worker** service
3. Build command: `pip install -r requirements.txt`
4. Start command: `python main.py`
5. Add environment variables
6. Add FFmpeg via render.yaml or shell:

```yaml
# render.yaml
services:
  - type: worker
    name: ytbot
    env: python
    buildCommand: "apt-get install -y ffmpeg && pip install -r requirements.txt"
    startCommand: "python main.py"
```

---

## 👑 Admin Commands

| Command | Description |
|---|---|
| `/stats` | Bot & download statistics |
| `/users` | Total user count |
| `/ban USER_ID` | Ban a user |
| `/unban USER_ID` | Unban a user |
| `/broadcast MSG` | Message all users |
| `/cleanup` | Delete temp download files |
| `/adminhelp` | Admin command list |

---

## 📋 User Commands

| Command | Description |
|---|---|
| `/start` | Start the bot |
| `/help` | Usage guide |
| Send YouTube link | Start download flow |
