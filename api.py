"""⚡ Dotxbrain Uptime Pro — Mini App API.
Every route identifies the user from Telegram's signed initData; each user only ever
sees and controls their own monitors.
"""
import logging
from pathlib import Path

from aiohttp import web

import asyncio

from admin import Admin
from core import UserError, avg_ms, branded, series, uptime, verify_init

log = logging.getLogger("dotxbrain.api")
ACTIONS = {"ping", "wake", "pause", "interval", "delete", "rename", "mute"}
WEBAPP = Path(__file__).parent / "webapp" / "index.html"


def pub(m):
    """Public view of a monitor (never exposes the owner id)."""
    keys = ("id", "name", "url", "status", "last_ms", "last_code", "total", "wakes",
            "interval", "paused", "last_check")
    return {k: m[k] for k in keys} | {
        "uptime": uptime(m), "avg_ms": avg_ms(m), "spark": series(m, 30), "muted": bool(m.get("muted")),
        "outages": m.get("outages", 0), "last_outage": m.get("last_outage", 0), "down_since": m.get("down_since", 0),
        "created": m.get("created", 0)}

def auth(req):
    uid = verify_init(req.headers.get("X-Init-Data", ""))
    if uid is None: raise web.HTTPUnauthorized(text="open this inside telegram")
    svc = req.app["svc"]
    if uid in svc.banned: raise UserError("you are banned from this service", 403)
    if svc.setting("maintenance") and not svc.is_admin(uid): raise UserError("maintenance in progress, try again soon", 503)
    return uid

def admin_auth(req):
    uid = auth(req)
    if not req.app["svc"].is_admin(uid): raise UserError("admins only", 403)
    return uid

def upub(u, n=None):
    return {"id": u["_id"], "name": u.get("name", "—"), "banned": bool(u.get("banned")), "seen": u.get("seen", 0),
            "joined": u.get("joined", 0), "limit": u.get("limit", 0), "monitors": n if n is not None else u.get("monitors", 0)}

async def read_json(req):
    try: b = await req.json()
    except Exception: raise UserError("bad request")
    if not isinstance(b, dict): raise UserError("bad request")
    return b

@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except UserError as e:
        return web.json_response({"error": str(e)}, status=e.status)
    except Exception:
        log.exception("api error")
        return web.json_response({"error": "server error, try again"}, status=500)

async def api_list(req):
    uid = auth(req)
    return web.json_response([pub(m) for m in await req.app["svc"].db.list(uid)])

async def api_add(req):
    uid = auth(req); b = await read_json(req)
    m, _ = await req.app["svc"].add(uid, b.get("url"))
    return web.json_response(pub(m))

async def api_act(req):
    uid = auth(req); svc = req.app["svc"]; b = await read_json(req)
    mid, act = b.get("id"), b.get("act")
    if not isinstance(mid, str) or act not in ACTIONS: raise UserError("bad request")
    m = await svc.get(uid, mid)
    out = {}
    if act == "ping":
        out["result"] = await svc.ping(m)
    elif act == "wake":
        async with svc.guard(m):
            res = await svc.wake(m)
        out["result"] = {**res["r"], "ok": res["ok"], "woke": res["woke"],
                         "secs": res["secs"], "attempts": res["attempts"]}
    elif act == "pause": await svc.toggle_pause(m)
    elif act == "interval":
        if "value" in b: await svc.set_interval(m, b["value"])
        else: await svc.cycle_interval(m)
    elif act == "rename": await svc.rename(m, b.get("value"))
    elif act == "mute": await svc.toggle_mute(m)
    elif act == "delete":
        await svc.delete(m); return web.json_response({"deleted": True})
    return web.json_response({"monitor": pub(m), **out})

async def api_logs(req):
    uid = auth(req)
    m = await req.app["svc"].get(uid, req.query.get("id", ""))
    return web.json_response(list(reversed(m["logs"][-40:])))

async def api_me(req):
    uid = auth(req); svc = req.app["svc"]
    await svc.register(uid, "user") if await svc.db.get_user(uid) is None else None
    u = await svc.db.get_user(uid) or {}
    return web.json_response({"id": uid, "admin": svc.is_admin(uid), "notify": u.get("notify", True) is not False,
                              "limit": await svc.user_limit(uid), "interval_opts": [60, 120, 300, 600, 900]})

async def api_prefs(req):
    uid = auth(req); b = await read_json(req)
    if not isinstance(b.get("notify"), bool): raise UserError("bad request")
    await req.app["svc"].db.set_user(uid, {"notify": b["notify"]})
    return web.json_response({"notify": b["notify"]})

async def api_checkall(req):
    uid = auth(req); svc = req.app["svc"]
    pairs = await svc.check_all(uid)
    return web.json_response({"monitors": [pub(m) for m, _ in pairs], "up": sum(1 for _, r in pairs if r["state"] == "up")})

# ───────────── admin (every route re-checks ADMIN_IDS on the server) ─────────────
async def adm_overview(req):
    admin_auth(req); return web.json_response(await Admin(req.app["svc"]).overview())

async def adm_users(req):
    admin_auth(req); us, total = await Admin(req.app["svc"]).users(int(req.query.get("page", 0) or 0))
    return web.json_response({"total": total, "users": [upub(u) for u in us]})

async def adm_user(req):
    admin_auth(req); a = Admin(req.app["svc"]); b = await read_json(req)
    uid, act = b.get("uid"), b.get("act")
    if not isinstance(uid, int) or isinstance(uid, bool): raise UserError("bad request")
    if act == "ban": await a.ban(uid, True)
    elif act == "unban": await a.ban(uid, False)
    elif act == "limit": await a.set_limit(uid, b.get("value"))
    elif act == "purge": await a.purge(uid)
    elif act == "message":
        await req.app["bot"].send_message(uid, branded(str(b.get("value", ""))[:3500]))
    else: raise UserError("bad request")
    u, ms, _ = await a.user(uid)
    return web.json_response(upub(u, len(ms)))

async def adm_monitors(req):
    admin_auth(req); st = req.query.get("status") or None
    ms, total = await Admin(req.app["svc"]).monitors(int(req.query.get("page", 0) or 0), st)
    return web.json_response({"total": total, "monitors": [pub(m) | {"owner": m["owner"]} for m in ms]})

async def adm_monitor(req):
    admin_auth(req); b = await read_json(req)
    m, out = await Admin(req.app["svc"]).monitor_act(str(b.get("id", "")), b.get("act"))
    return web.json_response(out if m is None else {"monitor": pub(m) | {"owner": m["owner"]}, **out})

async def adm_settings(req):
    admin_auth(req); return web.json_response(Admin(req.app["svc"]).settings())

async def adm_settings_set(req):
    admin_auth(req); b = await read_json(req)
    return web.json_response(await Admin(req.app["svc"]).set_setting(b.get("key"), b.get("value")))

async def adm_broadcast(req):
    admin_auth(req); b = await read_json(req); text = str(b.get("text", "")).strip()
    if not text or len(text) > 3500: raise UserError("message must be 1–3500 characters")
    bot = req.app["bot"]
    if bot is None: raise UserError("bot not available", 503)
    t = asyncio.create_task(Admin(req.app["svc"]).broadcast(bot, text))
    req.app["tasks"].add(t); t.add_done_callback(req.app["tasks"].discard)
    return web.json_response({"started": True})

async def page_app(_): return web.FileResponse(WEBAPP, headers={"Cache-Control": "no-cache"})
async def health(_): return web.Response(text="ok · dotxbrain uptime pro")

def build_app(svc, bot=None):
    app = web.Application(middlewares=[errors], client_max_size=8192)
    app["svc"], app["bot"], app["tasks"] = svc, bot, set()
    app.add_routes([web.get("/", health), web.get("/health", health), web.get("/app", page_app),
                    web.get("/api/list", api_list), web.post("/api/add", api_add),
                    web.post("/api/act", api_act), web.get("/api/logs", api_logs),
                    web.get("/api/me", api_me), web.post("/api/prefs", api_prefs), web.post("/api/checkall", api_checkall),
                    web.get("/api/admin/overview", adm_overview), web.get("/api/admin/users", adm_users),
                    web.post("/api/admin/user", adm_user), web.get("/api/admin/monitors", adm_monitors),
                    web.post("/api/admin/monitor", adm_monitor), web.get("/api/admin/settings", adm_settings),
                    web.post("/api/admin/settings", adm_settings_set), web.post("/api/admin/broadcast", adm_broadcast)])
    return app
