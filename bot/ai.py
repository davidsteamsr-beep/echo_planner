"""
AI через AI Tunnel → DeepSeek:
  - structure_note: свободный текст → строгий JSON → раскладка по разделам
  - arthur_reply: system + полный снимок данных пользователя
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from openai import AsyncOpenAI

from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

logger = logging.getLogger("echo.ai")

client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY or "missing",
    base_url=DEEPSEEK_BASE_URL,
)

# Дешёвая/быстрая модель на AI Tunnel (при необходимости смени в env)
CHAT_MODEL = "deepseek-chat"


STRUCTURE_PROMPT = """Ты — структуратор данных ECHO Planner.
Пользователь присылает свободный текст (с виджета iPhone или из чата).
Верни СТРОГО один JSON-объект без markdown и без текста снаружи.

Сегодня: {today}
Сейчас: {now}

Формат:
{{
  "reply": "короткая фраза пользователю по-русски, по-братски",
  "entries": [
    {{
      "kind": "note|expense|meeting|task|meal",
      "title": "кратко",
      "body": "своими словами суть (для note обязательно)",
      "amount": 0,
      "category": "cafe|groceries|taxi|sub|shop|rent|health|other",
      "date": "YYYY-MM-DD",
      "time": "HH:mm",
      "datetime": "YYYY-MM-DDTHH:mm:00",
      "due": "YYYY-MM-DD или null",
      "calories": 0,
      "protein": 0,
      "fat": 0,
      "carbs": 0,
      "meal": "breakfast|lunch|dinner|snack",
      "products": "продукты через запятую"
    }}
  ]
}}

kind:
- note — мысль / идея; в body перепиши мысль пользователя красиво и ясно (не копируй дословно хаос, сохрани смысл)
- expense — трата (amount в рублях)
- meeting — встреча / событие
- task — дело
- meal — еда (оцени БЖУ и ккал если не сказали)

date по умолчанию {today}. Для meeting без времени — 12:00.
entries может быть несколько. Если ничего: entries = [].
Только JSON.
"""


ARTHUR_SYSTEM = """Ты — ARTHUR, ассистент ECHO Planner.
Отвечай по-русски, коротко, по-братски.
Только факты из данных ниже. Не выдумывай.
Нет данных — «Нет записей» / «Не нашёл».

Сегодня: {today}

=== ДАННЫЕ ===
{snapshot}
=== КОНЕЦ ===
"""


def _extract_json(content: str) -> dict:
    content = (content or "").strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.lstrip().startswith("json"):
            content = content.lstrip()[4:]
        content = content.strip()
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no json")
    return json.loads(content[start : end + 1])


def _normalize_entry(raw: dict, today: str) -> dict | None:
    kind = str(raw.get("kind") or "").lower().strip()
    alias = {
        "food": "meal",
        "nutrition": "meal",
        "finance": "expense",
        "money": "expense",
        "calendar": "meeting",
        "event": "meeting",
        "todo": "task",
        "tasks": "task",
        "notes": "note",
        "thought": "note",
    }
    kind = alias.get(kind, kind)
    if kind not in ("note", "expense", "meeting", "task", "meal"):
        return None

    title = str(raw.get("title") or raw.get("body") or "Запись")[:120]
    body = str(raw.get("body") or title)
    d = str(raw.get("date") or today)[:10]
    t = str(raw.get("time") or "12:00")[:5]
    out: dict[str, Any] = {"kind": kind, "title": title, "body": body, "date": d}

    if kind == "expense":
        try:
            amount = float(raw.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        out.update(
            amount=amount,
            category=str(raw.get("category") or "other"),
            description=body,
            time=t,
        )
    elif kind == "meeting":
        dt = raw.get("datetime") or f"{d}T{t}:00"
        out.update(datetime=str(dt), description=body, time=t)
    elif kind == "task":
        due = raw.get("due")
        out.update(due=str(due)[:10] if due else None, done=False)
    elif kind == "meal":
        def num(k, default=0.0):
            try:
                v = raw.get(k)
                return float(v if v is not None else default)
            except (TypeError, ValueError):
                return float(default)

        out.update(
            calories=num("calories"),
            protein=num("protein"),
            fat=num("fat"),
            carbs=num("carbs"),
            meal=str(raw.get("meal") or "snack"),
            products=str(raw.get("products") or title),
        )
    return out


def _format_structured_log(user_text: str, entries: list, reply: str) -> str:
    lines = [f"USER: {user_text}", f"REPLY: {reply}"]
    for e in entries:
        k = e.get("kind")
        if k == "note":
            lines.append(f"Note: {e.get('body') or e.get('title')}")
        elif k == "expense":
            lines.append(
                f"Expense: {e.get('title')} | {e.get('amount')} ₽ | {e.get('category')} | {e.get('date')}"
            )
        elif k == "meeting":
            lines.append(f"Meeting: {e.get('title')} | {e.get('datetime')}")
        elif k == "task":
            lines.append(f"Task: {e.get('title')} | due={e.get('due')}")
        elif k == "meal":
            lines.append(
                f"Food: {e.get('products') or e.get('title')} | "
                f"ккал={e.get('calories')} Б={e.get('protein')} Ж={e.get('fat')} У={e.get('carbs')}"
            )
    return "\n".join(lines)


async def structure_note(text: str) -> dict:
    today = date.today().isoformat()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    raw_assistant = ""
    try:
        resp = await client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": STRUCTURE_PROMPT.format(today=today, now=now)},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=900,
        )
        raw_assistant = (resp.choices[0].message.content or "").strip()
        parsed = _extract_json(raw_assistant)
        entries_in = parsed.get("entries") or []
        if not entries_in and parsed.get("section"):
            kind_map = {
                "finance": "expense",
                "calendar": "meeting",
                "tasks": "task",
                "nutrition": "meal",
                "notes": "note",
            }
            section = parsed.get("section")
            entries_in = [
                {**it, "kind": kind_map.get(section, "note")}
                for it in (parsed.get("items") or [])
            ]

        entries = []
        for it in entries_in:
            if isinstance(it, dict):
                n = _normalize_entry(it, today)
                if n:
                    entries.append(n)

        reply = parsed.get("reply") or ("Записал." if entries else "Не понял, уточни.")
        return {
            "reply": str(reply),
            "entries": entries,
            "raw_assistant": raw_assistant,
            "structured_log": _format_structured_log(text, entries, str(reply)),
        }
    except Exception as e:
        logger.exception("structure_note")
        return {
            "reply": f"Не разобрал: {str(e)[:80]}",
            "entries": [],
            "raw_assistant": raw_assistant,
            "structured_log": f"USER: {text}\nERROR: {e}",
        }


def _build_snapshot(user_data: dict) -> str:
    sub = user_data.get("subscription") or {}
    lines = [
        f"subscription: type={sub.get('type')} active={sub.get('active')} until={sub.get('until')}",
        "",
        "— FINANCE —",
    ]
    for x in (user_data.get("finance") or [])[-20:]:
        lines.append(
            f"  {x.get('date')}: {x.get('amount')} ₽ | {x.get('category')} | {x.get('description') or x.get('title')}"
        )
    lines.append("— CALENDAR —")
    for x in (user_data.get("calendar") or [])[-20:]:
        lines.append(f"  {x.get('datetime')}: {x.get('title')}")
    lines.append("— TASKS —")
    for x in (user_data.get("tasks") or [])[-30:]:
        lines.append(f"  {'✓' if x.get('done') else '•'} {x.get('title')} due={x.get('due')}")
    lines.append("— NUTRITION —")
    for x in (user_data.get("nutrition") or [])[-20:]:
        lines.append(
            f"  {x.get('date')} {x.get('meal')}: {x.get('title') or x.get('products')} "
            f"ккал={x.get('calories')} Б={x.get('protein')} Ж={x.get('fat')} У={x.get('carbs')}"
        )
    lines.append("— NOTES / STRUCTURE LOG —")
    for x in (user_data.get("structure_log") or [])[-30:]:
        lines.append(f"  [{x.get('ts', '')}] {x.get('text', '')}")
    lines.append("— CHAT —")
    for x in (user_data.get("chat_history") or [])[-20:]:
        lines.append(f"  {x.get('role')}: {x.get('content')}")
    return "\n".join(lines)


async def arthur_reply(user_id: int, question: str, user_data: dict) -> str:
    today = date.today().isoformat()
    messages = [
        {
            "role": "system",
            "content": ARTHUR_SYSTEM.format(
                today=today, snapshot=_build_snapshot(user_data)
            ),
        },
        {"role": "user", "content": question},
    ]
    try:
        resp = await client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.35,
            max_tokens=500,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception("arthur")
        return f"Сбой связи: {str(e)[:80]}"


KIND_TO_SECTION = {
    "expense": "finance",
    "meeting": "calendar",
    "task": "tasks",
    "meal": "nutrition",
    "note": "notes",
}


def entries_to_storage_items(entries: list[dict]) -> list[tuple[str, dict]]:
    out = []
    for e in entries:
        kind = e.get("kind")
        section = KIND_TO_SECTION.get(kind)
        if not section:
            continue
        if kind == "expense":
            item = {
                "amount": e.get("amount", 0),
                "category": e.get("category", "other"),
                "description": e.get("description") or e.get("title"),
                "title": e.get("title"),
                "date": e.get("date"),
            }
        elif kind == "meeting":
            item = {
                "title": e.get("title"),
                "datetime": e.get("datetime"),
                "description": e.get("description") or "",
            }
        elif kind == "task":
            item = {"title": e.get("title"), "done": False, "due": e.get("due")}
        elif kind == "meal":
            item = {
                "title": e.get("title") or e.get("products"),
                "products": e.get("products"),
                "calories": e.get("calories", 0),
                "protein": e.get("protein", 0),
                "fat": e.get("fat", 0),
                "carbs": e.get("carbs", 0),
                "meal": e.get("meal", "snack"),
                "date": e.get("date"),
            }
        else:
            item = {"title": e.get("title"), "body": e.get("body")}
        out.append((section, item))
    return out
