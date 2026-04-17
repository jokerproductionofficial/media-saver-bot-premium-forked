# 🚀 Complete Setup Guide — MediaSaverBot

---

## STEP 1 — Railway Environment Variables

In Railway → your project → **Variables tab**, add these:

| Variable            | Required | Example                  | Description                              |
|---------------------|----------|--------------------------|------------------------------------------|
| `BOT_TOKEN`         | ✅ YES   | `123456:ABCdef...`       | Get from @BotFather on Telegram          |
| `ADMIN_ID`          | ✅ YES   | `987654321`              | Your Telegram user ID (numbers only)     |
| `ADMIN_USERNAME`    | ✅ YES   | `YourUsername`           | Your Telegram @username WITHOUT the @    |
| `CHANNEL_USERNAME`  | ✅ YES   | `@YourChannel`           | Force join channel — include the @       |
| `CHANNEL_USERNAME_2`| ❌ No    | `@YourGroup`             | 2nd force join channel (optional)        |
| `BOT_NAME`          | ❌ No    | `My Downloader Bot`      | Bot display name shown in messages       |
| `DAILY_LIMIT`       | ❌ No    | `10`                     | Max downloads per user per day           |
| `RATE_LIMIT_SECONDS`| ❌ No    | `10`                     | Seconds user must wait between requests  |
| `MAX_FILE_SIZE_MB`  | ❌ No    | `50`                     | Max file size in MB (Telegram limit=50)  |
| `COOKIES_FILE`      | ❌ No    | `cookies.txt`            | Path to YouTube cookies file             |

---

## STEP 2 — Fix Force Join (Most Common Issue!)

Force join REQUIRES the bot to be an **ADMIN** of the channel.

1. Open your channel in Telegram
2. Go to **Manage Channel → Administrators**
3. Add your bot as administrator
4. Make sure it has **"Add Members"** permission (or just all permissions)
5. Set `CHANNEL_USERNAME=@YourChannel` in Railway

If force join still not working, check Railway logs for lines like:
```
Force join check FAILED for channel @YourChannel: ...
```
That error will tell you exactly what's wrong.

---

## STEP 3 — How Animated Emoji Work in Telegram Bots

**You do NOT need any special code for animated emoji!**

Telegram automatically animates these emoji in messages:
- 🔥 Fire — animates when sent
- ⚡ Lightning bolt — animates  
- 🌟 Star — animates
- 🚀 Rocket — animates
- ❤️ Heart — animates
- 🎉 Party popper — animates
- 💯 100 — animates
- 🏆 Trophy — animates

The bots you saw that had "animated emoji" were simply using these
standard Telegram emoji in their messages. That's it! Telegram
renders them animated automatically on iOS and Android.

This bot already uses them in all messages (🔥⚡🚀🎬📥✅ etc).

---

## STEP 4 — Platform Status After Fixes

| Platform   | Status  | Notes                                              |
|------------|---------|-----------------------------------------------------|
| YouTube    | ✅ Fixed | Uses iOS client — bypasses bot detection on servers |
| TikTok     | ✅ Fixed | Updated API + watermark-free format                |
| Instagram  | ✅ Works | Public posts/reels only (login needed for private) |
| Pinterest  | ✅ Fixed | Mobile UA + MP4 format selection fixed             |
| Facebook   | ✅ Added | Public videos only (some require cookies)          |
| X/Twitter  | ✅ Works | All public videos work                             |
| Telegram   | ✅ Works | Public channels only                               |

---

## STEP 5 — YouTube Still Failing?

YouTube sometimes blocks Railway/VPS server IPs.

**Option A — Wait**: The iOS client bypass works 90% of the time.
If blocked, just wait 5 minutes and try again.

**Option B — Add cookies** (permanent fix):
1. Install "Get cookies.txt LOCALLY" extension in Chrome
2. Go to youtube.com (while logged in to your Google account)
3. Click the extension → Export cookies for this site
4. Save as `cookies.txt`
5. In Railway: Settings → Files → Upload `cookies.txt`
6. Add variable: `COOKIES_FILE=cookies.txt`

---

## STEP 6 — Pinterest "Not Available in Your Region"

Pinterest geo-blocks some videos. This is a Pinterest restriction
and cannot always be bypassed. The bot now uses a mobile User-Agent
which fixes most cases. For truly geo-blocked content:
- The user needs to use a VPN on their end
- Or the content creator has region-restricted it permanently

---

## STEP 7 — How to Get Your Telegram User ID

1. Message @userinfobot on Telegram
2. It replies with your numeric ID
3. Put that as `ADMIN_ID` in Railway

---

## STEP 8 — Admin Panel (Mobile-Friendly)

Send `/admin` to your bot. You get a full button menu:
- 📊 Bot stats
- 👥 User count  
- 📢 Broadcast to all users (just type your message after clicking)
- 🚫 Ban a user (type their ID)
- ✅ Unban a user
- 🧹 Clean temp files
- ⚙️ View current settings
- 📋 Recent download logs

No commands to memorize — everything works through buttons.
