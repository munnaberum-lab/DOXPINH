"""
⚡ Dotxbrain Uptime Pro — credentials & settings.
Every secret is read from an ENVIRONMENT VARIABLE (set them in Render → Environment).
Never paste tokens or passwords into this file.
"""
import os


def _load_dotenv():
    """Reads KEY=VALUE lines from a local `.env` file (for running on your own PC).
    On Render the values come from Environment settings instead; real env vars are never overridden."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


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
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()          # from @BotFather
MONGO_URI = os.getenv("MONGO_URI", "").strip()          # mongodb+srv://USER:PASS@cluster.../  (empty = temporary memory DB)
MONGO_DB = os.getenv("MONGO_DB", "dotxbrain_uptime")
ADMIN_IDS = _ids(os.getenv("ADMIN_IDS", ""))            # your Telegram user id(s), comma separated → unlocks /admin

# ───────────── ɢɪᴛʜᴜʙ ᴡᴀᴋᴇ-ʜᴇʟᴘᴇʀ (optional) ─────────────
# Render cannot wake another Render site from inside its own network, so the bot asks GitHub Actions (outside Render) to do it.
GH_TOKEN = os.getenv("GH_TOKEN", "").strip()            # fine-grained token: this repo only → Actions: Read and write
GH_REPO = os.getenv("GH_REPO", "").strip()              # owner/repo, e.g. munnaberum-lab/DOXPINH
GH_BRANCH = os.getenv("GH_BRANCH", "main").strip()

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
WAKE_TIMEOUT = 150         # max seconds (Render cold starts can take 1–2 min) to keep trying to wake a sleeping site
SLOW_MS = 8000             # an OK reply slower than this = the site was cold-starting
AUTO_WAKE = _bool("AUTO_WAKE", True)
LOG_KEEP = 50              # log entries stored per monitor
QUICK_COOLDOWN = 10        # seconds between /ping, /wake or "check all" per user
TZ_OFFSET_HOURS = float(os.getenv("TZ_OFFSET_HOURS", "5.5"))   # IST
