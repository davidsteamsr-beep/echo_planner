# ECHO Planner

Telegram Mini App + бот: личный планировщик (деньги, задачи, встречи, питание, заметки) с AI-ассистентом ARTHUR.

Один процесс FastAPI одновременно:

- отдаёт мини-приложение (`/`);
- отдаёт API (`/api/*`);
- принимает Telegram webhook (`/webhook`);
- запускает бота (aiogram).

```
Telegram ──► /webhook ──► aiogram (bot/handlers.py)
   │                        │
   └─ WebApp ──► index.html │
                    │       ▼
                    └──► /api/* ──► bot/storage.py ──► Postgres / SQLite
                                     bot/ai.py ─────► DeepSeek (AI Tunnel)
```

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # заполнить BOT_TOKEN
uvicorn app:app --host 0.0.0.0 --port 8000
```

Открыть `http://localhost:8000/` — приложение; `http://localhost:8000/health` — healthcheck.

Для локальной разработки бота без публичного URL:

```bash
set BOT_POLLING_MODE=1
python -m bot
```

## Деплой на Render (рекомендуется: один домен)

1. Web Service → Build: `pip install -r requirements.txt`, Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`.
2. Environment: `BOT_TOKEN`, `DATABASE_URL`, `DEEPSEEK_API_KEY`, `WEBAPP_URL`, `WEBHOOK_SECRET`, `OWNER_USERNAME`.
3. `WEBAPP_URL=https://<service>.onrender.com/` — фронтенд и API на одном origin, CORS и хардкод API-хоста больше не нужны.
4. После деплоя: `POST /setup-webhook` (или рестарт — webhook ставится автоматически).
5. **Обязательно `DATABASE_URL` (Postgres/Supabase).** Без него SQLite лежит на эфемерном диске Render и стирается при каждом редеплое вместе с подписками и токенами ярлыков. Для Supabase — см. раздел ниже (Session pooler).

Если фронтенд остаётся на GitHub Pages (`davidsteamsr-beep.github.io/echo_planner/`), `index.html` сам определит внешний API-хост. Переопределение: `?api=https://host` или `window.ECHO_API_BASE`.

## База данных на Supabase

Бэкенд работает на `asyncpg` и понимает строку подключения Supabase, но важно взять **правильный** хост:

Database → **Connect** → **Session pooler** (Session mode, порт `5432`):

```
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Что НЕ брать:

| Вариант Supabase | Почему не подходит |
|---|---|
| **Direct connection** (`db.<ref>.supabase.co:5432`) | Отдаёт IPv6-адрес, а Render работает только по IPv4 → `Network is unreachable` |
| **Transaction pooler** (`...pooler.supabase.com:6543`) | PgBouncer в transaction mode не держит prepared statements. Код определяет порт 6543 и выключает кэш, но для долгоживущего бота сессионный режим стабильнее |
| **Connection string для Prisma/ORM** | Содержит `?pgbouncer=true&connection_limit=1`. asyncpg отправляет эти параметры серверу как настройки и падает — код их отбрасывает, но лучше брать чистую строку |

Что делается автоматически в `bot/storage.py`:

- `postgres://` → `postgresql://` (Render иногда отдаёт старую схему);
- `sslmode=require`, если SSL не указан (Supabase без TLS не пускает);
- percent-encoding пароля — пароли Supabase со спецсимволами (`#`, `?`, `@`, `/`) больше не ломают разбор URL;
- параметры Prisma/psycopg вырезаются;
- для порта `6543` / `pgbouncer=true` включается `statement_cache_size=0`;
- таймауты: коннект 20 с, запрос 60 с;
- таблица `users (user_id BIGINT, data JSONB)` создаётся при первом подключении — вручную ничего создавать не нужно.

Диагностика после деплоя:

```bash
curl https://<host>/api/db-status
# {"backend":"postgres","ok":true,"target":"postgresql://postgres.<ref>:***@...:5432/postgres?...","mode":"session-or-direct"}
```

Если `ok:false` — в ответе будет `error` и `hint` (неверный пароль, проект на паузе, IPv6, TLS). Пароль в ответе и логах маскируется.

Важно про Supabase Free: проект засыпает после ~7 дней без запросов — первый запрос после паузы может занять до минуты или вернуть ошибку подключения. Разбудите проект в дашборде; в логах будет `tenant/user ... not found`.

## Почему приложение «не открывалось» и что исправлено

Симптом: после сплэша пустой чёрный экран с фоном, интерфейс не появляется.

Причины и фиксы:

| Проблема | Было | Стало |
|---|---|---|
| Сплэш скрывался до загрузки данных | `setTimeout(..., 1600)` убирал сплэш, затем до 2×60 с ждал API | Сплэш живёт до завершения загрузки + статус + кнопка «Продолжить без сервера» через 9 с |
| Недоступный API = пустой экран | Любая сетевая ошибка вела к заглушке/пустоте | Offline-first: при недоступном сервере приложение открывается на локальных данных, сверху баннер «Нет связи» и «Повторить» |
| Заглушка подписки при сетевой ошибке | `!ok && !active` → gate | Gate только если сервер **явно** ответил «нет подписки» (401/403) |
| Жёсткий `API_BASE` на Render | Всегда абсолютный URL | Same-origin на своём домене, Render-хост только для GitHub Pages/file:// |
| FastAPI не отдавал фронтенд | `/` возвращал JSON | `/` и `/app` отдают `index.html`, `/public/*`, `/channel.png` |
| Нет таймаутов | 60 с × 2 | 12 с + 10 с, с backoff и кэшем последнего статуса подписки |
| `auth_date` не проверялся | initData можно переиспользовать | Проверка возраста (`INITDATA_MAX_AGE`, по умолчанию 7 дней) + `compare_digest` |
| Внешние скрипты блокировали старт | `telegram-web-app.js` и Google Fonts грузились синхронно | SDK — `async`, boot ждёт его максимум 2.5 с, шрифты — неблокирующе |
| Падение AI на импорте | `AsyncOpenAI()` создавался при импорте и ломался на `httpx` 0.28 (`proxies`) | Ленивый `get_client()` + пин `httpx==0.27.2` |
| Пустой ответ сервера затирал локальные данные | `state = response` | `mergeById`: серверные записи мержатся по `id`, локальные сохраняются |

## Структура

```
app.py              FastAPI: статика, API, webhook, запуск бота
index.html          Мини-приложение (single-file: разметка + CSS + JS)
bot/
  main.py           polling-режим для локальной разработки
  handlers.py       команды, тарифы, платежи, разбор заметок
  storage.py        Postgres/SQLite, пользователи, подписки, партнёры
  ai.py             DeepSeek: структурирование и ARTHUR
  api.py            старый standalone-роутер (не подключён; см. app.py)
  config.py         env и константы
miniapp/            DEPRECATED: ранний прототип, не используется
public/             favicon и бренд-ассеты
```

## Проверка после деплоя

```bash
curl https://<host>/health          # ok
curl https://<host>/api/ping        # {"ok":true}
curl -I https://<host>/             # 200, text/html
curl -I https://<host>/public/favicon.svg
```

Чек-лист, если снова «не открывается»:

1. `/health` отвечает 200?
2. `WEBAPP_URL` открывается в браузере и отдаёт HTML (не JSON)?
3. В консоли Telegram WebView нет `401 invalid_init_data` (значит, `BOT_TOKEN` на сервере совпадает с ботом).
4. `DATABASE_URL` задан (иначе после редеплоя пропадают подписки).
5. Render-сервис не спит: free-план засыпает, первый запрос до ~50 с.

## Переменные окружения

См. `.env.example`. Ключевые: `BOT_TOKEN`, `DATABASE_URL`, `WEBAPP_URL`, `DEEPSEEK_API_KEY`, `PAYMENT_PROVIDER_TOKEN`, `WEBHOOK_SECRET`, `OWNER_USERNAME`.