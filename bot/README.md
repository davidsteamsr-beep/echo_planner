# ECHO Planner Bot (aiogram + FastAPI)

```
bot/
├── main.py          # polling entry
├── handlers.py      # /start, тарифы, платежи, заметки
├── config.py        # env + цены
├── storage.py       # JSON на пользователя
├── ai.py            # DeepSeek структурация + ARTHUR
├── api.py           # FastAPI для мини-приложения
├── requirements.txt
├── .env.example
├── assets/
│   ├── start.jpg
│   └── tariffs.png
└── data/            # создаётся сама
```

## Запуск

```bash
cd echo-planner   # родитель папки bot
python -m venv .venv && source .venv/bin/activate
pip install -r bot/requirements.txt
cp bot/.env.example bot/.env
python -m bot
```

Или из папки bot (если PYTHONPATH=.):

```bash
cd bot
pip install -r requirements.txt
python -m bot
```

## Тексты и кнопки

Всё в `handlers.py`:
- `START_TEXT` — caption /start
- `TARIFFS_TEXT` — экран тарифов
- `start_kb()` / `tariffs_kb()` / `expired_kb()`

## Env

| Ключ | Зачем |
|------|--------|
| BOT_TOKEN | токен бота |
| WEBAPP_URL | URL мини-приложения |
| PAYMENT_PROVIDER_TOKEN | ЮKassa через BotFather Payments |
| DEEPSEEK_API_KEY | AI Tunnel / DeepSeek |
