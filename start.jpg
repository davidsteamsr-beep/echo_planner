# ECHO Planner — Bot

## Состав папки

```
bot/
├── index.js          ← весь бот (логика, тарифы, AI, платежи)
├── package.json      ← зависимость: grammy
├── .env.example      ← пример переменных
├── assets/
│   ├── start.jpg     ← фото на /start
│   └── tariffs.png   ← фото на ТАРИФЫ
└── data/             ← появится сама после первого запуска (users.json)
```

`node_modules/` появится после `npm install` — в репозиторий её не кладут.

## Запуск

```bash
cd bot
npm install
cp .env.example .env   # поправь значения
# подхватить .env можно через:
export $(grep -v '^#' .env | xargs)
npm start
```

Или на Railway/Render — просто укажи env в панели, Start Command: `npm start`.

## Что делает бот

| Команда / кнопка | Действие |
|---|---|
| `/start` | фото + описание + кнопки ECHO PLANNER / ТАРИФЫ |
| **ECHO PLANNER** | открывает мини-приложение (нужен `MINI_APP_URL`) |
| **ТАРИФЫ** | удаляет сообщение → экран подписки |
| Trial 5 дней | активирует бесплатный период |
| Pro / Навсегда | счёт ЮKassa (нужен `PAYMENT_PROVIDER_TOKEN`) |
| текст / голос | структурация через AI (после активации тарифа) |

Без `PAYMENT_PROVIDER_TOKEN` платежи не уходят — показываются тестовые кнопки активации.
