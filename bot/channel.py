"""Проверка подписки на канал ECHO Planner."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from .config import CHANNEL_USERNAME, CHANNEL_PROMO_COOLDOWN_H, CHANNEL_PROMO_CHANCE
from . import storage

logger = logging.getLogger("echo.channel")

MEMBER_OK = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.RESTRICTED,  # still in channel
}


async def is_channel_member(bot: Bot, user_id: int, use_cache: bool = True) -> bool:
    """True если пользователь подписан на канал. Бот должен быть админом канала."""
    data = await storage.load_user(user_id)
    if use_cache and data.get("channel_member_at"):
        try:
            at = datetime.fromisoformat(data["channel_member_at"])
            if datetime.utcnow() - at < timedelta(hours=6) and data.get("channel_member_cached") is not None:
                return bool(data["channel_member_cached"])
        except Exception:
            pass

    chat = f"@{CHANNEL_USERNAME}"
    joined = False
    try:
        member = await bot.get_chat_member(chat_id=chat, user_id=user_id)
        status = member.status
        # aiogram 3: status may be enum or str
        st = status.value if hasattr(status, "value") else str(status)
        joined = st in ("member", "administrator", "creator", "restricted") or status in MEMBER_OK
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning("getChatMember failed user=%s: %s", user_id, e)
        joined = False
    except Exception:
        logger.exception("getChatMember error")
        joined = False

    data["channel_member_cached"] = joined
    data["channel_member_at"] = datetime.utcnow().isoformat()
    await storage.save_user(user_id, data)
    return joined


async def should_send_promo(user_id: int) -> bool:
    import random
    data = await storage.load_user(user_id)
    if data.get("channel_member_cached") is True:
        # still respect cache; real check done by caller
        pass
    last = data.get("channel_promo_at")
    if last:
        try:
            if datetime.utcnow() - datetime.fromisoformat(last) < timedelta(hours=CHANNEL_PROMO_COOLDOWN_H):
                return False
        except Exception:
            pass
    return random.random() < CHANNEL_PROMO_CHANCE


async def mark_promo_sent(user_id: int) -> None:
    data = await storage.load_user(user_id)
    data["channel_promo_at"] = datetime.utcnow().isoformat()
    await storage.save_user(user_id, data)
