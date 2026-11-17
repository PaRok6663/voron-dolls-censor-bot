import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from .config import load_config
from .database import Database
from .handlers import admin, group_moderation, private_dialog, business

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("CensorBot")


async def main():
    logger.info("Starting Censorship & Anti-Spam Bot...")

    # Load configuration
    config = load_config()

    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("\n" + "="*60)
        print(" [ОШИБКА] Токен бота не настроен!")
        print(" 1. Откройте файл config.yaml или .env")
        print(" 2. Вставьте токен вашего бота от @BotFather в BOT_TOKEN")
        print(" 3. Перезапустите бота")
        print("="*60 + "\n")
        return

    # Initialize SQLite Database
    db = Database(config.DATABASE_PATH)
    await db.init()

    # Pre-populate initial admin IDs into bot_admins table
    for aid in config.ADMIN_IDS:
        await db.add_bot_admin(aid, role="superadmin", added_by=0)

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
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Pre-warm visual NSFW model asynchronously
    from .filters.nsfw_analyzer import NSFWAnalyzer
    analyzer = NSFWAnalyzer()
    asyncio.get_event_loop().run_in_executor(None, analyzer.ensure_model)

    # Register Routers
    dp.include_router(admin.router)
    dp.include_router(business.router)
    dp.include_router(group_moderation.router)
    dp.include_router(private_dialog.router)

    # Inject dependencies
    dp["db"] = db
    dp["settings"] = config

    # Check connection
    try:
        me = await bot.get_me()
        logger.info(f"Bot authorized as @{me.username} (ID: {me.id})")
    except Exception as e:
        logger.error(f"Failed to connect to Telegram API: {e}")
        return

    # Delete existing webhook to run polling cleanly and specify allowed updates
    allowed_updates = [
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "business_connection",
        "business_message",
        "edited_business_message",
        "deleted_business_messages",
        "callback_query",
        "my_chat_member"
    ]
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

    # Start long polling with business updates enabled
    try:
        await dp.start_polling(bot, allowed_updates=allowed_updates)
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
