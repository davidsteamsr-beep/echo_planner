"""
Запуск ECHO Planner:
1. Бот (polling) + API (FastAPI) в одном процессе для удобства.
"""
import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import BOT_TOKEN
from bot.handlers import router
from bot.api import create_api_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("echo")


async def start_bot():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    dp.include_router(router)
    logger.info("Bot polling started")
    await dp.start_polling(bot)


async def main():
    # FastAPI в отдельном таске
    app = create_api_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        start_bot(),
    )


if __name__ == "__main__":
    asyncio.run(main())
