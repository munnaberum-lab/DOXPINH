"""
⚡ Dotxbrain Uptime Pro — credentials & settings.
Every secret is read from an ENVIRONMENT VARIABLE (set them in Render → Environment).
Never paste tokens or passwords into this file.
"""
import os


def _ids(raw):
    out = set()
    for p in str(raw or "").replace(";", ",").split(","):
        p = p.strip()
        if p.lstrip("-").isdigit(): out.add(int(p))
    return out


def _bool(name, default):
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


# ───────────── ᴄʀᴇᴅᴇɴᴛɪᴀʟs (env vars) ─────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8863952531:AAHmpmgvPgY21kmTrbUzHyO0rP1C-_0mV3s").strip()          # from @BotFather
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://Dotxbrain:01L3uvnMHkI1cJU6@cluster0.dda2uqz.mongodb.net/").strip()          # mongodb+srv://USER:PASS@cluster.../  (empty = temporary memory DB)
MONGO_DB = os.getenv("MONGO_DB", "dotxbrain_uptime")
ADMIN_IDS = _ids(os.getenv("ADMIN_IDS", "7832626481"))            # your Telegram user id(s), comma separated → unlocks /admin

# ───────────── ʙʀᴀɴᴅɪɴɢ ─────────────
BRAND = "Dotxbrain"
BRAND_LINK = os.getenv("BRAND_LINK", "https://t.me/dotxbrain_official")

# ───────────── ꜱᴇʀᴠᴇʀ ─────────────
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", os.getenv("BASE_URL", "")).rstrip("/")
PORT = int(os.getenv("PORT", "10000"))

# ───────────── ꜱᴇᴛᴛɪɴɢꜱ (defaults — admins can change the main ones live from /admin) ─────────────
MAX_MONITORS_PER_USER = int(os.getenv("MAX_MONITORS_PER_USER", "10"))
MIN_INTERVAL = 60          # seconds
DEFAULT_INTERVAL = 300     # 5 min (Render free sleeps after 15 min idle)
WAKE_TIMEOUT = 90          # max seconds to keep trying to wake a sleeping site
SLOW_MS = 8000             # an OK reply slower than this = the site was cold-starting
AUTO_WAKE = _bool("AUTO_WAKE", True)
LOG_KEEP = 50              # log entries stored per monitor
QUICK_COOLDOWN = 10        # seconds between /ping, /wake or "check all" per user
TZ_OFFSET_HOURS = float(os.getenv("TZ_OFFSET_HOURS", "5.5"))   # IST
