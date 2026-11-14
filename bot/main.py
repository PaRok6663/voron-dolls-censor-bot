import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from .config import load_config
from .database import Database
from .handlers import admin, group_moderation, private_dialog

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("CensorBot")


async def main():
    logger.info("Starting Censorship & Anti-Spam Bot...")

    # Load configuration
    config = load_config()

    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error(
            "BOT_TOKEN is not configured! Please provide BOT_TOKEN in .env or config.yaml"
        )
        print("\n" + "="*60)
        print(" ОШИБКА: Не указан токен бота (BOT_TOKEN)!")
        print(" 1. Откройте файл .env или config.yaml")
        print(" 2. Вставьте ваш токен от @BotFather в строку BOT_TOKEN")
        print(" 3. Перезапустите бота")
        print("="*60 + "\n")
        return

    # Initialize SQLite Database
    db = Database(config.DATABASE_PATH)
    await db.init()

    # Detect system/environment proxy if present (e.g. for local Windows runs)
    import urllib.request
    from aiogram.client.session.aiohttp import AiohttpSession
    system_proxies = urllib.request.getproxies()
    proxy_url = system_proxies.get("https") or system_proxies.get("http")
    session = AiohttpSession(proxy=proxy_url) if proxy_url else None
    if proxy_url:
        logger.info(f"Using proxy: {proxy_url}")

    # Initialize Bot & Dispatcher
    bot = Bot(
        token=config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Pass dependencies to all handlers
    dp["db"] = db
    dp["settings"] = config

    # Register handler routers
    dp.include_router(admin.router)
    dp.include_router(group_moderation.router)
    dp.include_router(private_dialog.router)

    # Bot info
    try:
        bot_info = await bot.get_me()
        logger.info(f"Bot authorized as @{bot_info.username} (ID: {bot_info.id})")
        print(f"\n[OK] Бот запущен под ником: @{bot_info.username}")
        print("Для остановки нажмите Ctrl+C\n")
    except Exception as e:
        logger.error(f"Failed to connect to Telegram API: {e}")
        return

    # Delete existing webhook to run polling cleanly
    await bot.delete_webhook(drop_pending_updates=True)

    # Optional lightweight HTTP health-check server for free cloud hosts (Render, Koyeb, etc.)
    import os
    from aiohttp import web
    port_env = os.getenv("PORT")
    runner = None
    if port_env and port_env.isdigit():
        port = int(port_env)
        async def handle_ping(request):
            return web.Response(text="Voron Dolls Bot is alive!")
        app = web.Application()
        app.router.add_get("/", handle_ping)
        app.router.add_get("/health", handle_ping)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Health-check HTTP server listening on port {port}")

    # Start long polling
    try:
        await dp.start_polling(bot)
    finally:
        if runner:
            await runner.cleanup()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot exited by user.")
