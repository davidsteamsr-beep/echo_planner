from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from . import storage, ai
from .config import BOT_TOKEN

MINIAPP_DIR = Path(__file__).resolve().parent.parent / "mini-app"
if not MINIAPP_DIR.exists():
    MINIAPP_DIR = Path(__file__).resolve().parent.parent / "miniapp"


def create_api_app() -> FastAPI:
    app = FastAPI(title="ECHO Planner API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if MINIAPP_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(MINIAPP_DIR)), name="static")

    @app.get("/")
    async def root():
        index = MINIAPP_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"status": "ECHO Planner API"}

    def validate_init_data(init_data: str) -> dict | None:
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
            user = json.loads(parsed.get("user", "{}"))
            return user
        except Exception:
            return None

    @app.get("/api/me")
    async def me(x_telegram_init_data: str | None = Header(None)):
        user = validate_init_data(x_telegram_init_data or "")
        if not user:
            user = {"id": 0, "first_name": "Dev"}
        data = await storage.load_user(user["id"])
        stats = await storage.get_stats(user["id"])
        return {
            "user": user,
            "stats": stats,
            "finance": data.get("finance", [])[-50:][::-1],
            "calendar": data.get("calendar", [])[-50:][::-1],
            "tasks": data.get("tasks", [])[-50:][::-1],
            "nutrition": data.get("nutrition", [])[-50:][::-1],
        }

    @app.post("/api/arthur")
    async def arthur(request: Request, x_telegram_init_data: str | None = Header(None)):
        body = await request.json()
        question = body.get("question", "").strip()
        if not question:
            raise HTTPException(400, "Empty question")

        user = validate_init_data(x_telegram_init_data or "")
        user_id = user["id"] if user else 0
        data = await storage.load_user(user_id)
        answer = await ai.arthur_reply(user_id, question, data)

        data.setdefault("chat_history", []).append({"role": "user", "content": question})
        data["chat_history"].append({"role": "assistant", "content": answer})
        data["chat_history"] = data["chat_history"][-40:]
        await storage.save_user(user_id, data)

        return {"answer": answer}

    @app.post("/api/task/toggle")
    async def toggle_task(request: Request, x_telegram_init_data: str | None = Header(None)):
        body = await request.json()
        user = validate_init_data(x_telegram_init_data or "")
        user_id = user["id"] if user else 0
        ok = await storage.update_task(user_id, body["task_id"], body["done"])
        return {"ok": ok}

    return app
