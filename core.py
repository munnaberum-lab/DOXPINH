"""⚡ Dotxbrain Uptime Pro — core helpers & service layer (shared by bot and mini app)."""
import asyncio, contextlib, hashlib, hmac, html, ipaddress, json, logging, re, socket, time, uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlparse

import aiohttp

import info as cfg

log = logging.getLogger("dotxbrain")

# Sleeping Render sites wake up for a real browser visit, so the probe looks like one (same headers a phone browser sends).
UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Mobile Safari/537.36 DotxbrainUptimePro/3.0")
HEADERS = {"User-Agent": UA,
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9", "Cache-Control": "no-cache", "Pragma": "no-cache",
           "Upgrade-Insecure-Requests": "1"}
INTERVALS = [60, 120, 300, 600, 900]
MARKERS = ("waking up", "service waking", "spinning up", "application loading", "starting up",
           "incoming http request detected", "render - application")
WAKE_GAP = 4  # seconds between wake attempts

# ═════════════════════ ꜱᴍᴀʟʟ ᴄᴀᴘs + ʙʀᴀɴᴅɪɴɢ ═════════════════════
_SC = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"))
def sc(t): return "".join(_SC.get(c, c) for c in str(t).lower())
def esc(t): return html.escape(str(t))

BRAND_SC = sc(cfg.BRAND)

def foot(): return f"\n\n<i>🧠 {sc('powered by')} {BRAND_SC}</i>"
def branded(text): return text if BRAND_SC in text else text + foot()
def head(t): return f"╭━━━━━━━━━━━━━━━━━━╮\n  <b>{sc(t)}</b>\n╰━━━━━━━━━━━━━━━━━━╯\n\n"
def row(i, k, v): return f"{i} {sc(k)}  ➜  <b>{v}</b>\n"

# ═════════════════════ ꜰᴏʀᴍᴀᴛ ʜᴇʟᴘᴇʀs ═════════════════════
TZ = timezone(timedelta(hours=cfg.TZ_OFFSET_HOURS))

def clock(ts, fmt="%d %b · %I:%M %p"):
    return datetime.fromtimestamp(ts, TZ).strftime(fmt) if ts else "—"

def ago(ts):
    if not ts: return "never"
    d = max(0, int(time.time() - ts))
    if d < 60: return f"{d}s ago"
    if d < 3600: return f"{d // 60}m ago"
    if d < 86400: return f"{d // 3600}h ago"
    return f"{d // 86400}d ago"

def uptime(m): return round(m["ok"] / m["total"] * 100, 1) if m.get("total") else 0.0
def bar(p, n=10): k = round(max(0, min(1, p)) * n); return "▰" * k + "▱" * (n - k)

def dur(secs):
    """1h 5m · 3m 20s · 45s"""
    secs = max(0, int(secs))
    if secs < 60: return f"{secs}s"
    if secs < 3600: return f"{secs // 60}m {secs % 60}s" if secs % 60 else f"{secs // 60}m"
    if secs < 86400: return f"{secs // 3600}h {secs % 3600 // 60}m"
    return f"{secs // 86400}d {secs % 86400 // 3600}h"

def spark(vals):
    """Tiny response-time chart: ▁▂▃▅▇ (None = failed check → ✖)."""
    ok = [v for v in vals if v is not None]
    if not ok: return "—"
    lo, hi = min(ok), max(ok); blocks = "▁▂▃▄▅▆▇█"
    return "".join("✖" if v is None else blocks[0 if hi == lo else int((v - lo) / (hi - lo) * 7)] for v in vals)

def series(m, n=20):
    """Last n response times; None for non-up checks."""
    return [l["ms"] if l["s"] == "up" else None for l in m.get("logs", [])[-n:]]

def avg_ms(m):
    v = [l["ms"] for l in m.get("logs", []) if l["s"] == "up"]
    return round(sum(v) / len(v)) if v else 0

# ═════════════════════ ᴜʀʟ sᴀғᴇᴛʏ ═════════════════════
def is_public_ip(ip):
    try:
        a = ipaddress.ip_address(ip)
        if getattr(a, "ipv4_mapped", None): a = a.ipv4_mapped
        return a.is_global
    except ValueError:
        return False

def norm_url(u):
    """Return a safe http(s) URL or None."""
    if not isinstance(u, str): return None
    u = u.strip()
    if not u or len(u) > 2048 or re.search(r"\s", u): return None
    if not re.match(r"^https?://", u, re.I):
        if "://" in u: return None
        u = "https://" + u
    try:
        p = urlparse(u); host = (p.hostname or "").lower(); p.port
    except ValueError:
        return None
    if not host or host == "localhost" or host.endswith((".local", ".internal")): return None
    try:
        ipaddress.ip_address(host)           # literal IP → must be public
        if not is_public_ip(host): return None
    except ValueError:
        if "." not in host: return None
    return u

async def default_resolve(host):
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list({i[4][0] for i in infos})

# ═════════════════════ ᴍɪɴɪ ᴀᴘᴘ ᴀᴜᴛʜ ═════════════════════
def verify_init(init, token=None, max_age=86400):
    """Validate Telegram WebApp initData → user id or None."""
    try:
        d = dict(parse_qsl(init, keep_blank_values=True))
        h = d.pop("hash", "")
        if not h: return None
        chk = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
        secret = hmac.new(b"WebAppData", (token or cfg.BOT_TOKEN).encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(secret, chk.encode(), hashlib.sha256).hexdigest(), h): return None
        if time.time() - int(d.get("auth_date", 0)) > max_age: return None
        return int(json.loads(d["user"])["id"])
    except Exception:
        return None

# ═════════════════════ ᴍᴏɴɪᴛᴏʀ ᴍᴏᴅᴇʟ ═════════════════════
class UserError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg); self.status = status

def new_monitor(uid, url, temp=False):
    mid = uuid.uuid4().hex[:8]
    return {"_id": mid, "id": mid, "owner": int(uid), "url": url, "name": urlparse(url).netloc,
            "interval": cfg.DEFAULT_INTERVAL, "paused": False, "status": "new", "last_check": 0,
            "next_check": 0, "last_ms": 0, "last_code": 0, "total": 0, "ok": 0, "wakes": 0,
            "created": int(time.time()), "logs": [], "temp": temp,
            "muted": False, "down_since": 0, "last_outage": 0, "outages": 0}

def apply_result(m, kind, r):
    """Mutate the local monitor dict and return the matching DB delta."""
    now = int(time.time())
    entry = {"t": now, "k": kind, "s": r["state"], "c": r["code"], "ms": r["ms"], "n": r["note"]}
    inc = {"total": 1, "ok": 1 if r["state"] == "up" else 0,
           "wakes": 1 if kind == "wake" and r["state"] == "up" else 0}
    st = {"status": r["state"], "last_check": now, "next_check": now + m["interval"],
          "last_ms": r["ms"], "last_code": r["code"]}
    prev = m.get("status", "new")
    if r["state"] != "up" and prev == "up":                    # outage begins
        st["down_since"] = now; inc["outages"] = 1
    elif r["state"] == "up" and m.get("down_since"):           # outage ends → remember how long
        st["last_outage"] = now - m["down_since"]; st["down_since"] = 0
    for k, v in inc.items(): m[k] = m.get(k, 0) + v
    m.update(st)
    m["logs"] = (m.get("logs", []) + [entry])[-cfg.LOG_KEEP:]
    return {"set": st, "inc": inc, "log": entry}

# ═════════════════════ sᴇʀᴠɪᴄᴇ ʟᴀʏᴇʀ ═════════════════════
SETTING_DEFAULTS = {                       # read lazily so config / env changes always apply
    "maintenance": lambda: False,
    "signups": lambda: True,
    "auto_wake": lambda: cfg.AUTO_WAKE,
    "max_monitors": lambda: cfg.MAX_MONITORS_PER_USER,
}

class Service:
    def __init__(self, db, session):
        self.db, self.session, self.busy = db, session, set()
        self.resolve = default_resolve
        self.settings, self.banned, self.started = {}, set(), time.time()
        self.last_broadcast = None

    # ── live admin settings & bans (cached in memory, persisted in the DB) ──
    async def load_state(self):
        self.settings = await self.db.load_settings()
        self.banned = {u["_id"] for u in await self.db.list_users() if u.get("banned")}

    def setting(self, key):
        return self.settings[key] if key in self.settings else SETTING_DEFAULTS[key]()

    def is_admin(self, uid): return int(uid) in cfg.ADMIN_IDS

    async def register(self, uid, name):
        """Create / refresh the user. New users are refused when the admin closed registrations."""
        if await self.db.get_user(uid) is None and not self.setting("signups") and not self.is_admin(uid):
            raise UserError("new registrations are closed right now", 403)
        await self.db.upsert_user(uid, name)

    async def user_limit(self, uid):
        u = await self.db.get_user(uid) or {}
        return int(u.get("limit") or self.setting("max_monitors"))

    async def should_alert(self, m):
        if m.get("muted") or m["owner"] in self.banned: return False
        u = await self.db.get_user(m["owner"]) or {}
        return u.get("notify", True) is not False

    @contextlib.asynccontextmanager
    async def guard(self, m):
        if m["id"] in self.busy: raise UserError("already working on this monitor", 409)
        self.busy.add(m["id"])
        try: yield
        finally: self.busy.discard(m["id"])

    async def get(self, uid, mid):
        m = await self.db.get(uid, mid)
        if not m: raise UserError("not found", 404)
        return m

    async def probe(self, url, timeout=25):
        t0 = time.perf_counter()
        base = dict(code=0, ms=0, server="—", size="—", cold=False)
        host = urlparse(url).hostname or ""
        try:
            ips = await self.resolve(host)
        except OSError:
            return {**base, "state": "down", "note": "dns lookup failed"}
        if not ips or not all(is_public_ip(i) for i in ips):
            return {**base, "state": "down", "note": "blocked address", "fatal": True}
        try:
            # allow_redirects=False → a redirect can never lead us to an internal address (SSRF-safe).
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=timeout),
                                        headers=HEADERS, allow_redirects=False) as r:
                chunk = await r.content.read(4096)
                ms = int((time.perf_counter() - t0) * 1000)
                txt = chunk.decode("utf-8", "ignore").lower()
                base.update(code=r.status, ms=ms, server=r.headers.get("server", "—"),
                            size=r.headers.get("content-length", "—"))
                if any(k in txt for k in MARKERS) or r.status in (502, 503, 504):
                    return {**base, "state": "sleeping", "note": "wake-up page / 5xx"}
                if r.status >= 500:
                    return {**base, "state": "down", "note": f"server error {r.status}"}
                cold = ms > cfg.SLOW_MS
                return {**base, "state": "up", "cold": cold,
                        "note": "cold start (was sleeping)" if cold else "ok"}
        except asyncio.TimeoutError:
            return {**base, "ms": int((time.perf_counter() - t0) * 1000), "state": "sleeping",
                    "note": "no response (timeout)"}
        except (aiohttp.ClientError, ValueError, UnicodeError) as e:
            return {**base, "state": "down", "note": type(e).__name__}

    async def record(self, m, kind, r):
        delta = apply_result(m, kind, r)
        if not m.get("temp"):
            await self.db.apply(m["owner"], m["id"], delta)

    async def ping(self, m):
        r = await self.probe(m["url"])
        await self.record(m, "ping", r)
        return r

    async def wake(self, m, progress=None):
        t0, attempts = time.time(), 0
        while True:
            attempts += 1
            r = await self.probe(m["url"], 20)
            secs = int(time.time() - t0)
            if r["state"] == "up":
                woke = attempts > 1 or r["cold"]
                await self.record(m, "wake" if woke else "ping", r)
                return dict(ok=True, woke=woke, attempts=attempts, secs=secs, r=r)
            if progress:
                try: await progress(attempts, r, secs)
                except Exception: log.exception("progress callback failed")
            if r.get("fatal") or time.time() - t0 >= cfg.WAKE_TIMEOUT: break
            await asyncio.sleep(WAKE_GAP)
        await self.record(m, "wake", r)
        return dict(ok=False, woke=False, attempts=attempts, secs=int(time.time() - t0), r=r)

    async def add(self, uid, raw):
        url = norm_url(raw)
        if not url: raise UserError("invalid or blocked link")
        if await self.db.get_user(uid) is None: await self.register(uid, "user")
        limit = await self.user_limit(uid)
        if await self.db.count(uid) >= limit: raise UserError(f"limit reached ({limit} monitors)")
        if await self.db.exists(uid, url): raise UserError("already monitoring this link")
        m = new_monitor(uid, url)
        if not await self.db.insert(m): raise UserError("already monitoring this link")
        if await self.db.count(uid) > limit:           # lost a race against parallel adds
            await self.db.delete(uid, m["id"]); raise UserError(f"limit reached ({limit} monitors)")
        r = await self.ping(m)
        if r.get("fatal"):
            await self.db.delete(uid, m["id"]); raise UserError("this address is not allowed")
        return m, r

    async def toggle_pause(self, m):
        m["paused"] = not m["paused"]
        m["next_check"] = 0 if not m["paused"] else m["next_check"]
        await self.db.set_fields(m["owner"], m["id"], {"paused": m["paused"], "next_check": m["next_check"]})

    async def cycle_interval(self, m):
        opts = [i for i in INTERVALS if i >= cfg.MIN_INTERVAL]
        m["interval"] = opts[(opts.index(m["interval"]) + 1) % len(opts)] if m["interval"] in opts else opts[0]
        m["next_check"] = int(time.time()) + m["interval"]
        await self.db.set_fields(m["owner"], m["id"], {"interval": m["interval"], "next_check": m["next_check"]})

    async def set_interval(self, m, secs):
        opts = [i for i in INTERVALS if i >= cfg.MIN_INTERVAL]
        try: secs = int(secs)
        except (TypeError, ValueError): raise UserError("bad interval")
        if secs not in opts: raise UserError("choose one of: " + ", ".join(f"{i // 60} min" for i in opts))
        m["interval"], m["next_check"] = secs, int(time.time()) + secs
        await self.db.set_fields(m["owner"], m["id"], {"interval": secs, "next_check": m["next_check"]})

    async def rename(self, m, name):
        name = re.sub(r"[\x00-\x1f<>]", "", str(name or "")).strip()[:40]
        if not name: raise UserError("name cannot be empty")
        m["name"] = name
        await self.db.set_fields(m["owner"], m["id"], {"name": name})

    async def toggle_mute(self, m):
        m["muted"] = not m.get("muted")
        await self.db.set_fields(m["owner"], m["id"], {"muted": m["muted"]})

    async def check_all(self, uid):
        """Ping every monitor of this user at once → [(monitor, result)]."""
        ms = [m for m in await self.db.list(uid) if m["id"] not in self.busy]
        async def one(m):
            async with self.guard(m): return m, await self.ping(m)
        return await asyncio.gather(*(one(m) for m in ms))

    async def delete(self, m):
        if not await self.db.delete(m["owner"], m["id"]): raise UserError("not found", 404)
