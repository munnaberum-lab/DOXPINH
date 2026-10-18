"""⚡ Dotxbrain Uptime Pro — /admin control panel inside Telegram (admins only, see ADMIN_IDS)."""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import bot as B
import templates as T
from admin import LIMITS, PER_PAGE, Admin
from core import UserError, esc, sc

log = logging.getLogger("dotxbrain.adminbot")
router = Router()
router.message.middleware(B.Safe())
router.callback_query.middleware(B.Safe())
btn, kb, edit, reply = B.btn, B.kb, B.edit, B.reply
BACK = lambda: [btn("⬅️ admin", "adm"), btn("🏠 home", "home")]


def A(): return Admin(B.S)

def guard(uid):
    if not B.S.is_admin(uid): raise UserError("admins only", 403)

async def dashboard():
    rows = [[btn("👥 users", "adm:u:0"), btn("📡 monitors", "adm:m:0")],
            [btn("⚙️ settings", "adm:set"), btn("📣 broadcast", "adm:bc")],
            [btn("🔎 find user", "adm:find"), btn("🔄 refresh", "adm")],
            [btn("🏠 home", "home")]]
    return T.admin_dashboard(await A().overview()), kb(rows)

@router.message(Command("admin"))
async def c_admin(m: Message):
    guard(m.from_user.id); text, markup = await dashboard(); await reply(m, text, markup)

@router.callback_query(F.data == "adm")
async def cb_adm(c: CallbackQuery):
    guard(c.from_user.id); B.PENDING.pop(c.from_user.id, None)
    text, markup = await dashboard(); await edit(c.message, text, markup); await c.answer()

def pager(prefix, page, total):
    nav = []
    if page > 0: nav.append(btn("◀️ prev", f"{prefix}:{page - 1}"))
    if (page + 1) * PER_PAGE < total: nav.append(btn("next ▶️", f"{prefix}:{page + 1}"))
    return nav

# ───────────── ᴜsᴇʀs ─────────────
@router.callback_query(F.data.startswith("adm:u:"))
async def cb_users(c: CallbackQuery):
    guard(c.from_user.id); page = int(c.data.split(":")[2])
    us, total = await A().users(page)
    rows = [[btn(("🚫 " if u.get("banned") else "👤 ") + f"{str(u.get('name', '?'))[:18]} · {u['monitors']}📡", f"adm:ud:{u['_id']}")] for u in us]
    nav = pager("adm:u", page, total)
    await edit(c.message, T.head("👥 users") + sc(f"{total} users · page {page + 1}"), kb(rows + ([nav] if nav else []) + [BACK()]))
    await c.answer()

async def show_user(msg, uid):
    u, ms, limit = await A().user(uid)
    banned = u.get("banned")
    rows = [[btn("✅ unban" if banned else "🚫 ban", f"adm:{'unban' if banned else 'ban'}:{uid}"), btn("📏 set limit", f"adm:lim:{uid}")],
            [btn("✉️ message", f"adm:msg:{uid}"), btn("🗑 delete monitors", f"adm:pg:{uid}")],
            [btn("⬅️ users", "adm:u:0"), btn("🛡 admin", "adm")]]
    await edit(msg, T.admin_user(u, ms, limit), kb(rows))

@router.callback_query(F.data.startswith("adm:ud:"))
async def cb_ud(c: CallbackQuery):
    guard(c.from_user.id); await show_user(c.message, int(c.data.split(":")[2])); await c.answer()

@router.callback_query(F.data.startswith("adm:ban:") | F.data.startswith("adm:unban:"))
async def cb_ban(c: CallbackQuery):
    guard(c.from_user.id); _, act, uid = c.data.split(":")
    await A().ban(int(uid), act == "ban"); await show_user(c.message, int(uid)); await c.answer("done")

@router.callback_query(F.data.startswith("adm:lim:"))
async def cb_lim(c: CallbackQuery):
    guard(c.from_user.id); uid = int(c.data.split(":")[2]); B.PENDING[c.from_user.id] = ("a_limit", uid)
    await edit(c.message, T.head("📏 monitor limit") + sc("send a number 1–100 (0 = use the default).") + f"\n\n<code>{uid}</code>",
               kb([[btn("✖️ cancel", f"adm:ud:{uid}")]])); await c.answer()

@router.callback_query(F.data.startswith("adm:msg:"))
async def cb_msg(c: CallbackQuery):
    guard(c.from_user.id); uid = int(c.data.split(":")[2]); B.PENDING[c.from_user.id] = ("a_msg", uid)
    await edit(c.message, T.head("✉️ message user") + sc("send the text to deliver.") + f"\n\n<code>{uid}</code>",
               kb([[btn("✖️ cancel", f"adm:ud:{uid}")]])); await c.answer()

@router.callback_query(F.data.startswith("adm:pg:"))
async def cb_pg(c: CallbackQuery):
    guard(c.from_user.id); uid = int(c.data.split(":")[2])
    await edit(c.message, "🗑 " + sc("delete ALL monitors of this user?") + f"\n\n<code>{uid}</code>",
               kb([[btn("✅ yes, delete", f"adm:pgok:{uid}"), btn("✖️ no", f"adm:ud:{uid}")]])); await c.answer()

@router.callback_query(F.data.startswith("adm:pgok:"))
async def cb_pgok(c: CallbackQuery):
    guard(c.from_user.id); uid = int(c.data.split(":")[2]); n = await A().purge(uid)
    await show_user(c.message, uid); await c.answer(f"{n} deleted")

@router.callback_query(F.data == "adm:find")
async def cb_find(c: CallbackQuery):
    guard(c.from_user.id); B.PENDING[c.from_user.id] = ("a_find",)
    await edit(c.message, T.head("🔎 find user") + sc("send a telegram user id."), kb([[btn("✖️ cancel", "adm")]])); await c.answer()

# ───────────── ᴍᴏɴɪᴛᴏʀs ─────────────
@router.callback_query(F.data.startswith("adm:m:"))
async def cb_mons(c: CallbackQuery):
    guard(c.from_user.id); page = int(c.data.split(":")[2])
    ms, total = await A().monitors(page)
    rows = [[btn(f"{T.ICON[m['status']]} {m['name'][:26]}", f"adm:md:{m['id']}")] for m in ms]
    nav = pager("adm:m", page, total)
    await edit(c.message, T.head("📡 all monitors") + sc(f"{total} monitors · broken first · page {page + 1}"),
               kb(rows + ([nav] if nav else []) + [BACK()])); await c.answer()

async def show_mon(msg, mid):
    m = await A().monitor(mid); i = m["id"]
    rows = [[btn("☀️ wake", f"adm:mw:{i}"), btn("🏓 ping", f"adm:mp:{i}")],
            [btn("▶️ resume" if m["paused"] else "⏸ pause", f"adm:mt:{i}"), btn("🗑 delete", f"adm:mx:{i}")],
            [btn("👤 owner", f"adm:ud:{m['owner']}"), btn("⬅️ list", "adm:m:0")]]
    await edit(msg, T.admin_monitor(m), kb(rows))

@router.callback_query(F.data.startswith("adm:md:"))
async def cb_md(c: CallbackQuery):
    guard(c.from_user.id); await show_mon(c.message, c.data.split(":")[2]); await c.answer()

@router.callback_query(F.data.startswith("adm:mp:") | F.data.startswith("adm:mw:") | F.data.startswith("adm:mt:"))
async def cb_mact(c: CallbackQuery):
    guard(c.from_user.id); _, act, mid = c.data.split(":")
    await c.answer("working…")
    await A().monitor_act(mid, {"mp": "ping", "mw": "wake", "mt": "pause"}[act]); await show_mon(c.message, mid)

@router.callback_query(F.data.startswith("adm:mx:"))
async def cb_mx(c: CallbackQuery):
    guard(c.from_user.id); mid = c.data.split(":")[2]
    await edit(c.message, "🗑 " + sc("delete this monitor?"), kb([[btn("✅ yes, delete", f"adm:mxok:{mid}"), btn("✖️ no", f"adm:md:{mid}")]]))
    await c.answer()

@router.callback_query(F.data.startswith("adm:mxok:"))
async def cb_mxok(c: CallbackQuery):
    guard(c.from_user.id); await A().monitor_act(c.data.split(":")[2], "delete")
    await c.answer("deleted"); ms, total = await A().monitors(0)
    rows = [[btn(f"{T.ICON[m['status']]} {m['name'][:26]}", f"adm:md:{m['id']}")] for m in ms]
    await edit(c.message, T.head("📡 all monitors") + sc(f"{total} monitors"), kb(rows + [BACK()]))

# ───────────── sᴇᴛᴛɪɴɢs ─────────────
async def settings_view(msg):
    s = A().settings()
    rows = [[btn(f"🛠 maintenance: {'on' if s['maintenance'] else 'off'}", "adm:tg:maintenance")],
            [btn(f"☀️ auto wake: {'on' if s['auto_wake'] else 'off'}", "adm:tg:auto_wake")],
            [btn(f"🆕 signups: {'on' if s['signups'] else 'off'}", "adm:tg:signups")],
            [btn(f"📏 monitor limit: {s['max_monitors']}", "adm:lm")], BACK()]
    await edit(msg, T.admin_settings(s), kb(rows))

@router.callback_query(F.data == "adm:set")
async def cb_set(c: CallbackQuery):
    guard(c.from_user.id); await settings_view(c.message); await c.answer()

@router.callback_query(F.data.startswith("adm:tg:"))
async def cb_tg(c: CallbackQuery):
    guard(c.from_user.id); key = c.data.split(":")[2]
    await A().set_setting(key, not A().settings().get(key, False)); await settings_view(c.message); await c.answer("saved")

@router.callback_query(F.data == "adm:lm")
async def cb_lm(c: CallbackQuery):
    guard(c.from_user.id); cur = A().settings()["max_monitors"]
    nxt = next((x for x in LIMITS if x > cur), LIMITS[0])
    await A().set_setting("max_monitors", nxt); await settings_view(c.message); await c.answer(f"limit {nxt}")

# ───────────── ʙʀᴏᴀᴅᴄᴀsᴛ ─────────────
@router.callback_query(F.data == "adm:bc")
async def cb_bc(c: CallbackQuery):
    guard(c.from_user.id); B.PENDING[c.from_user.id] = ("a_bcast",)
    await edit(c.message, T.head("📣 broadcast") + sc("send the message for all users (html allowed)."), kb([[btn("✖️ cancel", "adm")]]))
    await c.answer()

BCAST: dict = {}        # admin id -> text awaiting confirmation

@router.callback_query(F.data == "adm:bcok")
async def cb_bcok(c: CallbackQuery):
    guard(c.from_user.id); text = BCAST.pop(c.from_user.id, None)
    if not text: return await c.answer("nothing to send", show_alert=True)
    await c.answer("sending…"); await edit(c.message, "📣 " + sc("sending broadcast…"))
    res = await A().broadcast(B.BOT, text)
    await edit(c.message, T.head("📣 broadcast done") + T.row("✅", "delivered", res["sent"]) + T.row("❌", "failed", res["failed"]), kb([BACK()]))

# ───────────── ᴛᴇxᴛ ɪɴᴘᴜᴛs (called from bot.on_text) ─────────────
async def pending_text(m: Message, p):
    kind, text = p[0], m.text.strip()
    if kind == "a_bcast":
        BCAST[m.from_user.id] = text
        return await reply(m, T.head("📣 preview") + text + "\n\n" + sc("send to every user?"),
                           kb([[btn("✅ send now", "adm:bcok"), btn("✖️ cancel", "adm")]]))
    if kind == "a_find":
        if not text.lstrip("-").isdigit(): raise UserError("send a numeric user id")
        u, ms, limit = await A().user(int(text))
        return await reply(m, T.admin_user(u, ms, limit), kb([[btn("👤 manage", f"adm:ud:{text}"), btn("🛡 admin", "adm")]]))
    if kind == "a_limit":
        if not text.isdigit(): raise UserError("send a number")
        await A().set_limit(p[1], int(text)); return await reply(m, "✅ " + sc("limit saved"), kb([[btn("👤 user", f"adm:ud:{p[1]}")]]))
    if kind == "a_msg":
        await B.BOT.send_message(p[1], B.branded(text))
        return await reply(m, "✅ " + sc("message sent"), kb([[btn("👤 user", f"adm:ud:{p[1]}")]]))
