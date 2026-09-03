# ECHO Planner

Голосовой / текстовый трекер всего через Telegram-бота + мини-приложение.

## Что умеет

- Принимает текст (и скоро голос)
- Через DeepSeek (AI Tunnel) раскладывает на: **Финансы / Календарь / Задачи / Питание**
- Мини-приложение в стиле ECHO (чёрный + оранжевый)
- Ассистент **ARTHUR** с доступом к данным пользователя
- Подписка 290 ₽/мес и 2490 ₽ навсегда (через Telegram Payments + ЮKassa)

## Быстрый старт

```bash
cd echo-planner
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Бот запустится в polling, API + мини-приложение на `http://0.0.0.0:8000`.

## Важно для продакшена

1. **WebApp URL**  
   В `.env` укажи реальный HTTPS-адрес (Railway / Vercel / свой сервер):
   ```
   WEBAPP_URL=https://твой-домен.com
   ```
   И в BotFather → Bot Settings → Menu Button / Web App укажи тот же URL.

2. **Платежи**  
   - @BotFather → Payments → подключи **ЮKassa** или PayMaster  
   - Получи `provider_token`  
   - Добавь invoice-отправку в `bot/handlers.py` (сейчас заглушка + `/activate_test`)

3. **Голос**  
   Сейчас текст работает. Для Whisper добавь endpoint `/v1/audio/transcriptions` через AI Tunnel (если поддерживается) или OpenAI.

4. **Webhook (вместо polling)**  
   На сервере с постоянным IP/доменом лучше webhook. Код легко переключается.

## Структура

```
echo-planner/
├── .env
├── requirements.txt
├── run.py
├── bot/
│   ├── config.py
│   ├── storage.py      # JSON-хранилище
│   ├── ai.py           # DeepSeek структура + ARTHUR
│   ├── handlers.py     # aiogram handlers
│   ├── api.py          # FastAPI для мини-приложения
│   └── main.py
├── miniapp/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── data/               # user_*.json
```

## Команды бота

- `/start` — приветствие + кнопка WebApp
- `/app` — открыть мини-приложение
- `/status` — краткая статистика
- `/activate_test` — тестовая подписка на 30 дней

## Дизайн

Чёрный фон `#0a0a0a`, акцент `#ff6b00`, минимализм, круглая кнопка ARTHUR снизу по центру.
