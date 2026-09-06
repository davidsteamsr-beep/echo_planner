from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from . import storage
from .config import BOT_TOKEN
from .storage import subscription_status


def validate_init_data(init_data: str) -> dict | None:
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if calculated != received_hash:
            return None
        return json.loads(parsed.get("user", "{}"))
    except Exception:
        return None


def mount_api(app: FastAPI) -> None:
    """Вешает /api/* на уже созданное FastAPI-приложение (Render app.py)."""

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/me")
    async def me(x_telegram_init_data: str | None = Header(None)):
        user = validate_init_data(x_telegram_init_data or "")
        # Без валидного initData — отказ (без лазеек через id=0)
        if not user or not user.get("id"):
            raise HTTPException(401, "Invalid Telegram initData")

        user_id = int(user["id"])
        data = await storage.load_user(user_id)
        st = subscription_status(data)
        stats = await storage.get_stats(user_id)

        return {
            "user": {"id": user_id, "first_name": user.get("first_name"), "username": user.get("username")},
            "subscription": {
                "active": st["active"],
                "ok": st["ok"],
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

    @app.get("/api/subscription")
    async def subscription_only(x_telegram_init_data: str | None = Header(None)):
        user = validate_init_data(x_telegram_init_data or "")
        if not user or not user.get("id"):
            raise HTTPException(401, "Invalid Telegram initData")
        data = await storage.load_user(int(user["id"]))
        st = subscription_status(data)
        return {
            "active": st["active"],
            "ok": st["ok"],
            "type": st.get("type") or st.get("plan"),
            "until": st.get("until"),
            "reason": st.get("reason"),
            "trial_used": st.get("trial_used", False),
        }
