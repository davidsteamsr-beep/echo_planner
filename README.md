# ECHO Planner

Голосовой трекер финансов, встреч, задач и питания.  
Интерфейс мини-приложения — тёмный iOS-стиль с металлическими акцентами (как в референсе).

## Структура

```
echo-planner/
├── mini-app/
│   └── index.html          # всё мини-приложение (HTML + CSS + JS)
├── bot/
│   ├── index.js            # Telegram-бот (grammy)
│   └── package.json
├── public/
│   ├── echo-mark.jpg       # логотип (3 полоски)
│   ├── echo-wordmark.jpg   # Echo Planner
│   └── reference.png       # UI-референс
└── README.md
```

## Мини-приложение

1. Открой `mini-app/index.html` в браузере — работает сразу.
2. Для GitHub Pages: положи `index.html` в корень репозитория (или в `docs/`) и включи Pages.
3. В Telegram: BotFather → Bot Settings → Menu Button / Web App URL → URL твоего Pages.

**Разделы:** DIGEST · TASKS · NOTES · MONEY · MEETINGS · FOOD · SETTINGS  
**Центр dock** — чат с **ARTHUR** (голос / текст → структурация).

Данные хранятся в `localStorage` браузера / WebView Telegram.

### Тарифы (UI)

| Тариф | Цена |
|--------|------|
| Pro | 250 ₽ / мес |
| Навсегда | 2 490 ₽ |

Платежи в проде — Telegram Payments (ЮKassa / PayMaster). В превью тарифы переключаются в Settings.

## Бот

```bash
cd bot
npm install
export TELEGRAM_BOT_TOKEN="твой_токен"
# опционально:
export AITUNNEL_KEY="sk-aitunnel-..."
export XAI_API_KEY="xai-..."
export MINI_APP_URL="https://username.github.io/echo-planner/"
npm start
```

Бот принимает текст, структурирует через AI (DeepSeek via AI Tunnel или xAI) и отвечает коротко.  
Полная статистика — в мини-приложении.

## Примеры фраз

- «потратил 430 в кафе»
- «встреча завтра в 21:00»
- «поел курицу с рисом»
- «надо поставить Лосяру»
- «сколько я потратил?»

## Деплой

| Часть | Куда |
|--------|------|
| Мини-приложение | GitHub Pages / Vercel / любой static host |
| Бот | Railway, Render, Fly.io, VPS |

Не коммить токены в публичный репозиторий — только env.
