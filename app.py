"""
ECHO Planner — Render entrypoint (корень репозитория).

Start: uvicorn app:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger("echo.app")
logging.basicConfig(level=logging.INFO)

_bot = None
_dp = None
_bot_lock = asyncio.Lock()
_webhook_set = False


def _env_port() -> int:
    return int(os.getenv("PORT", "10000"))


def _public_base() -> str:
    return (
        os.getenv("RENDER_EXTERNAL_URL")
        or os.getenv("WEBHOOK_HOST")
        or os.getenv("API_PUBLIC_URL")
        or "https://echo-planner-ppeb.onrender.com"
    ).rstrip("/")


def _bot_token() -> str:
    return os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""


def validate_init_data(init_data: str) -> dict | None:
    token = _bot_token()
    if not init_data or not token:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if calculated != received_hash:
            return None
        return json.loads(parsed.get("user", "{}"))
    except Exception:
        logger.exception("initData validate failed")
        return None


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
        from bot.handlers import router

        token = _bot_token()
        if not token:
            raise RuntimeError("BOT_TOKEN is not set")

        logger.info("Lazy-init bot…")
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
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
    logger.info("App start port=%s", _env_port())
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

# CORS сразу при создании app — иначе браузер/WebView режет /api/*
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


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
        "api": True,
    })


@app.get("/api/ping")
async def api_ping():
    """Проверка доступности API без Telegram."""
    return {"ok": True, "service": "echo-api"}


@app.get("/api/me")
@app.get("/api/subscription")
async def api_me(
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
):
    """
    Статус подписки для мини-приложения.
    Header: X-Telegram-Init-Data  (Telegram.WebApp.initData)
    """
    init_data = x_telegram_init_data or ""
    # иногда прокси/клиент шлёт в другом регистре — подстрахуемся
    if not init_data:
        init_data = request.headers.get("x-telegram-init-data") or ""

    user = validate_init_data(init_data)
    if not user or not user.get("id"):
        # Для отладки: отличаем «нет header» от «битая подпись»
        detail = "no_init_data" if not init_data else "invalid_init_data"
        raise HTTPException(status_code=401, detail=detail)

    user_id = int(user["id"])

    try:
        from bot import storage
        from bot.storage import subscription_status

        data = await storage.load_user(user_id)
        st = subscription_status(data)
        stats = await storage.get_stats(user_id)
    except Exception:
        logger.exception("storage error")
        raise HTTPException(status_code=500, detail="storage_error")

    body = {
        "user": {
            "id": user_id,
            "first_name": user.get("first_name"),
            "username": user.get("username"),
        },
        "subscription": {
            "active": bool(st.get("active")),
            "ok": bool(st.get("ok")),
            "type": st.get("type") or st.get("plan"),
            "until": st.get("until"),
            "reason": st.get("reason"),
            "trial_used": st.get("trial_used", False),
        },
        "stats": stats,
        "finance": data.get("finance", [])[-50:][::-1],
        "calendar": data.get("calendar", [])[-50:][::-1],
        "tasks": data.get("tasks", [])[-50:][::-1],
        "nutrition": data.get("nutrition", [])[-50:][::-1],
    }
    return JSONResponse(body)


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

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=_env_port(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
