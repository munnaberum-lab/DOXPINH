"""⚡ Dotxbrain Uptime Pro — Telegram bot handlers (users). Admin handlers live in admin_bot.py."""
import logging, re, time

from aiogram import BaseMiddleware, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

import info as cfg
import templates as T
from core import INTERVALS, UserError, branded, esc, new_monitor, norm_url, sc

log = logging.getLogger("dotxbrain.bot")
router = Router()
S = None            # Service  (set by setup)
BOT = None
WAITING: set = set()        # users who tapped "add monitor" and must send a link
PENDING: dict = {}          # uid -> ("rename", id) | ("a_bcast",) | ("a_find",) | ("a_limit", uid) | ("a_msg", uid)
LAST_QUICK: dict = {}
URL_RE = re.compile(r"^(https?://)?[\w.-]+\.[a-z]{2,}(:\d+)?(/\S*)?$", re.I)
ICON, LABEL = T.ICON, T.LABEL


def setup(service, bot):
    global S, BOT
    S, BOT = service, bot

# ═════════════════════ ᴍɪᴅᴅʟᴇᴡᴀʀᴇ: ʙᴀɴ · ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ · ғʀɪᴇɴᴅʟʏ ᴇʀʀᴏʀs ═════════════════════
class Safe(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            u = getattr(event, "from_user", None)
            if S and u and not S.is_admin(u.id):
                if u.id in S.banned: return await self.notify(event, "🚫 " + sc("you are banned from this bot."))
                if S.setting("maintenance"):
                    return await self.notify(event, "🛠 " + sc("maintenance in progress. please try again soon."))
            return await handler(event, data)
        except UserError as e:
            await self.notify(event, "⚠️ " + sc(str(e)))
        except Exception:
            log.exception("handler crashed")
            await self.notify(event, "⚠️ " + sc("something went wrong. please try again."))

    @staticmethod
    async def notify(event, text):
        try:
            if isinstance(event, CallbackQuery): await event.answer(text[:190], show_alert=True)
            else: await event.answer(branded(text))
        except Exception:
            log.warning("could not notify user")

router.message.middleware(Safe())
router.callback_query.middleware(Safe())

# ═════════════════════ ᴜɪ ʜᴇʟᴘᴇʀs ═════════════════════
def btn(text, data=None, url=None, web_app=None):
    return InlineKeyboardButton(text=sc(text), callback_data=data, url=url,
                                web_app=WebAppInfo(url=web_app) if web_app else None)

def kb(rows): return InlineKeyboardMarkup(inline_keyboard=rows)
def app_url(): return cfg.BASE_URL + "/app" if cfg.BASE_URL.startswith("https") else None

async def edit(msg, text, markup=None):
    try: await msg.edit_text(branded(text), reply_markup=markup)
    except TelegramBadRequest: pass            # "message is not modified" / message deleted

async def reply(m, text, markup=None):
    return await m.answer(branded(text), reply_markup=markup)

def kb_home():
    rows = [[btn("➕ add monitor", "add"), btn("📋 my monitors", "list")],
            [btn("📊 statistics", "stats"), btn("⚙️ settings", "set")],
            [btn("🔄 check all", "chk"), btn("❓ help", "help")]]
    if app_url(): rows.insert(0, [btn("🚀 open mini app", web_app=app_url())])
    if cfg.BRAND_LINK.startswith("https"): rows.append([btn(f"🧠 {cfg.BRAND}", url=cfg.BRAND_LINK)])
    return kb(rows)

def kb_card(m):
    i = m["id"]
    return kb([[btn("☀️ wake up", f"wake:{i}"), btn("🏓 ping now", f"ping:{i}")],
               [btn("📜 logs", f"logs:{i}"), btn("⏱ interval", f"int:{i}")],
               [btn("✏️ rename", f"ren:{i}"), btn("🔔 unmute" if m.get("muted") else "🔕 mute", f"mute:{i}")],
               [btn("▶️ resume" if m["paused"] else "⏸ pause", f"pause:{i}"), btn("🗑 delete", f"del:{i}")],
               [btn("⬅️ back", "list")]])

def kb_back(i): return kb([[btn("⬅️ monitor", f"m:{i}"), btn("🏠 home", "home")]])
KB_HOME_ONLY = lambda: kb([[btn("🏠 home", "home")]])
card, report = T.card, T.report

async def home_view(uid, name):
    return T.home(name, await S.db.list(uid)), kb_home()

# ═════════════════════ ʜᴀɴᴅʟᴇʀs ═════════════════════
@router.message(CommandStart())
async def start(m: Message):
    name = m.from_user.first_name or "friend"
    await S.register(m.from_user.id, name)
    PENDING.pop(m.from_user.id, None); WAITING.discard(m.from_user.id)
    text, markup = await home_view(m.from_user.id, name)
    await reply(m, text, markup)

@router.callback_query(F.data == "home")
async def cb_home(c: CallbackQuery):
    WAITING.discard(c.from_user.id); PENDING.pop(c.from_user.id, None)
    text, markup = await home_view(c.from_user.id, c.from_user.first_name or "friend")
    await edit(c.message, text, markup); await c.answer()

@router.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery):
    await edit(c.message, T.help_text(S.is_admin(c.from_user.id)), KB_HOME_ONLY()); await c.answer()

@router.message(Command("help"))
async def c_help(m: Message): await reply(m, T.help_text(S.is_admin(m.from_user.id)), KB_HOME_ONLY())

@router.callback_query(F.data == "add")
async def cb_add(c: CallbackQuery):
    WAITING.add(c.from_user.id)
    await edit(c.message, T.head("➕ add monitor") + sc("send the site link now.") +
               "\n\n<code>https://your-app.onrender.com</code>", kb([[btn("✖️ cancel", "home")]]))
    await c.answer()

@router.message(F.text & ~F.text.startswith("/"))
async def on_text(m: Message):
    uid, text = m.from_user.id, m.text.strip()
    p = PENDING.pop(uid, None)
    if p:
        if p[0] == "rename":
            mon = await S.get(uid, p[1]); await S.rename(mon, text)
            return await reply(m, card(mon, "✏️ " + sc("renamed")), kb_card(mon))
        if p[0].startswith("a_") and S.is_admin(uid):
            from admin_bot import pending_text
            return await pending_text(m, p)
    if not URL_RE.match(text):
        if uid in WAITING: raise UserError("that does not look like a valid link. try again.")
        return
    WAITING.discard(uid)
    if not norm_url(text): raise UserError("invalid or blocked link")
    msg = await reply(m, "🔍 " + sc("checking if your site is sleeping…"))
    try:
        mon, r = await S.add(uid, text)
    except UserError as e:
        return await edit(msg, "⚠️ " + sc(str(e)), KB_HOME_ONLY())
    banner = {"up": "✅ " + sc("monitor added · site is awake"),
              "sleeping": "😴 " + sc("monitor added · site is sleeping, tap wake up"),
              "down": "🔴 " + sc("monitor added · site is not responding")}[r["state"]]
    await edit(msg, card(mon, banner), kb_card(mon))

async def show_list(c: CallbackQuery):
    ms = await S.db.list(c.from_user.id)
    if not ms:
        await edit(c.message, T.head("📋 monitors") + sc("nothing here yet. add your first link!"),
                   kb([[btn("➕ add monitor", "add")], [btn("🏠 home", "home")]]))
    else:
        rows = [[btn(f"{ICON[x['status']]} {x['name'][:28]}" + (" 🔕" if x.get("muted") else ""), f"m:{x['id']}")] for x in ms]
        rows.append([btn("🔄 check all", "chk")]); rows.append([btn("➕ add", "add"), btn("🏠 home", "home")])
        await edit(c.message, T.head("📋 my monitors") + sc(f"{len(ms)} monitors · tap to manage"), kb(rows))

@router.callback_query(F.data == "list")
async def cb_list(c: CallbackQuery):
    await show_list(c); await c.answer()

@router.message(Command("list"))
async def c_list(m: Message):
    ms = await S.db.list(m.from_user.id)
    rows = [[btn(f"{ICON[x['status']]} {x['name'][:28]}", f"m:{x['id']}")] for x in ms] + [[btn("➕ add", "add")]]
    await reply(m, T.head("📋 my monitors") + (sc(f"{len(ms)} monitors · tap to manage") if ms else sc("nothing here yet.")), kb(rows))

@router.callback_query(F.data == "stats")
async def cb_stats(c: CallbackQuery):
    await edit(c.message, T.stats(await S.db.list(c.from_user.id)), KB_HOME_ONLY()); await c.answer()

@router.message(Command("stats"))
async def c_stats(m: Message): await reply(m, T.stats(await S.db.list(m.from_user.id)), KB_HOME_ONLY())

async def settings_view(uid):
    u = await S.db.get_user(uid) or {}
    on = u.get("notify", True) is not False
    text = T.user_settings(u, await S.db.count(uid), await S.user_limit(uid))
    return text, kb([[btn("🔕 turn alerts off" if on else "🔔 turn alerts on", "notif")], [btn("🏠 home", "home")]])

@router.callback_query(F.data == "set")
async def cb_set(c: CallbackQuery):
    text, markup = await settings_view(c.from_user.id); await edit(c.message, text, markup); await c.answer()

@router.message(Command("settings"))
async def c_set(m: Message):
    text, markup = await settings_view(m.from_user.id); await reply(m, text, markup)

@router.callback_query(F.data == "notif")
async def cb_notif(c: CallbackQuery):
    u = await S.db.get_user(c.from_user.id) or {}
    await S.db.set_user(c.from_user.id, {"notify": not (u.get("notify", True) is not False)})
    text, markup = await settings_view(c.from_user.id); await edit(c.message, text, markup); await c.answer("saved")

async def do_check_all(uid, msg, edit_it):
    if time.time() - LAST_QUICK.get(uid, 0) < cfg.QUICK_COOLDOWN:
        raise UserError(f"slow down — wait {cfg.QUICK_COOLDOWN}s between checks")
    LAST_QUICK[uid] = time.time()
    if not await S.db.count(uid): raise UserError("add a monitor first")
    await edit_it(msg, "🔍 " + sc("checking all your monitors…"))
    await edit_it(msg, T.checkall(await S.check_all(uid)), kb([[btn("📋 my monitors", "list"), btn("🏠 home", "home")]]))

@router.callback_query(F.data == "chk")
async def cb_chk(c: CallbackQuery):
    await c.answer(); await do_check_all(c.from_user.id, c.message, edit)

async def get_m(c: CallbackQuery):
    """Fetch a monitor that belongs to the person who tapped the button (else None)."""
    try: return await S.get(c.from_user.id, c.data.split(":", 1)[1])
    except UserError:
        await c.answer("⚠️ " + sc("not found"), show_alert=True); return None

@router.callback_query(F.data.startswith("m:"))
async def cb_m(c: CallbackQuery):
    m = await get_m(c)
    if m: await edit(c.message, card(m), kb_card(m)); await c.answer()

@router.callback_query(F.data.startswith("ping:"))
async def cb_ping(c: CallbackQuery):
    m = await get_m(c)
    if not m: return
    await c.answer()
    await edit(c.message, "🔍 " + sc("checking status…"))
    r = await S.ping(m)
    if r["state"] == "up":
        await edit(c.message, report("ping successful", "🏓", m, r, "\n✅ " + sc("site is awake and healthy.")), kb_back(m["id"]))
    else:
        await edit(c.message, report("site is not awake", "😴", m, r, "\n⚠️ " + sc("sleeping or down. wake it up now?")),
                   kb([[btn("☀️ wake up now", f"wake:{m['id']}")], [btn("⬅️ monitor", f"m:{m['id']}")]]))

@router.callback_query(F.data.startswith("wake:"))
async def cb_wake(c: CallbackQuery):
    m = await get_m(c)
    if not m: return
    if m["id"] in S.busy: return await c.answer(sc("already waking…"), show_alert=True)
    await c.answer()
    await edit(c.message, "🔍 " + sc("step 1 · checking if site is sleeping…"))

    async def progress(att, r, secs): await edit(c.message, T.waking(m, att, r, secs))
    async with S.guard(m):
        res = await S.wake(m, progress)
    r = res["r"]
    if res["ok"] and res["woke"]:
        extra = "\n" + T.row("⏱", "woke in", f"{res['secs']}s") + T.row("🔁", "attempts", res["attempts"]) + \
                "\n☀️ " + sc("site was sleeping. now it is awake!")
        t = report("wake-up successful", "☀️", m, r, extra)
    elif res["ok"]:
        t = report("already awake", "✅", m, r, "\n✅ " + sc("it was awake, so i sent a ping instead."))
    else:
        t = report("could not wake", "❌", m, r, "\n" + T.row("⏱", "tried for", f"{res['secs']}s") +
                   "\n🔴 " + sc("no answer yet.") + "\n" +
                   (T.gh_note() if res.get("gh") else T.phone_hint() if T.render_to_render(m["url"]) else
                    sc("some sites need 2–3 min — tap wake up again. if it keeps failing, check the render logs.")))
    await edit(c.message, t, kb_back(m["id"]))

@router.callback_query(F.data.startswith("logs:"))
async def cb_logs(c: CallbackQuery):
    m = await get_m(c)
    if m: await edit(c.message, T.logs(m), kb_back(m["id"])); await c.answer()

@router.callback_query(F.data.startswith("int:"))
async def cb_int(c: CallbackQuery):
    m = await get_m(c)
    if not m: return
    rows = [[btn(("✅ " if i == m["interval"] else "") + f"{i // 60} min", f"seti:{m['id']}:{i}") for i in INTERVALS if i >= cfg.MIN_INTERVAL]]
    await edit(c.message, T.head("⏱ interval") + sc("how often should i check this site?"), kb(rows + [[btn("⬅️ monitor", f"m:{m['id']}")]]))
    await c.answer()

@router.callback_query(F.data.startswith("seti:"))
async def cb_seti(c: CallbackQuery):
    try: _, mid, secs = c.data.split(":")
    except ValueError: return await c.answer()
    try: m = await S.get(c.from_user.id, mid)
    except UserError: return await c.answer("⚠️ " + sc("not found"), show_alert=True)
    await S.set_interval(m, secs)
    await edit(c.message, card(m), kb_card(m)); await c.answer(f"{m['interval'] // 60} min")

@router.callback_query(F.data.startswith("pause:"))
async def cb_pause(c: CallbackQuery):
    m = await get_m(c)
    if not m: return
    await S.toggle_pause(m)
    await edit(c.message, card(m), kb_card(m)); await c.answer("paused" if m["paused"] else "resumed")

@router.callback_query(F.data.startswith("mute:"))
async def cb_mute(c: CallbackQuery):
    m = await get_m(c)
    if not m: return
    await S.toggle_mute(m)
    await edit(c.message, card(m), kb_card(m)); await c.answer("alerts muted" if m["muted"] else "alerts on")

@router.callback_query(F.data.startswith("ren:"))
async def cb_ren(c: CallbackQuery):
    m = await get_m(c)
    if not m: return
    PENDING[c.from_user.id] = ("rename", m["id"])
    await edit(c.message, T.head("✏️ rename") + sc("send the new name (max 40 characters).") + f"\n\n<code>{esc(m['name'])}</code>",
               kb([[btn("✖️ cancel", f"m:{m['id']}")]]))
    await c.answer()

@router.callback_query(F.data.startswith("del:"))
async def cb_del(c: CallbackQuery):
    m = await get_m(c)
    if not m: return
    await edit(c.message, "🗑 " + sc("delete this monitor?") + f"\n\n<code>{esc(m['url'])}</code>",
               kb([[btn("✅ yes, delete", f"delok:{m['id']}"), btn("✖️ no", f"m:{m['id']}")]]))
    await c.answer()

@router.callback_query(F.data.startswith("delok:"))
async def cb_delok(c: CallbackQuery):
    m = await get_m(c)
    if not m: return
    await S.delete(m)
    await show_list(c); await c.answer("deleted")

async def quick(msg: Message, wake: bool):
    uid = msg.from_user.id
    if time.time() - LAST_QUICK.get(uid, 0) < cfg.QUICK_COOLDOWN:
        raise UserError(f"slow down — wait {cfg.QUICK_COOLDOWN}s between checks")
    parts = (msg.text or "").split(maxsplit=1)
    url = norm_url(parts[1]) if len(parts) > 1 else None
    if not url: raise UserError("usage: /ping https://site.com")
    LAST_QUICK[uid] = time.time()
    tmp = new_monitor(uid, url, temp=True)         # never stored
    s = await reply(msg, "🔍 " + sc("checking…"))
    if wake:
        res = await S.wake(tmp)
        await edit(s, report("wake result", "☀️" if res["ok"] else "❌", tmp, res["r"], "\n" + T.row("⏱", "took", f"{res['secs']}s")))
    else:
        r = await S.ping(tmp)
        await edit(s, report("ping result", "🏓", tmp, r))

@router.message(Command("ping"))
async def c_ping(m: Message): await quick(m, False)

@router.message(Command("wake"))
async def c_wake(m: Message): await quick(m, True)
