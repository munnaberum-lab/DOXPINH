# ⚡ Dotxbrain Uptime Pro

Smart uptime monitor & Render wake-up bot for Telegram — with a Mini App dashboard and an admin control panel.
**Built by Dotxbrain.**

## Features
**For users**
- 🔍 Detects whether a site is **sleeping** (Render wake-up page, 5xx, timeout, cold start)
- ☀️ **Wake up** with live progress · 🏓 **Ping** with code, speed, server, size · 🔄 **Check all** in one tap
- 🤖 Background monitor (1–15 min) with **auto-wake** and instant alerts (includes how long the site was down)
- 📈 Uptime %, average response, latency chart, outage counter, smart logs
- ✏️ Rename · 🔕 mute per monitor · ⚙️ global alerts on/off · ⏱ pick any interval
- 🚀 Mini App: tabs (Monitors / Insights / Settings), search, filters, sparkline charts, detail sheet
- 🔒 Multi-user & private — every user sees only their own links (enforced in the database layer)

**For admins** (`ADMIN_IDS`) — `/admin` in the bot **and** an Admin tab in the Mini App
- 📊 Dashboard: users, monitors, status split, checks, wake-ups, server uptime
- 👥 Users: ban / unban, per-user monitor limit, message a user, delete their monitors, find by ID
- 📡 All monitors: ping, wake, pause, delete (broken ones listed first)
- ⚙️ Live controls: maintenance mode, auto-wake on/off, signups open/closed, default monitor limit
- 📣 Broadcast to every user

## Setup (Render)
1. @BotFather → create bot → copy the token.
2. MongoDB Atlas (free) → Database user + Network Access `0.0.0.0/0` → copy the connection string.
3. Render → your service → **Environment** → add:
   | Key | Value |
   |---|---|
   | `BOT_TOKEN` | token from BotFather |
   | `MONGO_URI` | Atlas connection string |
   | `ADMIN_IDS` | your Telegram numeric id (get it from @userinfobot) |
4. Deploy. Open the bot → `/start` (Mini App button appears automatically) → `/admin`.

> ⚠️ **Never write tokens or passwords inside the code.** `info.py` only reads environment variables.

## 😴 Keeping the bot itself awake (important on Render free)
The bot pings its own public URL every 4 min, which stops it from *falling* asleep. But a service that is **already
asleep cannot wake itself** — something outside must send a request (exactly like opening the link in a browser; Render
then boots it in ~30–60 s). Set up **one** of these (two is even safer):

1. **GitHub Actions** (free, included): push this repo to GitHub → Settings → Secrets → Actions → add `APP_URL` =
   `https://<your-service>.onrender.com`. The workflow `.github/workflows/keepalive.yml` pings every 5 min and waits
   up to ~2 min for the cold start. (GitHub pauses schedules after 60 days without repo activity.)
2. **UptimeRobot / cron-job.org** (free): HTTP monitor → `https://<your-service>.onrender.com/health` → every 5 min.
   Its timeout may expire during a cold start — that is fine, the request has already woken the service.

When the bot comes back after being unreachable for more than 5 minutes, it messages every admin
("bot was asleep · offline for 23m") so you can see whether your pinger works.

## Commands
`/start` `/list` `/stats` `/settings` `/help` `/ping url` `/wake url` · admins: `/admin`

## Run tests (no internet / packages needed)
    python3 tests/test_all.py

## Local run
    pip install -r requirements.txt
    BOT_TOKEN=... MONGO_URI=... ADMIN_IDS=... python main.py

© Dotxbrain
