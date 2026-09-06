"""
ECHO Planner — entrypoint for Render (and similar PaaS).

Проблема 502: процесс долго стартует / не слушает PORT.
Решение: FastAPI поднимается мгновенно, /health всегда живой,
Bot + Dispatcher создаются лениво при первом реальном запросе.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger("echo.app")
logging.basicConfig(level=logging.INFO)

# --- lazy bot state (НЕ создаём Bot/Dispatcher на импорте) ---
_bot = None
_dp = None
_bot_lock = asyncio.Lock()
_webhook_set = False


def _env_port() -> int:
    return int(os.getenv("PORT", "10000"))


def _public_base() -> str:
    """Публичный URL сервиса на Render."""
    return (
        os.getenv("RENDER_EXTERNAL_URL")
        or os.getenv("WEBHOOK_HOST")
        or os.getenv("WEBAPP_URL")
        or ""
    ).rstrip("/")


async def get_bot():
    """Создаёт aiogram Bot + Dispatcher только при первом вызове."""
    global _bot, _dp

    if _bot is not None and _dp is not None:
        return _bot, _dp

    async with _bot_lock:
        if _bot is not None and _dp is not None:
            return _bot, _dp

        # Импорты тяжёлых модулей — внутри, не на верхнем уровне app-старта
        from aiogram import Bot, Dispatcher
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        try:
            from .config import BOT_TOKEN
            from .handlers import router
        except ImportError:
            from config import BOT_TOKEN
            from handlers import router

        if not BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN is not set")

        logger.info("Lazy-init: creating Bot + Dispatcher…")
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = Dispatcher()
        dp.include_router(router)

        _bot = bot
        _dp = dp
        logger.info("Lazy-init: bot ready")
        return _bot, _dp


async def _ensure_webhook() -> None:
    """Один раз выставляет webhook на /webhook (если есть публичный URL)."""
    global _webhook_set
    if _webhook_set:
        return

    base = _public_base()
    if not base:
        logger.warning("No public URL (RENDER_EXTERNAL_URL / WEBHOOK_HOST) — webhook not set")
        return

    bot, _ = await get_bot()
    url = f"{base}/webhook"
    try:
        await bot.set_webhook(
            url=url,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "pre_checkout_query"],
        )
        _webhook_set = True
        logger.info("Webhook set: %s", url)
    except Exception as e:
        logger.exception("Failed to set webhook: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Стартуем быстро: только лог. Бот — по первому запросу / фоном."""
    logger.info("App lifespan start (port=%s)", _env_port())
    # Не блокируем: webhook поставим в фоне после старта
    task = asyncio.create_task(_deferred_setup())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # закрыть сессию бота если создан
    global _bot
    if _bot is not None:
        try:
            await _bot.session.close()
        except Exception:
            pass
    logger.info("App lifespan end")


async def _deferred_setup() -> None:
    """Через короткую паузу (после bind PORT) инициализируем webhook."""
    try:
        await asyncio.sleep(1.0)
        await _ensure_webhook()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Deferred setup failed")


app = FastAPI(title="ECHO Planner", lifespan=lifespan)


@app.get("/health")
@app.get("/healthz")
async def health():
    """Render health check — без Bot/Dispatcher."""
    return PlainTextResponse("ok", status_code=200)


@app.get("/")
async def root():
    return JSONResponse(
        {
            "service": "ECHO Planner",
            "status": "up",
            "bot_ready": _bot is not None,
        }
    )


@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """Telegram updates. Тяжёлая инициализация — только здесь (лениво)."""
    from aiogram.types import Update

    secret = os.getenv("WEBHOOK_SECRET", "")
    if secret and x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=403, detail="bad secret")

    bot, dp = await get_bot()
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return PlainTextResponse("ok")


@app.post("/setup-webhook")
async def setup_webhook():
    """Ручной триггер (для отладки)."""
    await _ensure_webhook()
    return {"ok": True, "webhook_set": _webhook_set, "base": _public_base()}



def create_app() -> FastAPI:
    """Для uvicorn: app:create_app или app:app."""
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "bot.app:app",
        host="0.0.0.0",
        port=_env_port(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
