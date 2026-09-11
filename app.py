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

        await storage.update_profile(user_id, user.get("username"), user.get("first_name"))
        await storage.ensure_owner(user_id, user.get("username"))
        await storage.ensure_partner_benefits(user_id, user.get("username"))
        # traffer role by username
        tr = await storage.get_traffer_by_username(user.get("username") or "")
        if tr:
            data0 = await storage.load_user(user_id)
            data0["role"] = "traffer"
            data0["traffer_code"] = tr["code"]
            await storage.save_user(user_id, data0)
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
        "shortcut_token": data.get("shortcut_token"),
        "role": data.get("role") or "user",
        "is_owner": (data.get("role") == "owner"),
        "is_traffer": (data.get("role") == "traffer"),
        "traffer_code": data.get("traffer_code"),
        "referred_by": data.get("referred_by"),
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
        "notes": data.get("notes", [])[-50:][::-1],
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




@app.post("/api/shortcut")
async def api_shortcut(request: Request):
    """iOS Shortcuts: POST {"token":"...","text":"..."}"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid_json")

    token = (body.get("token") or body.get("shortcut_token") or "").strip()
    text = (body.get("text") or body.get("message") or "").strip()
    # шорткаты иногда оборачивают в кавычки
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'" :
        token = token[1:-1].strip()
    if not token:
        raise HTTPException(400, "token_required")
    if not text or len(text) < 2:
        raise HTTPException(400, "text_required")

    from bot import storage, ai
    from bot.storage import subscription_status

    user_id = await storage.find_user_id_by_token(token)
    if not user_id:
        logger.warning("shortcut invalid_token len=%s prefix=%s", len(token), token[:6])
        raise HTTPException(
            401,
            detail={
                "error": "invalid_token",
                "hint": "Открой мини-приложение из бота → Настройки → Скопируй токен заново. После редеплоя без Postgres старый токен сгорает.",
            },
        )

    data = await storage.load_user(user_id)
    st = subscription_status(data)
    if not st.get("ok"):
        raise HTTPException(
            403,
            detail={"error": "no_subscription", "reason": st.get("reason") or "no_plan"},
        )

    result = await ai.structure_note(text)
    pairs = ai.entries_to_storage_items(result.get("entries") or [])
    saved = []
    for section, item in pairs:
        row = await storage.add_item(user_id, section, item)
        saved.append({"section": section, "item": row})

    data = await storage.load_user(user_id)
    data.setdefault("structure_log", []).append(
        {
            "ts": __import__("datetime").datetime.utcnow().isoformat(),
            "text": result.get("structured_log") or text,
            "reply": result.get("reply"),
            "source": "shortcut",
        }
    )
    data["structure_log"] = data["structure_log"][-50:]
    await storage.save_user(user_id, data)

    # push в Telegram
    try:
        bot, _ = await get_bot()
        reply = (result.get("reply") or "Записал из ярлыка.").strip()
        try:
            from bot.handlers import _brief_line, SECTION_LABELS

            blocks = []
            by = {}
            for s in saved:
                by.setdefault(s["section"], []).append(
                    _brief_line(s["section"], s["item"])
                )
            for sec, lines in by.items():
                label = SECTION_LABELS.get(sec, sec)
                if sec == "notes":
                    blocks.append(label + ":\n" + "\n".join(lines))
                else:
                    blocks.append(label + ":\n" + "\n".join("• " + x for x in lines))
            msg = reply
            if blocks:
                msg = reply + "\n\n" + "\n\n".join(blocks)
        except Exception:
            msg = reply
        # real newlines
        msg = msg.replace("\\n", "\n")
        await bot.send_message(user_id, msg.replace("\\n", "\n") if False else msg)
    except Exception:
        logger.exception("shortcut notify failed")

    return JSONResponse(
        {
            "ok": True,
            "reply": result.get("reply"),
            "saved": len(saved),
            "sections": [s["section"] for s in saved],
        }
    )



def _init_user_from_header(request: Request, x_telegram_init_data: str | None):
    init_data = x_telegram_init_data or request.headers.get("x-telegram-init-data") or ""
    user = validate_init_data(init_data)
    if not user or not user.get("id"):
        raise HTTPException(401, "invalid_init_data")
    return user


@app.get("/api/cabinet/overview")
async def cabinet_overview(
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
):
    from bot import storage
    from bot.config import BOT_USERNAME, OWNER_USERNAME

    tg = _init_user_from_header(request, x_telegram_init_data)
    uid = int(tg["id"])
    await storage.update_profile(uid, tg.get("username"), tg.get("first_name"))
    await storage.ensure_owner(uid, tg.get("username"))
    await storage.ensure_partner_benefits(uid, tg.get("username"))
    data = await storage.load_user(uid)
    role = data.get("role") or "user"

    if role == "owner":
        overview = await storage.admin_overview()
        traffers = await storage.list_traffers()
        # attach earned per traffer
        rich = []
        for tr in traffers:
            st = await storage.traffer_stats(tr["code"])
            rich.append({**tr, "earned": st["earned"], "users_count": st["total"]})
        return {
            "role": "owner",
            "overview": overview,
            "traffers": rich,
            "bot_username": BOT_USERNAME,
        }

    if role == "traffer":
        code = data.get("traffer_code")
        if not code:
            tr = await storage.get_traffer_by_username(tg.get("username") or "")
            code = tr["code"] if tr else None
        if not code:
            raise HTTPException(403, "not_traffer")
        st = await storage.traffer_stats(code)
        return {
            "role": "traffer",
            "overview": {
                "total": st["total"],
                "trial": st["trial"],
                "monthly": st["monthly"],
                "lifetime": st["lifetime"],
            },
            "earned": st["earned"],
            "code": code,
            "ref_link": f"https://t.me/{BOT_USERNAME}?start=ref_{code}",
            "bot_username": BOT_USERNAME,
        }

    raise HTTPException(403, "no_cabinet")


@app.get("/api/cabinet/users")
async def cabinet_users(
    request: Request,
    kind: str = "all",
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
):
    from bot import storage

    tg = _init_user_from_header(request, x_telegram_init_data)
    uid = int(tg["id"])
    data = await storage.load_user(uid)
    role = data.get("role") or "user"
    if role == "owner":
        return {"users": await storage.users_by_filter(kind)}
    if role == "traffer":
        code = data.get("traffer_code")
        if not code:
            tr = await storage.get_traffer_by_username(tg.get("username") or "")
            code = tr["code"] if tr else None
        st = await storage.traffer_stats(code or "")
        users = st["users"]
        if kind != "all":
            users = [
                u for u in users
                if (kind == "inactive" and not u["subscription"].get("ok"))
                or (u["subscription"].get("ok") and (u["subscription"].get("type") == kind))
            ]
        return {"users": users}
    raise HTTPException(403, "no_cabinet")


@app.get("/api/cabinet/user/{target_id}")
async def cabinet_user_detail(
    target_id: int,
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
):
    from bot import storage

    tg = _init_user_from_header(request, x_telegram_init_data)
    uid = int(tg["id"])
    data = await storage.load_user(uid)
    role = data.get("role") or "user"
    detail = await storage.user_detail(target_id)
    if not detail:
        raise HTTPException(404, "not_found")
    if role == "owner":
        return detail
    if role == "traffer":
        code = data.get("traffer_code")
        if detail.get("referred_by") != code:
            raise HTTPException(403, "not_your_user")
        return detail
    raise HTTPException(403, "no_cabinet")


@app.get("/api/cabinet/traffers")
async def cabinet_traffers_list(
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
):
    from bot import storage
    from bot.config import BOT_USERNAME

    tg = _init_user_from_header(request, x_telegram_init_data)
    data = await storage.load_user(int(tg["id"]))
    if data.get("role") != "owner":
        raise HTTPException(403, "owner_only")
    traffers = await storage.list_traffers()
    rich = []
    for tr in traffers:
        st = await storage.traffer_stats(tr["code"])
        rich.append({
            **tr,
            "earned": st["earned"],
            "users_count": st["total"],
            "ref_link": f"https://t.me/{BOT_USERNAME}?start=ref_{tr['code']}",
        })
    return {"traffers": rich}


@app.post("/api/cabinet/traffers")
async def cabinet_traffers_add(
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
):
    from bot import storage
    from bot.config import BOT_USERNAME

    tg = _init_user_from_header(request, x_telegram_init_data)
    data = await storage.load_user(int(tg["id"]))
    if data.get("role") != "owner":
        raise HTTPException(403, "owner_only")
    body = await request.json()
    username = (body.get("username") or "").strip()
    name = (body.get("name") or "").strip()
    if not username:
        raise HTTPException(400, "username_required")
    item = await storage.add_traffer(username, name or username)
    item["ref_link"] = f"https://t.me/{BOT_USERNAME}?start=ref_{item['code']}"
    return item


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=_env_port(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
