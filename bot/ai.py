from openai import AsyncOpenAI
from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
import json
from datetime import datetime, date

client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
)

STRUCTURE_PROMPT = """Ты — парсер голосовых и текстовых заметок для ECHO Planner.
Пользователь пишет свободным текстом. Твоя задача — извлечь структурированные данные.

Возможные разделы:
1. finance — траты (amount в рублях числом, category, description, date YYYY-MM-DD)
2. calendar — встречи/события (title, datetime ISO, description)
3. tasks — задачи (title, due YYYY-MM-DD или null)
4. nutrition — еда (title, calories, protein, fat, carbs, meal: breakfast/lunch/dinner/snack, date YYYY-MM-DD)

Правила:
- Если дата не указана — используй сегодня: {today}
- Если время не указано для встречи — ставь 12:00
- amount всегда число (без "рублей")
- calories/protein/fat/carbs — числа, если не указаны — оцени примерно или поставь 0
- Отвечай ТОЛЬКО валидным JSON без markdown:
{{
  "section": "finance|calendar|tasks|nutrition|unknown",
  "items": [ {{...}}, ... ],
  "reply": "короткий ответ пользователю на русском"
}}

Если ничего не понял — section = "unknown", items = [], reply = "Не понял, уточни".
"""

ARTHUR_SYSTEM = """Ты — ARTHUR, ассистент ECHO Planner.
Ты имеешь доступ ко всем данным пользователя: траты, задачи, встречи, питание.
Отвечай только на основе этих данных. Не додумывай информацию, если её нет.
Отвечай коротко, по-братски, без лишних слов.
Если данных нет — скажи «Нет записей» или «Не нашёл».
Сегодня: {today}
"""


async def structure_note(text: str) -> dict:
    today = date.today().isoformat()
    messages = [
        {"role": "system", "content": STRUCTURE_PROMPT.format(today=today)},
        {"role": "user", "content": text},
    ]
    try:
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.1,
            max_tokens=800,
        )
        content = resp.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()
        return json.loads(content)
    except Exception as e:
        return {
            "section": "unknown",
            "items": [],
            "reply": f"Ошибка разбора: {str(e)[:80]}",
        }


async def arthur_reply(user_id: int, question: str, user_data: dict) -> str:
    today = date.today().isoformat()
    context = {
        "finance_last": user_data.get("finance", [])[-15:],
        "calendar": user_data.get("calendar", [])[-15:],
        "tasks": user_data.get("tasks", [])[-20:],
        "nutrition_today": [n for n in user_data.get("nutrition", []) if n.get("date") == today],
        "subscription": user_data.get("subscription", {}),
    }
    messages = [
        {"role": "system", "content": ARTHUR_SYSTEM.format(today=today)},
        {
            "role": "system",
            "content": f"Данные пользователя (JSON):\n{json.dumps(context, ensure_ascii=False)}",
        },
        {"role": "user", "content": question},
    ]
    try:
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.4,
            max_tokens=400,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Сбой связи: {str(e)[:60]}"
