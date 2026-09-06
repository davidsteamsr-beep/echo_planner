from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, LabeledPrice, PreCheckoutQuery, FSInputFile, ContentType,
)
from aiogram.filters import CommandStart, Command
from datetime import datetime, timedelta, date
import json

from . import storage, ai
from .config import (
    WEBAPP_URL, PRICE_MONTHLY, PRICE_LIFETIME, CURRENCY,
    PAYMENT_PROVIDER_TOKEN, ASSETS_DIR, TRIAL_DAYS,
)
from .storage import subscription_status

router = Router()

START_TEXT = (
    "ECHO Planner — это голосовой трекер личных данных.\n\n"
    "Продукт решает задачу: запись и структурирование информации о расходах, "
    "встречах, задачах и приёмах пищи.\n\n"
    "Вместо заполнения таблиц, форм или выбора категорий, Бот определяет тип записи, извлекает "
    "ключевые данные (сумму, дату, время, название) и сохраняет их в соответствующий раздел.\n\n"
    "Все данные доступны в мини-приложении в виде статистики и списков."
)

TARIFFS_TEXT = (
    "ECHO Planner работает по модели подписки. Это не ограничение, "
    "а способ поддерживать развитие продукта и сохранять его независимым."
)

TRIAL_ENDED_TEXT = "❗ БЕСПЛАТНЫЙ ПЕРИОД ОКОНЧЕН"


def _sub_caption(st: dict) -> str:
    if not st.get("ok"):
        reason = st.get("reason")
        if reason == "trial_ended":
            return "Статус: пробный период закончился"
        if reason == "expired":
            return f"Статус: подписка истекла" + (f" ({st.get('until')})" if st.get("until") else "")
        return "Статус: нет активной подписки"
    plan = st.get("plan") or st.get("type")
    if plan == "lifetime":
        return "Статус: Навсегда ✅"
    if plan == "monthly":
        return f"Статус: Pro ✅ до {st.get('until')}"
    if plan == "trial":
        return f"Статус: пробный период ✅ до {st.get('until')}"
    return "Статус: активна ✅"


def start_kb() -> InlineKeyboardMarkup:
    row = []
    if WEBAPP_URL:
        row.append(InlineKeyboardButton(text="ECHO PLANNER 🏳️", web_app=WebAppInfo(url=WEBAPP_URL)))
    else:
        row.append(InlineKeyboardButton(text="ECHO PLANNER 🏳️", callback_data="open_app"))
    row.append(InlineKeyboardButton(text="ТАРИФЫ", callback_data="tariffs"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def tariffs_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="БЕСПЛАТНЫЙ ПЕРИОД | 5 дней", callback_data="plan_trial")],
        [InlineKeyboardButton(text="ОСНОВНАЯ ПОДПИСКА | 250р мес", callback_data="plan_pro")],
        [InlineKeyboardButton(text="НАВСЕГДА | 2990р", callback_data="plan_forever")],
        [InlineKeyboardButton(text="← ВЕРНУТЬСЯ", callback_data="back_start")],
    ])


def expired_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ОСНОВНАЯ ПОДПИСКА | 250р мес", callback_data="plan_pro")],
        [InlineKeyboardButton(text="НАВСЕГДА | 2990р", callback_data="plan_forever")],
        [InlineKeyboardButton(text="← ВЕРНУТЬСЯ", callback_data="back_start")],
    ])


def app_kb() -> InlineKeyboardMarkup | None:
    if not WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть ECHO Planner", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])


async def send_start_screen(target_message: Message, user_id: int | None = None):
    photo = ASSETS_DIR / "start.jpg"
    uid = user_id or (target_message.from_user.id if target_message.from_user else None)
    caption = START_TEXT
    if uid:
        data = await storage.load_user(uid)
        st = subscription_status(data)
        caption = START_TEXT + "\n\n" + _sub_caption(st)

    if photo.exists():
        await target_message.answer_photo(
            FSInputFile(photo),
            caption=caption,
            reply_markup=start_kb(),
        )
    else:
        await target_message.answer(caption, reply_markup=start_kb())


async def send_tariffs_screen(target_message: Message):
    photo = ASSETS_DIR / "tariffs.png"
    if photo.exists():
        await target_message.answer_photo(
            FSInputFile(photo),
            caption=TARIFFS_TEXT,
            reply_markup=tariffs_kb(),
        )
    else:
        await target_message.answer(TARIFFS_TEXT, reply_markup=tariffs_kb())


@router.message(CommandStart())
async def cmd_start(message: Message):
    await storage.load_user(message.from_user.id)
    # deep link: /start subscribe → сразу тарифы
    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip().lower() if len(parts) > 1 else ""
    if payload in ("subscribe", "tariffs", "pay", "pro"):
        await send_tariffs_screen(message)
        return
    await send_start_screen(message, user_id=message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Пиши или голосуй. Я структурирую запись.\n\n"
        "Примеры:\n"
        "• потратил 430 в кафе\n"
        "• встреча завтра в 21:00\n"
        "• поел курицу с рисом\n"
        "• надо поставить Лосяру",
        reply_markup=app_kb(),
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    stats = await storage.get_stats(message.from_user.id)
    sub = stats["subscription"]
    st_line = _sub_caption(sub)
    text = (
        f"{st_line}\n"
        f"Тип: {sub.get('type') or '—'}\n"
        f"До: {sub.get('until') or ('∞' if sub.get('type') == 'lifetime' else '—')}\n\n"
        f"💰 Месяц: {stats['finance']['month_spend']} ₽\n"
        f"📅 Встреч на неделе: {stats['calendar']['week_count']}\n"
        f"✅ Задач: {stats['tasks']['done']}/{stats['tasks']['total']}\n"
        f"🍽 Сегодня: {stats['nutrition']['calories']} ккал"
    )
    await message.answer(text, reply_markup=start_kb())


@router.message(Command("tariffs"))
async def cmd_tariffs(message: Message):
    await send_tariffs_screen(message)


@router.callback_query(F.data == "tariffs")
async def cb_tariffs(call: CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    await send_tariffs_screen(call.message)


@router.callback_query(F.data == "back_start")
async def cb_back_start(call: CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    await send_start_screen(call.message, user_id=call.from_user.id)


@router.callback_query(F.data == "open_app")
async def cb_open_app(call: CallbackQuery):
    await call.answer("Задай WEBAPP_URL в .env", show_alert=True)


@router.callback_query(F.data == "plan_trial")
async def cb_plan_trial(call: CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    data = await storage.load_user(user_id)
    st = subscription_status(data)

    if st.get("ok") and st.get("plan") == "trial":
        await call.message.answer(
            f"Бесплатный период уже активен. До: {st.get('until')}",
            reply_markup=app_kb(),
        )
        return

    if st.get("ok") and st.get("plan") in ("monthly", "lifetime"):
        await call.message.answer("У тебя уже оплаченный тариф.", reply_markup=app_kb())
        return

    # trial только один раз
    if st.get("trial_used") or data.get("subscription", {}).get("trial_started"):
        await call.message.answer(TRIAL_ENDED_TEXT, reply_markup=expired_kb())
        return

    started = datetime.utcnow().isoformat()
    until = (date.today() + timedelta(days=TRIAL_DAYS)).isoformat()
    await storage.set_subscription(user_id, "trial", until=until, trial_started=started)
    await call.message.answer(
        f"Бесплатный период на {TRIAL_DAYS} дней активирован.\nМожно пользоваться всеми функциями.",
        reply_markup=app_kb(),
    )


@router.callback_query(F.data == "plan_pro")
async def cb_plan_pro(call: CallbackQuery, bot: Bot):
    await call.answer()
    await _send_invoice(call, bot, "monthly")


@router.callback_query(F.data == "plan_forever")
async def cb_plan_forever(call: CallbackQuery, bot: Bot):
    await call.answer()
    await _send_invoice(call, bot, "lifetime")


async def _send_invoice(call: CallbackQuery, bot: Bot, kind: str):
    if not PAYMENT_PROVIDER_TOKEN:
        await call.message.answer(
            "Платежи не подключены.\n"
            "BotFather → Payments → ЮKassa → PAYMENT_PROVIDER_TOKEN в Render env.\n\n"
            "Тест: /activate_test",
        )
        return

    if kind == "monthly":
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="ECHO Planner Pro",
            description="Подписка на 30 дней с момента оплаты.",
            payload=f"monthly_{call.from_user.id}_{int(datetime.utcnow().timestamp())}",
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency=CURRENCY,
            prices=[LabeledPrice(label="Pro · 30 дней", amount=PRICE_MONTHLY)],
        )
    else:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="ECHO Planner Навсегда",
            description="Все функции без срока. Один платёж.",
            payload=f"lifetime_{call.from_user.id}_{int(datetime.utcnow().timestamp())}",
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency=CURRENCY,
            prices=[LabeledPrice(label="Навсегда", amount=PRICE_LIFETIME)],
        )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(query.id, ok=True)


@router.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: Message):
    sp = message.successful_payment
    payload = sp.invoice_payload or ""
    user_id = message.from_user.id

    if payload.startswith("monthly_"):
        until = (date.today() + timedelta(days=30)).isoformat()
        await storage.set_subscription(
            user_id, "monthly", until=until, payment_id=sp.telegram_payment_charge_id
        )
        await message.answer("Оплата прошла. Pro активен 30 дней.", reply_markup=app_kb())
    elif payload.startswith("lifetime_"):
        await storage.set_subscription(
            user_id, "lifetime", until=None, payment_id=sp.telegram_payment_charge_id
        )
        await message.answer("Оплата прошла. Тариф «Навсегда» активирован.", reply_markup=app_kb())
    else:
        await message.answer("Оплата получена. Спасибо!")


@router.message(Command("activate_test"))
async def activate_test(message: Message):
    until = (date.today() + timedelta(days=30)).isoformat()
    await storage.set_subscription(message.from_user.id, "monthly", until=until, payment_id="test")
    await message.answer("✅ Тестовая подписка Pro на 30 дней.", reply_markup=app_kb())


async def ensure_access(message: Message) -> bool:
    data = await storage.load_user(message.from_user.id)
    st = subscription_status(data)
    if st.get("ok"):
        return True
    if st.get("reason") == "trial_ended":
        await message.answer(TRIAL_ENDED_TEXT, reply_markup=expired_kb())
        return False
    if st.get("reason") == "expired":
        await message.answer("Подписка истекла. Оформите новую.", reply_markup=expired_kb())
        return False
    await message.answer(
        "Чтобы пользоваться ботом, активируй бесплатный период или подписку.",
        reply_markup=tariffs_kb(),
    )
    return False


@router.message(F.text | F.voice)
async def handle_note(message: Message, bot: Bot):
    if message.text and message.text.startswith("/"):
        return
    if not await ensure_access(message):
        return

    text = message.text
    if message.voice:
        await message.answer(
            "🎤 Голос — в мини-приложении (Артур → микрофон). Или текстом.",
            reply_markup=app_kb(),
        )
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

    user_id = message.from_user.id
    for item in items:
        if section == "finance":
            item.setdefault("amount", 0)
            item.setdefault("category", "другое")
            item.setdefault("description", text[:80])
            item.setdefault("date", date.today().isoformat())
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
            item.setdefault("date", date.today().isoformat())
        await storage.add_item(user_id, section, item)

    names = {
        "finance": "💰 Финансы",
        "calendar": "📅 Календарь",
        "tasks": "✅ Задачи",
        "nutrition": "🍽 Питание",
    }
    await wait.edit_text(
        f"{reply}\n\n→ {names.get(section, section)} (+{len(items)})",
        reply_markup=app_kb(),
    )


@router.message(F.web_app_data)
async def webapp_data(message: Message):
    try:
        payload = json.loads(message.web_app_data.data)
        if payload.get("action") == "toggle_task":
            ok = await storage.update_task(
                message.from_user.id, payload["task_id"], payload["done"]
            )
            await message.answer("✅ Обновлено" if ok else "Не нашёл задачу")
        else:
            await message.answer("Данные получены")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
