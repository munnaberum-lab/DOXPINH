"""⚡ Dotxbrain Uptime Pro — every Telegram message template lives here (HTML parse mode)."""
import time
from urllib.parse import urlparse

import info as cfg
from core import (ago, avg_ms, bar, clock, dur, esc, head, render_to_render, row, sc, series, spark, uptime)

ICON = {"up": "🟢", "sleeping": "😴", "down": "🔴", "new": "⚪"}
LABEL = {"up": "online", "sleeping": "sleeping", "down": "offline", "new": "pending"}
KIND = {"ping": "🏓", "wake": "☀️", "auto": "🤖"}
LINE = "┈" * 16


def phone_hint():
    return ("🛰 " + sc("this bot runs on render, and render cannot wake another render site from inside its own network "
                       "(it gets an instant 502). open the mini app and tap wake up — it wakes the site from your phone — "
                       "or set GH_TOKEN + GH_REPO so github wakes it automatically (see readme).") + "\n")


def gh_note():
    return "🛰 " + sc("wake request sent through github (outside render). give it 1–3 minutes, then tap wake up again.") + "\n"


def grade(p):
    """Uptime → friendly rating."""
    return "🏆 excellent" if p >= 99 else "👍 good" if p >= 95 else "⚠️ unstable" if p >= 80 else "🔥 poor"


# ═════════════════════ ᴜsᴇʀ ═════════════════════
def home(name, ms=()):
    t = head("⚡ uptime pro") + f"ʜᴇʏ <b>{esc(name)}</b> 👋\n\n"
    if ms:
        c = lambda s: sum(1 for x in ms if x["status"] == s)
        t += (f"📡 {sc('your fleet')}  ➜  <b>{len(ms)}</b>\n🟢 {c('up')}   😴 {c('sleeping')}   🔴 {c('down')}\n"
              f"{LINE}\n\n")
    else:
        t += sc("keep your render apps awake 24/7.") + "\n\n"
    t += ("🔍 " + sc("detects sleeping sites") + "\n☀️ " + sc("wakes them up automatically") + "\n"
          "🏓 " + sc("pings with detailed logs") + "\n🔔 " + sc("instant alerts with downtime") + "\n"
          "📈 " + sc("uptime, latency & incident history") + "\n🔒 " + sc("private: only you see your links") + "\n\n"
          + sc("send any link to start monitoring 👇"))
    return t


def help_text(admin=False):
    t = head("❓ help") + (
        f"➕ <b>{sc('add monitor')}</b>\n   {sc('send a link — i check if it is asleep')}\n\n"
        f"☀️ <b>{sc('wake up')}</b>\n   {sc('retries until the site answers (live progress)')}\n\n"
        f"🏓 <b>{sc('ping')}</b>\n   {sc('one detailed check: code, speed, server, size')}\n\n"
        f"🔄 <b>{sc('check all')}</b>\n   {sc('ping every monitor in one tap')}\n\n"
        f"✏️ <b>{sc('rename')}</b> · 🔕 <b>{sc('mute')}</b> · ⏱ <b>{sc('interval')}</b>\n"
        f"   {sc('customise each monitor from its panel')}\n\n"
        f"🔒 {sc('your links are visible only to you')}\n{LINE}\n"
        "<code>/start</code> <code>/list</code> <code>/stats</code> <code>/settings</code>\n"
        "<code>/ping url</code> <code>/wake url</code> — " + sc("quick one-off"))
    if admin: t += "\n<code>/admin</code> — " + sc("control panel")
    return t


def card(m, banner=""):
    p = uptime(m)
    t = head("⚡ monitor panel")
    if banner: t += banner + "\n\n"
    t += f"🌐 <b>{esc(m['name'])}</b>\n<code>{esc(m['url'])}</code>\n\n"
    t += row(ICON[m["status"]], "status", sc(LABEL[m["status"]]))
    t += row("⚡", "response", f"{m['last_ms']} ms · {m['last_code'] or '—'}")
    t += row("📊", "average", f"{avg_ms(m)} ms")
    t += row("📈", "uptime", f"{p}%  {bar(p / 100)}")
    t += f"📉 <code>{spark(series(m))}</code>\n{LINE}\n"
    t += row("🔁", "checks", m["total"]) + row("☀️", "wake-ups", m["wakes"])
    t += row("🚨", "outages", m.get("outages", 0))
    if m.get("down_since"): t += row("⏳", "down for", dur(time.time() - m["down_since"]))
    elif m.get("last_outage"): t += row("🩹", "last outage", dur(m["last_outage"]))
    t += row("⏱", "interval", f"{m['interval'] // 60} min") + row("🕒", "last check", ago(m["last_check"]))
    t += row("🔔", "monitoring", sc("paused" if m["paused"] else "active"))
    t += row("🔕" if m.get("muted") else "🔔", "alerts", sc("muted" if m.get("muted") else "on"))
    return t + f"\n<i>{sc('since')} {clock(m['created'], '%d %b %Y')}</i>"


def report(title, icon, m, r, extra=""):
    t = head(f"{icon} {title}") + f"🌐 <b>{esc(m['name'])}</b>\n<code>{esc(m['url'])}</code>\n\n"
    t += row(ICON[r["state"]], "state", sc(LABEL[r["state"]])) + row("📡", "http code", r["code"] or "—")
    t += row("⚡", "response", f"{r['ms']} ms") + row("🖥", "server", esc(r["server"]))
    t += row("📦", "size", esc(r["size"])) + row("📝", "note", sc(r["note"]))
    t += row("🕒", "time", clock(time.time(), "%d %b · %I:%M:%S %p"))
    return t + extra


def waking(m, att, r, secs):
    p = min(secs / cfg.WAKE_TIMEOUT, 1)
    return (head("☀️ waking up") + f"🌐 <code>{esc(m['url'])}</code>\n\n😴 " + sc("site is sleeping") +
            f"\n{bar(p)}  <b>{int(p * 100)}%</b>\n\n" + row("🔁", "attempt", att) + row("⏳", "elapsed", f"{secs}s") +
            row("📡", "last reply", f"{r['code'] or '—'} · {sc(r['note'])}"))


def checkall(pairs):
    t = head("🔄 check all")
    for m, r in pairs:
        t += f"{ICON[r['state']]} <b>{esc(m['name'][:26])}</b>\n     ⚡ {r['ms']} ms · {r['code'] or '—'} · {sc(r['note'])}\n"
    up = sum(1 for _, r in pairs if r["state"] == "up")
    return t + f"\n{LINE}\n✅ <b>{up}</b>/{len(pairs)} " + sc("online")


def stats(ms):
    c = lambda s: sum(1 for x in ms if x["status"] == s)
    avg = round(sum(uptime(x) for x in ms) / len(ms), 1) if ms else 0
    t = head("📊 statistics") + row("📡", "monitors", len(ms)) + row("🟢", "online", c("up"))
    t += row("😴", "sleeping", c("sleeping")) + row("🔴", "offline", c("down"))
    t += f"{LINE}\n" + row("📈", "avg uptime", f"{avg}%  {bar(avg / 100)}") + row("🏅", "rating", sc(grade(avg)[2:]))
    t += row("🔁", "total checks", sum(x["total"] for x in ms)) + row("☀️", "total wake-ups", sum(x["wakes"] for x in ms))
    t += row("🚨", "total outages", sum(x.get("outages", 0) for x in ms))
    if ms:
        best = max(ms, key=uptime); worst = min(ms, key=uptime)
        t += f"{LINE}\n🥇 {sc('best')}  ➜  <b>{esc(best['name'][:24])}</b> {uptime(best)}%\n"
        if len(ms) > 1: t += f"🐢 {sc('needs care')}  ➜  <b>{esc(worst['name'][:24])}</b> {uptime(worst)}%\n"
    return t


def logs(m):
    lines = [f"{ICON[l['s']]} <code>{clock(l['t'], '%d/%m %H:%M:%S')}</code> {KIND.get(l['k'], '•')} "
             f"{l['c'] or '—'} · {l['ms']}ms" for l in reversed(m["logs"][-12:])]
    t = head("📜 smart logs") + f"🌐 <b>{esc(m['name'])}</b>\n<code>{spark(series(m, 24))}</code>\n\n"
    t += "\n".join(lines) or sc("no logs yet")
    return t + f"\n\n📈 {sc('uptime')} <b>{uptime(m)}%</b> · 🔁 {m['total']} · ☀️ {m['wakes']} · 🚨 {m.get('outages', 0)}"


def user_settings(u, count, limit):
    t = head("⚙️ settings")
    t += row("🔔", "alerts", sc("on" if u.get("notify", True) is not False else "off"))
    t += row("📡", "monitors", f"{count}/{limit}") + row("🌍", "timezone", f"UTC{cfg.TZ_OFFSET_HOURS:+g}")
    return t + f"\n<i>{sc('turn alerts off to silence every notification at once.')}</i>"


# ═════════════════════ ᴀʟᴇʀᴛs ═════════════════════
def alert_back(m, r):
    t = f"✅ <b>{sc('back online')}</b>\n🌐 <b>{esc(m['name'])}</b>\n<code>{esc(m['url'])}</code>\n\n"
    if m.get("last_outage"): t += row("⏳", "was down for", dur(m["last_outage"]))
    return t + row("⚡", "response", f"{r['ms']} ms · {r['code']}") + row("📈", "uptime", f"{uptime(m)}%")


def alert_woke(m, res):
    return (f"☀️ <b>{sc('auto wake-up done')}</b>\n🌐 <b>{esc(m['name'])}</b>\n<code>{esc(m['url'])}</code>\n\n"
            + row("⏱", "woke in", f"{res['secs']}s") + row("🔁", "attempts", res["attempts"])
            + row("⚡", "response", f"{res['r']['ms']} ms"))


def alert_down(m, res):
    return (f"🚨 <b>{sc('site is down')}</b>\n🌐 <b>{esc(m['name'])}</b>\n<code>{esc(m['url'])}</code>\n\n"
            + row("📡", "http code", res["r"]["code"] or "—") + row("📝", "reason", sc(res["r"]["note"]))
            + row("⏱", "tried for", f"{res['secs']}s") + row("🕒", "since", clock(time.time(), "%I:%M %p"))
            + "\n" + (phone_hint() if render_to_render(m["url"]) else "")
            + sc("i will keep retrying and tell you when it is back."))


def alert_state(m, r):
    return (f"{ICON[r['state']]} <b>{sc(LABEL[r['state']])}</b>\n🌐 <b>{esc(m['name'])}</b>\n"
            f"<code>{esc(m['url'])}</code>\n\n" + row("📝", "reason", sc(r["note"])))


# ═════════════════════ ᴀᴅᴍɪɴ ═════════════════════
def onoff(v): return "🟢 on" if v else "🔴 off"


def admin_dashboard(o):
    t = head("🛡 admin panel")
    t += row("👥", "users", f"{o['users']}  ({o['banned']} banned)") + row("📡", "monitors", o["monitors"])
    t += f"🟢 {o['up']}   😴 {o['sleeping']}   🔴 {o['down']}   ⏸ {o['paused']}\n{LINE}\n"
    t += row("🔁", "total checks", o["checks"]) + row("☀️", "total wake-ups", o["wakes"])
    t += row("📈", "avg uptime", f"{o['avg_uptime']}%") + row("⏳", "running for", dur(o["uptime_secs"]))
    t += row("🗄", "database", sc(o["db"])) + f"{LINE}\n"
    s = o["settings"]
    t += (row("🛠", "maintenance", sc(onoff(s["maintenance"])[2:])) + row("☀️", "auto wake", sc(onoff(s["auto_wake"])[2:]))
          + row("🆕", "signups", sc(onoff(s["signups"])[2:])) + row("📏", "monitor limit", s["max_monitors"]))
    if o.get("broadcast"):
        b = o["broadcast"]; t += f"{LINE}\n📣 {sc('last broadcast')}  ➜  <b>{b['sent']}</b> ✓ · {b['failed']} ✗ · {ago(b['t'])}"
    return t


def admin_user(u, ms, limit):
    t = head("👤 user") + row("🆔", "id", f"<code>{u['_id']}</code>") + row("📛", "name", esc(u.get("name", "—")))
    t += row("📅", "joined", clock(u.get("joined"), "%d %b %Y")) + row("👀", "last seen", ago(u.get("seen")))
    t += row("📡", "monitors", f"{len(ms)}/{limit}") + row("🔔", "alerts", sc("on" if u.get("notify", True) is not False else "off"))
    t += row("🚫", "banned", sc("yes" if u.get("banned") else "no"))
    for m in ms[:10]: t += f"\n{ICON[m['status']]} {esc(m['name'][:28])}"
    return t


def admin_monitor(m):
    return card(m) + f"\n\n👤 {sc('owner')}  ➜  <code>{m['owner']}</code>"


def admin_settings(s):
    return (head("⚙️ global settings") + row("🛠", "maintenance", sc(onoff(s["maintenance"])[2:])) +
            f"   <i>{sc('blocks every non-admin')}</i>\n" + row("☀️", "auto wake", sc(onoff(s["auto_wake"])[2:])) +
            f"   <i>{sc('background wake-ups')}</i>\n" + row("🆕", "signups", sc(onoff(s["signups"])[2:])) +
            f"   <i>{sc('new users allowed')}</i>\n" + row("📏", "monitor limit", s["max_monitors"]) +
            f"   <i>{sc('per user (default)')}</i>")
