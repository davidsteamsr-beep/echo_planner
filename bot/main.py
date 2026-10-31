import os
from threading import Thread

# API и polling живут в одном Render Web Service.
# В режиме polling вебхук не ставим, иначе Telegram перестанет отдавать updates.
os.environ.setdefault("BOT_POLLING_MODE", "1")


def run_server():
    """FastAPI (мини-аппа + кабинет) на том же порту, что требует Render."""
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        log_level="info",
    )


Thread(target=run_server, daemon=True).start()

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import BOT_TOKEN, WEBAPP_URL
from .handlers import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    me = await bot.get_me()
    logger.info("ECHO Planner bot @%s started (WEBAPP_URL=%s)", me.username, WEBAPP_URL or "—")


async def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is required")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)

    logger.info("Starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
