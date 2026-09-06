import json
import aiofiles
from pathlib import Path
from datetime import datetime, date, timedelta
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
            "trial_used": False,
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
        data = json.loads(await f.read())
    # migrate missing keys
    base = _default_user()
    for k, v in base.items():
        if k not in data:
            data[k] = v
    if "subscription" not in data:
        data["subscription"] = base["subscription"]
    else:
        for k, v in base["subscription"].items():
            data["subscription"].setdefault(k, v)
    return data


async def save_user(user_id: int, data: dict) -> None:
    path = _user_path(user_id)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=2))


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
    """
    Returns:
      ok: bool
      plan: trial|monthly|lifetime|None
      until: YYYY-MM-DD|None
      reason: no_plan|trial_ended|expired|None
      trial_used: bool
    """
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

    if sub.get("type") == "trial" and sub.get("trial_started"):
        try:
            started = datetime.fromisoformat(sub["trial_started"])
            ends = started + timedelta(days=TRIAL_DAYS)
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
    data["subscription"] = {
        "active": True,
        "type": sub_type,
        "until": until,
        "payment_id": payment_id,
        "trial_started": trial_started or prev.get("trial_started"),
        "trial_used": True if sub_type == "trial" else bool(prev.get("trial_used") or prev.get("trial_started")),
    }
    if sub_type == "trial":
        data["subscription"]["trial_used"] = True
        if not data["subscription"]["trial_started"]:
            data["subscription"]["trial_started"] = trial_started or datetime.utcnow().isoformat()
    await save_user(user_id, data)


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
        {x.get("date") for x in data.get("finance", []) if str(x.get("date", "")).startswith(month)}
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
            "count": len([x for x in data.get("finance", []) if str(x.get("date", "")).startswith(month)]),
        },
        "calendar": {"week_count": week_count, "nearest": nearest, "total": len(meetings)},
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
