"""
⚡ Dotxbrain Uptime Pro
Smart uptime monitor + Render wake-up bot with Telegram Mini App.
"""
import asyncio, logging

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from aiohttp import web

import admin_bot
import bot as botmod
import info as cfg
from api import build_app
from core import Service
from db import create_db
from worker import heartbeat, monitor_loop, self_ping

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("dotxbrain")

DESCRIPTION = (f"⚡ Uptime Pro by {cfg.BRAND}\n\nKeep your Render apps awake 24/7. Detects sleeping sites, "
               "wakes them up, pings with detailed logs and sends instant alerts.\n\n"
               "🔒 Your links are private — only you can see them.")
SHORT = f"Uptime Pro by {cfg.BRAND} · keep your apps awake"


async def main():
    token = (cfg.BOT_TOKEN or "").strip()
    if ":" not in token:
        raise SystemExit("❌ BOT_TOKEN is missing or invalid.\n   Render → your service → Environment → add BOT_TOKEN = <token from @BotFather>.")
    log.info("⚡ %s Uptime Pro starting…", cfg.BRAND)

    session = aiohttp.ClientSession()
    bot = runner = None
    tasks = []
    try:
        try:
            db = await create_db()
        except Exception as e:
            raise SystemExit(f"❌ Could not connect to MongoDB: {e}\n   Check MONGO_URI and Atlas network access (0.0.0.0/0).")
        svc = Service(db, session); await svc.load_state()

        bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
        botmod.setup(svc, bot)
        dp = Dispatcher(); dp.include_router(botmod.router); dp.include_router(admin_bot.router)

        runner = web.AppRunner(build_app(svc, bot)); await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", cfg.PORT).start()
        log.info("web server on :%s  ·  database: %s", cfg.PORT, db.name)

        cmds = [BotCommand(command="start", description="Open Uptime Pro"),
                BotCommand(command="list", description="My monitors"),
                BotCommand(command="stats", description="My statistics"),
                BotCommand(command="settings", description="Alerts & preferences"),
                BotCommand(command="ping", description="Quick ping: /ping url"),
                BotCommand(command="wake", description="Wake a site: /wake url"),
                BotCommand(command="help", description="How it works")]
        for step in (lambda: bot.set_my_commands(cmds), lambda: bot.set_my_description(DESCRIPTION),
                     lambda: bot.set_my_short_description(SHORT)):
            try: await step()
            except Exception as e: log.warning("bot profile update skipped: %s", e)
        if botmod.app_url():
            try:
                await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                    text="Dashboard", web_app=WebAppInfo(url=botmod.app_url())))
            except Exception as e: log.warning("menu button skipped: %s", e)

        tasks = [asyncio.create_task(monitor_loop(svc, bot)), asyncio.create_task(self_ping(session)),
                 asyncio.create_task(heartbeat(svc, bot))]
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        for t in tasks: t.cancel()
        if runner: await runner.cleanup()
        if bot: await bot.session.close()
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
