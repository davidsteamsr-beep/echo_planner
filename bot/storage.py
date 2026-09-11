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
        "notes": [],
        "structure_log": [],
        "chat_history": [],
        "shortcut_token": None,
        "username": None,
        "first_name": None,
        "referred_by": None,  # traffer code
        "role": "user",  # user | traffer | owner
        "payments": [],  # [{type, amount_rub, at, payment_id}]

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


async def ensure_shortcut_token(user_id: int, data: dict) -> dict:
    """Выдаёт постоянный токен для iOS Shortcuts, если ещё нет."""
    import secrets
    if data.get("shortcut_token"):
        return data
    data["shortcut_token"] = secrets.token_urlsafe(24)
    await save_user(user_id, data)
    return data

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
    if not data.get("shortcut_token"):
        import secrets
        data["shortcut_token"] = secrets.token_urlsafe(24)
        # save after return path — force save
        await save_user(user_id, data)
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




async def find_user_id_by_token(token: str) -> int | None:
    """Найти user_id по shortcut_token."""
    import json as _json

    token = (token or "").strip()
    if not token:
        return None
    await _ensure_init()

    if _is_postgres():
        pool = await _pg_pool_get()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM users WHERE data->>'shortcut_token' = $1 LIMIT 1",
                token,
            )
            if row:
                return int(row["user_id"])
            # fallback scan
            rows = await conn.fetch("SELECT user_id, data FROM users")
            for r in rows:
                d = r["data"]
                if isinstance(d, str):
                    try:
                        d = _json.loads(d)
                    except Exception:
                        continue
                if isinstance(d, dict) and (d.get("shortcut_token") or "").strip() == token:
                    return int(r["user_id"])
        return None

    db = await _sqlite_conn()
    # 1) json_extract
    try:
        cur = await db.execute(
            "SELECT user_id FROM users WHERE json_extract(data, '$.shortcut_token') = ? LIMIT 1",
            (token,),
        )
        row = await cur.fetchone()
        if row is not None:
            uid = row["user_id"] if hasattr(row, "keys") else row[0]
            return int(uid)
    except Exception as e:
        logger.warning("json_extract token lookup failed: %s", e)

    # 2) full scan (надёжно на малом числе юзеров)
    cur = await db.execute("SELECT user_id, data FROM users")
    rows = await cur.fetchall()
    for r in rows:
        uid = r["user_id"] if hasattr(r, "keys") else r[0]
        raw = r["data"] if hasattr(r, "keys") else r[1]
        try:
            d = _json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if isinstance(d, dict) and (d.get("shortcut_token") or "").strip() == token:
            return int(uid)
    return None


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


# ——— admin / traffers ———

META_USER_ID = 0


async def _load_meta() -> dict:
    data = await load_user(META_USER_ID)
    data.setdefault("traffers", [])
    return data


async def _save_meta(data: dict) -> None:
    await save_user(META_USER_ID, data)


async def list_all_users() -> list[tuple[int, dict]]:
    """Все пользователи кроме meta (0)."""
    await _ensure_init()
    out: list[tuple[int, dict]] = []
    if _is_postgres():
        pool = await _pg_pool_get()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id, data FROM users WHERE user_id <> 0")
            for r in rows:
                d = r["data"]
                if isinstance(d, str):
                    d = json.loads(d)
                out.append((int(r["user_id"]), d))
    else:
        db = await _sqlite_conn()
        cur = await db.execute("SELECT user_id, data FROM users WHERE user_id <> 0")
        rows = await cur.fetchall()
        for r in rows:
            uid = int(r["user_id"] if hasattr(r, "keys") else r[0])
            raw = r["data"] if hasattr(r, "keys") else r[1]
            d = json.loads(raw) if isinstance(raw, str) else raw
            out.append((uid, d))
    return out


async def update_profile(user_id: int, username: str | None, first_name: str | None) -> dict:
    data = await load_user(user_id)
    if username is not None:
        data["username"] = username.lstrip("@") if username else None
    if first_name is not None:
        data["first_name"] = first_name
    await save_user(user_id, data)
    return data


async def ensure_owner(user_id: int, username: str | None) -> dict:
    """Если username владельца — lifetime + role owner."""
    from .config import OWNER_USERNAME
    data = await load_user(user_id)
    uname = (username or data.get("username") or "").lstrip("@").lower()
    if uname and uname == OWNER_USERNAME.lower():
        data["role"] = "owner"
        data["username"] = uname
        sub = data.setdefault("subscription", {})
        sub["active"] = True
        sub["type"] = "lifetime"
        sub["until"] = None
        await save_user(user_id, data)
    return data


async def set_referred_by(user_id: int, code: str) -> bool:
    """Привязать реферала один раз."""
    data = await load_user(user_id)
    if data.get("referred_by"):
        return False
    if data.get("role") in ("owner", "traffer"):
        return False
    meta = await _load_meta()
    codes = {t.get("code") for t in meta.get("traffers") or []}
    if code not in codes:
        return False
    data["referred_by"] = code
    await save_user(user_id, data)
    return True


async def add_traffer(username: str, name: str) -> dict:
    import secrets
    meta = await _load_meta()
    username = username.lstrip("@").lower().strip()
    name = (name or username).strip()
    code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10]
    # unique
    existing = {t.get("code") for t in meta["traffers"]}
    while code in existing:
        code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10]
    item = {
        "username": username,
        "name": name,
        "code": code,
        "created_at": datetime.utcnow().isoformat(),
        "paid_out": 0,
    }
    meta["traffers"].append(item)
    await _save_meta(meta)
    # если такой tg user уже есть — role traffer
    for uid, d in await list_all_users():
        if (d.get("username") or "").lower() == username:
            d["role"] = "traffer"
            d["traffer_code"] = code
            await save_user(uid, d)
            break
    return item


async def list_traffers() -> list[dict]:
    meta = await _load_meta()
    return list(meta.get("traffers") or [])


async def get_traffer_by_username(username: str) -> dict | None:
    username = (username or "").lstrip("@").lower()
    for t in await list_traffers():
        if (t.get("username") or "").lower() == username:
            return t
    return None


async def record_payment(user_id: int, pay_type: str, payment_id: str | None = None) -> None:
    """pay_type: monthly | lifetime — для выплат траферу."""
    data = await load_user(user_id)
    data.setdefault("payments", []).append(
        {
            "type": pay_type,
            "at": datetime.utcnow().isoformat(),
            "payment_id": payment_id,
        }
    )
    await save_user(user_id, data)


async def admin_overview() -> dict:
    users = await list_all_users()
    total = len(users)
    trial = monthly = lifetime = none = 0
    for uid, d in users:
        st = subscription_status(d)
        plan = st.get("plan") or st.get("type")
        if st.get("ok") and plan == "trial":
            trial += 1
        elif st.get("ok") and plan == "monthly":
            monthly += 1
        elif st.get("ok") and plan == "lifetime":
            lifetime += 1
        else:
            none += 1
    return {
        "total": total,
        "trial": trial,
        "monthly": monthly,
        "lifetime": lifetime,
        "inactive": none,
    }


async def users_by_filter(kind: str) -> list[dict]:
    """kind: all|trial|monthly|lifetime|inactive"""
    rows = []
    for uid, d in await list_all_users():
        st = subscription_status(d)
        plan = st.get("plan") or st.get("type")
        ok = st.get("ok")
        if kind == "trial" and not (ok and plan == "trial"):
            continue
        if kind == "monthly" and not (ok and plan == "monthly"):
            continue
        if kind == "lifetime" and not (ok and plan == "lifetime"):
            continue
        if kind == "inactive" and ok:
            continue
        rows.append(_user_public(uid, d, st))
    rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return rows


def _user_public(uid: int, d: dict, st: dict | None = None) -> dict:
    if st is None:
        st = subscription_status(d)
    return {
        "id": uid,
        "username": d.get("username"),
        "first_name": d.get("first_name"),
        "role": d.get("role") or "user",
        "referred_by": d.get("referred_by"),
        "created_at": d.get("created_at"),
        "subscription": {
            "ok": st.get("ok"),
            "type": st.get("type") or st.get("plan"),
            "until": st.get("until"),
            "reason": st.get("reason"),
        },
        "counts": {
            "finance": len(d.get("finance") or []),
            "calendar": len(d.get("calendar") or []),
            "tasks": len(d.get("tasks") or []),
            "nutrition": len(d.get("nutrition") or []),
            "notes": len(d.get("notes") or []),
        },
        "payments": d.get("payments") or [],
    }


async def user_detail(uid: int) -> dict | None:
    users = dict(await list_all_users())
    if uid not in users:
        # try load
        try:
            d = await load_user(uid)
        except Exception:
            return None
    else:
        d = users[uid]
    st = subscription_status(d)
    detail = _user_public(uid, d, st)
    detail["finance"] = (d.get("finance") or [])[-30:][::-1]
    detail["calendar"] = (d.get("calendar") or [])[-20:][::-1]
    detail["tasks"] = (d.get("tasks") or [])[-30:][::-1]
    detail["nutrition"] = (d.get("nutrition") or [])[-20:][::-1]
    detail["notes"] = (d.get("notes") or [])[-20:][::-1]
    detail["structure_log"] = (d.get("structure_log") or [])[-15:]
    return detail


async def traffer_stats(code: str) -> dict:
    from .config import TRAFFER_PAY_MONTHLY, TRAFFER_PAY_LIFETIME

    users = []
    earned = 0
    for uid, d in await list_all_users():
        if d.get("referred_by") != code:
            continue
        st = subscription_status(d)
        users.append(_user_public(uid, d, st))
        for p in d.get("payments") or []:
            if p.get("type") == "monthly":
                earned += TRAFFER_PAY_MONTHLY
            elif p.get("type") == "lifetime":
                earned += TRAFFER_PAY_LIFETIME
    trial = sum(1 for u in users if u["subscription"].get("type") == "trial" and u["subscription"].get("ok"))
    monthly = sum(1 for u in users if u["subscription"].get("type") == "monthly" and u["subscription"].get("ok"))
    lifetime = sum(1 for u in users if u["subscription"].get("type") == "lifetime" and u["subscription"].get("ok"))
    return {
        "code": code,
        "total": len(users),
        "trial": trial,
        "monthly": monthly,
        "lifetime": lifetime,
        "earned": earned,
        "users": users,
    }
