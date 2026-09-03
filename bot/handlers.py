from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, LabeledPrice, PreCheckoutQuery, ContentType
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from datetime import datetime, timedelta
import json

from . import storage, ai
from .config import WEBAPP_URL, PRICE_MONTHLY, PRICE_LIFETIME, CURRENCY

router = Router()


def main_kb(user_id: int | None = None) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text="📱 Открыть ECHO Planner",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
        [
            InlineKeyboardButton(text="💎 Купить Pro (290 ₽/мес)", callback_data="buy_monthly"),
            InlineKeyboardButton(text="♾️ Навсегда (2490 ₽)", callback_data="buy_lifetime"),
        ],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await storage.load_user(message.from_user.id)  # создаём профиль
    text = (
        "👋 *ECHO Planner*\n\n"
        "Говори или пиши что угодно:\n"
        "• «Потратил 430 в кафе»\n"
        "• «Встреча с другом 6 июля в 21:00»\n"
        "• «Поел курицу с рисом»\n"
        "• «Купить молоко»\n\n"
        "Я разложу по разделам: финансы, календарь, задачи, питание.\n\n"
        "Открой мини-приложение ↓"
    )
    await message.answer(text, reply_markup=main_kb(), parse_mode=ParseMode.MARKDOWN)


@router.message(Command("app"))
async def cmd_app(message: Message):
    await message.answer(
        "Открывай ECHO Planner 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📱 Открыть", web_app=WebAppInfo(url=WEBAPP_URL))
        ]])
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    stats = await storage.get_stats(message.from_user.id)
    sub = stats["subscription"]
    status = "✅ Активна" if sub.get("active") else "❌ Нет"
    text = (
        f"*Подписка:* {status}\n"
        f"Тип: {sub.get('type') or '—'}\n"
        f"До: {sub.get('until') or '—'}\n\n"
        f"💰 Месяц: {stats['finance']['month_spend']} ₽\n"
        f"📅 Встреч на неделе: {stats['calendar']['week_count']}\n"
        f"✅ Задач: {stats['tasks']['done']}/{stats['tasks']['total']}\n"
        f"🍽 Сегодня: {stats['nutrition']['calories']} ккал"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb())


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery):
    await call.message.answer(
        "Просто пришли голосовое или текст.\n"
        "Примеры:\n"
        "• Потратил 1200 на такси\n"
        "• Встреча с Машей завтра в 19:00\n"
        "• Сделать отчёт до пятницы\n"
        "• Поел овсянку, 350 ккал\n\n"
        "В мини-приложении — статистика и ARTHUR.",
        reply_markup=main_kb()
    )
    await call.answer()


# ——— Платежи (Telegram Payments + YooKassa provider token нужно указать) ———
# Пока заглушка: отправляем invoice. Для продакшена в BotFather → Payments → подключить ЮKassa

@router.callback_query(F.data == "buy_monthly")
async def buy_monthly(call: CallbackQuery, bot: Bot):
    # Для реальной оплаты нужно provider_token от ЮKassa через BotFather
    await call.message.answer(
        "💎 *Pro на месяц — 290 ₽*\n\n"
        "Чтобы оплата заработала:\n"
        "1. Зайди в @BotFather → Payments\n"
        "2. Подключи ЮKassa / PayMaster\n"
        "3. Получи provider_token и добавь в код.\n\n"
        "Пока для теста могу активировать вручную (напиши /activate_test).",
        parse_mode=ParseMode.MARKDOWN
    )
    await call.answer()


@router.callback_query(F.data == "buy_lifetime")
async def buy_lifetime(call: CallbackQuery):
    await call.message.answer(
        "♾️ *Навсегда — 2490 ₽*\n\n"
        "Подключи платежи в BotFather (ЮKassa), затем вернёмся.",
        parse_mode=ParseMode.MARKDOWN
    )
    await call.answer()


@router.message(Command("activate_test"))
async def activate_test(message: Message):
    """Временная команда для теста подписки"""
    until = (datetime.utcnow() + timedelta(days=30)).date().isoformat()
    await storage.set_subscription(message.from_user.id, "monthly", until=until, payment_id="test")
    await message.answer("✅ Тестовая подписка на 30 дней активирована.")


# ——— Основной обработчик текста и голоса ———

@router.message(F.text | F.voice)
async def handle_note(message: Message, bot: Bot):
    user_id = message.from_user.id
    text = message.text

    if message.voice:
        # Скачиваем голос и отправляем в Whisper через AI Tunnel / OpenAI-compatible
        file = await bot.get_file(message.voice.file_id)
        file_path = file.file_path
        # AI Tunnel может поддерживать audio, но для простоты пока говорим пользователю
        # В продакшене: скачать bytes → отправить в /v1/audio/transcriptions
        await message.answer("🎤 Голос пока в разработке. Напиши текстом, пожалуйста.")
        return

    if not text or len(text.strip()) < 2:
        return

    wait = await message.answer("⏳ Разбираю...")

    result = await ai.structure_note(text)
    section = result.get("section", "unknown")
    items = result.get("items", [])
    reply = result.get("reply", "Готово.")

    if section == "unknown" or not items:
        await wait.edit_text(reply)
        return

    # Сохраняем
    for item in items:
        # нормализация полей
        if section == "finance":
            item.setdefault("amount", 0)
            item.setdefault("category", "другое")
            item.setdefault("description", text[:80])
            item.setdefault("date", datetime.utcnow().date().isoformat())
        elif section == "calendar":
            item.setdefault("title", "Встреча")
            item.setdefault("datetime", datetime.utcnow().isoformat())
            item.setdefault("description", "")
        elif section == "tasks":
            item.setdefault("title", text[:100])
            item.setdefault("done", False)
            item.setdefault("due", None)
        elif section == "nutrition":
            item.setdefault("title", text[:80])
            item.setdefault("calories", 0)
            item.setdefault("protein", 0)
            item.setdefault("fat", 0)
            item.setdefault("carbs", 0)
            item.setdefault("meal", "snack")
            item.setdefault("date", datetime.utcnow().date().isoformat())

        await storage.add_item(user_id, section, item)

    section_names = {
        "finance": "💰 Финансы",
        "calendar": "📅 Календарь",
        "tasks": "✅ Задачи",
        "nutrition": "🍽 Питание",
    }
    await wait.edit_text(
        f"{reply}\n\n→ {section_names.get(section, section)} (+{len(items)})",
        reply_markup=main_kb()
    )


# ——— WebApp data (если мини-приложение шлёт данные) ———

@router.message(F.web_app_data)
async def webapp_data(message: Message):
    try:
        payload = json.loads(message.web_app_data.data)
        action = payload.get("action")
        if action == "toggle_task":
            ok = await storage.update_task(
                message.from_user.id,
                payload["task_id"],
                payload["done"]
            )
            await message.answer("✅ Обновлено" if ok else "Не нашёл задачу")
        else:
            await message.answer("Данные получены")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
