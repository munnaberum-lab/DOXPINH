"""⚡ Dotxbrain Uptime Pro — background monitoring, auto-wake and alerts."""
import asyncio, logging, time

import info as cfg
import templates as T
from core import UserError, branded, dur, row, sc

log = logging.getLogger("dotxbrain.worker")
_sem = asyncio.Semaphore(20)


async def alert(bot, uid, text):
    try: await bot.send_message(uid, branded(text))
    except Exception as e: log.warning("alert to %s failed: %s", uid, e)


async def run_check(svc, bot, m):
    try:
        if m["owner"] in svc.banned: return
        async with svc.guard(m):
            async with _sem:
                prev = m["status"]
                r = await svc.probe(m["url"])
                await svc.record(m, "auto", r)
                loud = await svc.should_alert(m)
                if r["state"] == "up":
                    if prev in ("sleeping", "down") and loud: await alert(bot, m["owner"], T.alert_back(m, r))
                    return
                if not svc.setting("auto_wake"):
                    if prev != r["state"] and loud: await alert(bot, m["owner"], T.alert_state(m, r))
                    return
                res = await svc.wake(m)
                if not loud: return
                if res["ok"]: await alert(bot, m["owner"], T.alert_woke(m, res))
                elif prev not in ("sleeping", "down"):      # alert once, not every cycle
                    await alert(bot, m["owner"], T.alert_down(m, res))
    except UserError:
        pass                      # monitor busy (user is waking it right now) → skip this round
    except Exception:
        log.exception("check failed for %s", m.get("id"))


_tasks: set = set()

async def tick(svc, bot):
    due = await svc.db.due(int(time.time()))
    out = []
    for m in due:
        t = asyncio.create_task(run_check(svc, bot, m))
        _tasks.add(t); t.add_done_callback(_tasks.discard); out.append(t)
    return out


async def monitor_loop(svc, bot):
    while True:
        try: await tick(svc, bot)
        except Exception: log.exception("tick failed")
        await asyncio.sleep(15)


PING_EVERY = 240          # seconds — well under Render's 15-minute idle limit (a missed ping still leaves a spare)
GAP_ALERT = 300           # tell admins when the bot was unreachable for longer than this


async def self_ping(session):
    """Keeps THIS service awake on Render's free plan by sending real inbound traffic via the public URL."""
    while cfg.BASE_URL:
        await asyncio.sleep(PING_EVERY)
        try:
            async with session.get(cfg.BASE_URL + "/health") as r: await r.read()
            log.info("self-ping ok (%s)", r.status)
        except Exception as e: log.warning("self ping failed: %s", e)


async def heartbeat(svc, bot):
    """Writes a timestamp every minute. After a sleep/crash/redeploy the first thing the bot does is
    compare it with now and tell the admins how long it was gone (a sleeping process cannot wake
    itself — an external pinger must do that, see README)."""
    last = svc.settings.get("heartbeat"); now = int(time.time())
    if last and now - last > GAP_ALERT:
        for uid in cfg.ADMIN_IDS:
            await alert(bot, uid, f"😴 <b>{sc('bot was asleep')}</b>\n" + row("⏳", "offline for", dur(now - last)) +
                        row("☀️", "status", sc("awake again — monitors resume now")) +
                        "\n" + sc("tip: add an external pinger so this never happens (see readme)."))
    while True:
        try: await svc.db.save_setting("heartbeat", int(time.time()))
        except Exception as e: log.warning("heartbeat failed: %s", e)
        await asyncio.sleep(60)
