"""
Хранилище пользователей ECHO Planner.

Приоритет:
1) DATABASE_URL (postgres:// / postgresql://) — переживает редеплой на Render
2) SQLite файл (DATABASE_PATH или data/echo.db)

Все данные юзера — один JSON-документ на telegram user_id.
"""

from __future__ import annotations

import json
import os
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from .config import DATA_DIR, TRIAL_DAYS

logger = logging.getLogger("echo.storage")

# --- backend selection ---
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH")
    or str(DATA_DIR / "echo.db")
)

_pg_pool = None
_sqlite = None
_init_done = False


def _default_user() -> dict:
    return {
        "created_at": datetime.utcnow().isoformat(),
        "subscription": {
            "active": False,
            "type": None,
            "until": None,
            "payment_id": None,
            "trial_started": None,
            "trial_used": False,
        },
        "finance": [],
        "calendar": [],
        "tasks": [],
        "nutrition": [],
        "chat_history": [],
    }


def _is_postgres() -> bool:
    u = DATABASE_URL.lower()
    return u.startswith("postgres://") or u.startswith("postgresql://")


# ---------- SQLite ----------

async def _sqlite_conn():
    global _sqlite
    import aiosqlite

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _sqlite is None:
        _sqlite = await aiosqlite.connect(str(DATABASE_PATH))
        _sqlite.row_factory = aiosqlite.Row
        await _sqlite.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                data    TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await _sqlite.commit()
        logger.info("SQLite ready: %s", DATABASE_PATH)
    return _sqlite


async def _pg_pool_get():
    global _pg_pool
    import asyncpg

    if _pg_pool is None:
        url = DATABASE_URL
        # Render sometimes gives postgres:// — asyncpg wants postgresql://
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        _pg_pool = await asyncpg.create_pool(url, min_size=1, max_size=4)
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    data    JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        logger.info("Postgres pool ready")
    return _pg_pool


async def _ensure_init():
    global _init_done
    if _init_done:
        return
    if _is_postgres():
        await _pg_pool_get()
    else:
        await _sqlite_conn()
    _init_done = True


# ---------- public API (same as before) ----------

async def load_user(user_id: int) -> dict:
    await _ensure_init()
    uid = int(user_id)

    if _is_postgres():
        pool = await _pg_pool_get()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM users WHERE user_id=$1", uid
            )
            if row is None:
                data = _default_user()
                await conn.execute(
                    "INSERT INTO users (user_id, data) VALUES ($1, $2::jsonb) "
                    "ON CONFLICT (user_id) DO NOTHING",
                    uid,
                    json.dumps(data, ensure_ascii=False),
                )
                return data
            data = row["data"]
            if isinstance(data, str):
                data = json.loads(data)
    else:
        db = await _sqlite_conn()
        cur = await db.execute(
            "SELECT data FROM users WHERE user_id=?", (uid,)
        )
        row = await cur.fetchone()
        if row is None:
            data = _default_user()
            await db.execute(
                "INSERT INTO users (user_id, data, updated_at) VALUES (?, ?, ?)",
                (uid, json.dumps(data, ensure_ascii=False), datetime.utcnow().isoformat()),
            )
            await db.commit()
            return data
        data = json.loads(row["data"])

    # migrate missing keys
    base = _default_user()
    for k, v in base.items():
        if k not in data:
            data[k] = v
    sub = data.setdefault("subscription", base["subscription"])
    for k, v in base["subscription"].items():
        sub.setdefault(k, v)
    return data


async def save_user(user_id: int, data: dict) -> None:
    await _ensure_init()
    uid = int(user_id)
    payload = json.dumps(data, ensure_ascii=False)
    now = datetime.utcnow().isoformat()

    if _is_postgres():
        pool = await _pg_pool_get()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, data, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (user_id) DO UPDATE
                  SET data = EXCLUDED.data,
                      updated_at = NOW()
                """,
                uid,
                payload,
            )
    else:
        db = await _sqlite_conn()
        await db.execute(
            """
            INSERT INTO users (user_id, data, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              data=excluded.data,
              updated_at=excluded.updated_at
            """,
            (uid, payload, now),
        )
        await db.commit()


async def add_item(user_id: int, section: str, item: dict) -> dict:
    data = await load_user(user_id)
    data.setdefault(section, [])
    item["id"] = f"{section}_{len(data[section]) + 1}_{int(datetime.utcnow().timestamp())}"
    item["created_at"] = datetime.utcnow().isoformat()
    data[section].append(item)
    await save_user(user_id, data)
    return item


async def update_task(user_id: int, task_id: str, done: bool) -> bool:
    data = await load_user(user_id)
    for t in data.get("tasks", []):
        if t["id"] == task_id:
            t["done"] = done
            await save_user(user_id, data)
            return True
    return False


def subscription_status(data: dict) -> dict:
    sub = data.get("subscription") or {}
    trial_used = bool(sub.get("trial_used") or sub.get("trial_started"))
    now = datetime.utcnow()
    today = date.today()

    if sub.get("type") == "lifetime" and sub.get("active"):
        return {
            "ok": True,
            "active": True,
            "plan": "lifetime",
            "type": "lifetime",
            "until": None,
            "reason": None,
            "trial_used": trial_used,
        }

    if sub.get("type") == "monthly" and sub.get("active") and sub.get("until"):
        try:
            until = date.fromisoformat(str(sub["until"])[:10])
            if until >= today:
                return {
                    "ok": True,
                    "active": True,
                    "plan": "monthly",
                    "type": "monthly",
                    "until": until.isoformat(),
                    "reason": None,
                    "trial_used": trial_used,
                }
            return {
                "ok": False,
                "active": False,
                "plan": None,
                "type": "monthly",
                "until": until.isoformat(),
                "reason": "expired",
                "trial_used": trial_used,
            }
        except Exception:
            pass

    if sub.get("type") == "trial" and (sub.get("trial_started") or sub.get("until")):
        try:
            if sub.get("trial_started"):
                started = datetime.fromisoformat(str(sub["trial_started"]).replace("Z", ""))
                ends = started + timedelta(days=TRIAL_DAYS)
            else:
                ends_d = date.fromisoformat(str(sub["until"])[:10])
                ends = datetime(ends_d.year, ends_d.month, ends_d.day) + timedelta(days=1)
            if now < ends:
                return {
                    "ok": True,
                    "active": True,
                    "plan": "trial",
                    "type": "trial",
                    "until": ends.date().isoformat(),
                    "reason": None,
                    "trial_used": True,
                }
            return {
                "ok": False,
                "active": False,
                "plan": None,
                "type": "trial",
                "until": ends.date().isoformat(),
                "reason": "trial_ended",
                "trial_used": True,
            }
        except Exception:
            logger.exception("trial status parse")
            return {
                "ok": False,
                "active": False,
                "plan": None,
                "type": "trial",
                "until": None,
                "reason": "trial_ended",
                "trial_used": True,
            }

    if trial_used:
        return {
            "ok": False,
            "active": False,
            "plan": None,
            "type": sub.get("type"),
            "until": sub.get("until"),
            "reason": "trial_ended",
            "trial_used": True,
        }

    return {
        "ok": False,
        "active": False,
        "plan": None,
        "type": None,
        "until": None,
        "reason": "no_plan",
        "trial_used": False,
    }


async def set_subscription(
    user_id: int,
    sub_type: str,
    until: str | None = None,
    payment_id: str | None = None,
    trial_started: str | None = None,
):
    data = await load_user(user_id)
    prev = data.get("subscription") or {}
    trial_used = bool(prev.get("trial_used") or prev.get("trial_started") or sub_type == "trial")
    started = trial_started or prev.get("trial_started")
    if sub_type == "trial" and not started:
        started = datetime.utcnow().isoformat()

    data["subscription"] = {
        "active": True,
        "type": sub_type,
        "until": until,
        "payment_id": payment_id,
        "trial_started": started,
        "trial_used": trial_used if sub_type != "trial" else True,
    }
    await save_user(user_id, data)
    logger.info(
        "set_subscription user=%s type=%s until=%s",
        user_id,
        sub_type,
        until,
    )


async def get_stats(user_id: int) -> dict:
    data = await load_user(user_id)
    today = date.today().isoformat()
    month = today[:7]
    st = subscription_status(data)

    month_spend = sum(
        x.get("amount", 0)
        for x in data.get("finance", [])
        if str(x.get("date", "")).startswith(month)
    )
    days_with = len(
        {
            x.get("date")
            for x in data.get("finance", [])
            if str(x.get("date", "")).startswith(month)
        }
    ) or 1

    now = datetime.utcnow()
    meetings = data.get("calendar", [])
    week_count = 0
    nearest = None
    for m in sorted(meetings, key=lambda x: x.get("datetime", "")):
        try:
            dt = datetime.fromisoformat(str(m["datetime"]).replace("Z", ""))
            if 0 <= (dt - now).days <= 7:
                week_count += 1
            if dt >= now and nearest is None:
                nearest = m
        except Exception:
            pass

    tasks = data.get("tasks", [])
    done = sum(1 for t in tasks if t.get("done"))
    total = len(tasks)
    today_meals = [n for n in data.get("nutrition", []) if n.get("date") == today]

    return {
        "finance": {
            "month_spend": round(month_spend, 2),
            "avg_day": round(month_spend / days_with, 2),
            "count": len(
                [x for x in data.get("finance", []) if str(x.get("date", "")).startswith(month)]
            ),
        },
        "calendar": {
            "week_count": week_count,
            "nearest": nearest,
            "total": len(meetings),
        },
        "tasks": {"done": done, "total": total, "open": total - done},
        "nutrition": {
            "calories": sum(n.get("calories", 0) for n in today_meals),
            "protein": sum(n.get("protein", 0) for n in today_meals),
            "fat": sum(n.get("fat", 0) for n in today_meals),
            "carbs": sum(n.get("carbs", 0) for n in today_meals),
            "meals_today": len(today_meals),
        },
        "subscription": {
            "active": st["active"],
            "type": st.get("type") or st.get("plan"),
            "until": st.get("until"),
            "reason": st.get("reason"),
            "trial_used": st.get("trial_used", False),
            "ok": st["ok"],
        },
    }
