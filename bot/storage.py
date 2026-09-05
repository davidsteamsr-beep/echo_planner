import json
import aiofiles
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Any
from .config import DATA_DIR, TRIAL_DAYS


def _user_path(user_id: int) -> Path:
    return DATA_DIR / f"user_{user_id}.json"


def _default_user() -> dict:
    return {
        "created_at": datetime.utcnow().isoformat(),
        "subscription": {
            "active": False,
            "type": None,  # trial | monthly | lifetime
            "until": None,
            "payment_id": None,
            "trial_started": None,
        },
        "finance": [],
        "calendar": [],
        "tasks": [],
        "nutrition": [],
        "chat_history": [],
    }


async def load_user(user_id: int) -> dict:
    path = _user_path(user_id)
    if not path.exists():
        data = _default_user()
        await save_user(user_id, data)
        return data
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
        return json.loads(content)


async def save_user(user_id: int, data: dict) -> None:
    path = _user_path(user_id)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=2))


async def add_item(user_id: int, section: str, item: dict) -> dict:
    data = await load_user(user_id)
    if section not in data:
        data[section] = []
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


async def get_stats(user_id: int) -> dict:
    data = await load_user(user_id)
    today = date.today().isoformat()
    month = today[:7]

    month_spend = sum(
        x.get("amount", 0) for x in data.get("finance", []) if str(x.get("date", "")).startswith(month)
    )
    days_with = len({x.get("date") for x in data.get("finance", []) if str(x.get("date", "")).startswith(month)}) or 1
    avg_day = month_spend / days_with

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
    cal = sum(n.get("calories", 0) for n in today_meals)
    p = sum(n.get("protein", 0) for n in today_meals)
    f = sum(n.get("fat", 0) for n in today_meals)
    c = sum(n.get("carbs", 0) for n in today_meals)

    return {
        "finance": {
            "month_spend": round(month_spend, 2),
            "avg_day": round(avg_day, 2),
            "count": len([x for x in data.get("finance", []) if str(x.get("date", "")).startswith(month)]),
        },
        "calendar": {"week_count": week_count, "nearest": nearest, "total": len(meetings)},
        "tasks": {"done": done, "total": total, "open": total - done},
        "nutrition": {
            "calories": cal,
            "protein": p,
            "fat": f,
            "carbs": c,
            "meals_today": len(today_meals),
        },
        "subscription": data.get("subscription", {}),
    }


async def set_subscription(
    user_id: int,
    sub_type: str,
    until: str | None = None,
    payment_id: str | None = None,
    trial_started: str | None = None,
):
    data = await load_user(user_id)
    sub = data.get("subscription") or {}
    data["subscription"] = {
        "active": True,
        "type": sub_type,
        "until": until,
        "payment_id": payment_id,
        "trial_started": trial_started or sub.get("trial_started"),
    }
    await save_user(user_id, data)


def subscription_status(data: dict) -> dict:
    """ok / trial_ended / no_plan"""
    sub = data.get("subscription") or {}
    now = datetime.utcnow()

    if sub.get("type") == "lifetime" and sub.get("active"):
        return {"ok": True, "plan": "lifetime"}

    if sub.get("type") == "monthly" and sub.get("active") and sub.get("until"):
        try:
            until = date.fromisoformat(sub["until"])
            if until >= date.today():
                return {"ok": True, "plan": "monthly", "until": sub["until"]}
        except Exception:
            pass

    if sub.get("type") == "trial" and sub.get("trial_started"):
        try:
            started = datetime.fromisoformat(sub["trial_started"])
            ends = started + timedelta(days=TRIAL_DAYS)
            if now < ends:
                return {"ok": True, "plan": "trial", "until": ends.date().isoformat()}
            return {"ok": False, "reason": "trial_ended"}
        except Exception:
            return {"ok": False, "reason": "trial_ended"}

    if sub.get("trial_started") and not sub.get("active"):
        return {"ok": False, "reason": "trial_ended"}

    return {"ok": False, "reason": "no_plan"}
