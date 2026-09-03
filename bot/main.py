import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from .config import BOT_TOKEN, WEBAPP_URL
from .handlers import router
from .api import create_api_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    logger.info("Bot started")
    # Можно установить webhook здесь, если нужно
    # await bot.set_webhook(f"{WEBAPP_URL}/webhook")


async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)

    # Локальный режим polling (для разработки)
    # В продакшене лучше webhook + FastAPI
    logger.info("Starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
