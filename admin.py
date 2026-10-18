"""⚡ Dotxbrain Uptime Pro — admin logic shared by the bot (/admin) and the Mini App (Admin tab).
Only ids listed in ADMIN_IDS may use it; callers must check `svc.is_admin(uid)` first."""
import asyncio, logging, time

import info as cfg
from core import UserError, branded, esc, uptime

log = logging.getLogger("dotxbrain.admin")
PER_PAGE = 8
LIMITS = [3, 5, 10, 20, 50]
SETTING_KEYS = {"maintenance": bool, "auto_wake": bool, "signups": bool, "max_monitors": int}


class Admin:
    def __init__(self, svc): self.s = svc

    async def overview(self):
        s, users, mons = self.s, await self.s.db.list_users(), await self.s.db.all_monitors()
        c = lambda st: sum(1 for m in mons if m["status"] == st)
        return {"users": len(users), "banned": len(s.banned), "monitors": len(mons),
                "up": c("up"), "sleeping": c("sleeping"), "down": c("down"), "paused": sum(1 for m in mons if m["paused"]),
                "checks": sum(m.get("total", 0) for m in mons), "wakes": sum(m.get("wakes", 0) for m in mons),
                "avg_uptime": round(sum(uptime(m) for m in mons) / len(mons), 1) if mons else 0,
                "uptime_secs": int(time.time() - s.started), "db": s.db.name,
                "settings": self.settings(), "broadcast": s.last_broadcast}

    def settings(self): return {k: self.s.setting(k) for k in SETTING_KEYS}

    async def set_setting(self, key, value):
        kind = SETTING_KEYS.get(key)
        if not kind: raise UserError("unknown setting")
        if kind is bool:
            if not isinstance(value, bool): raise UserError("bad value")
        else:
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100: raise UserError("limit must be 1–100")
        self.s.settings[key] = value
        await self.s.db.save_setting(key, value)
        return self.settings()

    async def users(self, page=0):
        us = sorted(await self.s.db.list_users(), key=lambda u: u.get("seen", 0), reverse=True)
        counts = {}
        for m in await self.s.db.all_monitors(): counts[m["owner"]] = counts.get(m["owner"], 0) + 1
        page = max(0, int(page)); chunk = us[page * PER_PAGE:(page + 1) * PER_PAGE]
        return [{**u, "monitors": counts.get(u["_id"], 0)} for u in chunk], len(us)

    async def user(self, uid):
        u = await self.s.db.get_user(uid)
        if not u: raise UserError("user not found", 404)
        return u, await self.s.db.list(uid), await self.s.user_limit(uid)

    async def ban(self, uid, flag):
        uid = int(uid)
        if self.s.is_admin(uid): raise UserError("admins cannot be banned")
        await self.s.db.set_user(uid, {"banned": bool(flag)})
        (self.s.banned.add if flag else self.s.banned.discard)(uid)

    async def set_limit(self, uid, n):
        n = int(n)
        if not 0 <= n <= 100: raise UserError("limit must be 0–100 (0 = default)")
        await self.s.db.set_user(uid, {"limit": n})

    async def purge(self, uid): return await self.s.db.delete_user_monitors(uid)

    async def monitors(self, page=0, status=None):
        ms = sorted(await self.s.db.all_monitors(), key=lambda m: (m["status"] == "up", m["created"]))
        if status: ms = [m for m in ms if m["status"] == status]
        page = max(0, int(page)); return ms[page * PER_PAGE:(page + 1) * PER_PAGE], len(ms)

    async def monitor(self, mid):
        m = next((x for x in await self.s.db.all_monitors() if x["id"] == str(mid)), None)
        if not m: raise UserError("monitor not found", 404)
        return m

    async def monitor_act(self, mid, act):
        m = await self.monitor(mid); s = self.s; out = {}
        if act == "ping": out["result"] = await s.ping(m)
        elif act == "wake":
            async with s.guard(m): res = await s.wake(m)
            out["result"] = {**res["r"], "ok": res["ok"], "secs": res["secs"], "attempts": res["attempts"]}
        elif act == "pause": await s.toggle_pause(m)
        elif act == "delete": await s.delete(m); return None, {"deleted": True}
        else: raise UserError("bad request")
        return m, out

    async def broadcast(self, bot, text):
        text = str(text or "").strip()
        if not text or len(text) > 3500: raise UserError("message must be 1–3500 characters")
        ids = [u["_id"] for u in await self.s.db.list_users() if not u.get("banned")]
        sent = failed = 0
        for uid in ids:
            try: await bot.send_message(uid, branded(text)); sent += 1
            except Exception: failed += 1
            await asyncio.sleep(0.05)                      # stay under Telegram's ~30 msg/s limit
        self.s.last_broadcast = {"sent": sent, "failed": failed, "t": int(time.time())}
        log.info("broadcast done: %s sent, %s failed", sent, failed)
        return self.s.last_broadcast
