"""
ECHO Planner — Render entrypoint (корень репозитория).

Start: uvicorn app:app --host 0.0.0.0 --port $PORT
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

_bot = None
_dp = None
_bot_lock = asyncio.Lock()
_webhook_set = False
_api_mounted = False


def _env_port() -> int:
    return int(os.getenv("PORT", "10000"))


def _public_base() -> str:
    return (
        os.getenv("RENDER_EXTERNAL_URL")
        or os.getenv("WEBHOOK_HOST")
        or os.getenv("API_PUBLIC_URL")
        or "https://echo-planner-ppeb.onrender.com"
    ).rstrip("/")


async def get_bot():
    global _bot, _dp
    if _bot is not None and _dp is not None:
        return _bot, _dp

    async with _bot_lock:
        if _bot is not None and _dp is not None:
            return _bot, _dp

        from aiogram import Bot, Dispatcher
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from bot.config import BOT_TOKEN
        from bot.handlers import router

        if not BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN is not set")

        logger.info("Lazy-init bot…")
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()
        dp.include_router(router)
        _bot, _dp = bot, dp
        logger.info("Bot ready")
        return _bot, _dp


async def _ensure_webhook() -> None:
    global _webhook_set
    if _webhook_set:
        return
    base = _public_base()
    if not base:
        logger.warning("No public URL — webhook skipped")
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
    except Exception:
        logger.exception("set_webhook failed")


async def _deferred_setup() -> None:
    try:
        await asyncio.sleep(1.0)
        await _ensure_webhook()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("deferred setup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _api_mounted
    logger.info("App start port=%s", _env_port())
    if not _api_mounted:
        try:
            from bot.api import mount_api
            mount_api(app)
            _api_mounted = True
            logger.info("API mounted")
        except Exception:
            logger.exception("API mount failed")
    task = asyncio.create_task(_deferred_setup())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    global _bot
    if _bot is not None:
        try:
            await _bot.session.close()
        except Exception:
            pass


app = FastAPI(title="ECHO Planner", lifespan=lifespan)


@app.get("/health")
@app.get("/healthz")
async def health():
    return PlainTextResponse("ok", status_code=200)


@app.get("/")
async def root():
    return JSONResponse({
        "service": "ECHO Planner",
        "status": "up",
        "bot_ready": _bot is not None,
        "api": _api_mounted,
    })


@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
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
    await _ensure_webhook()
    return {"ok": True, "webhook_set": _webhook_set, "base": _public_base()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=_env_port(), proxy_headers=True, forwarded_allow_ips="*")
