/**
 * ECHO Planner — Telegram bot
 *
 * Env:
 *   TELEGRAM_BOT_TOKEN       — токен от @BotFather
 *   PAYMENT_PROVIDER_TOKEN   — токен платёжного провайдера (ЮKassa) из BotFather → Payments
 *   MINI_APP_URL             — URL мини-приложения (GitHub Pages / Vercel)
 *   AITUNNEL_KEY             — опционально, AI Tunnel
 *   XAI_API_KEY              — опционально, xAI
 *
 * Start: npm start
 */

import { Bot, InlineKeyboard, InputFile } from "grammy";
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ASSETS = join(__dirname, "assets");
const DATA_DIR = join(__dirname, "data");
const USERS_FILE = join(DATA_DIR, "users.json");

const TOKEN = process.env.TELEGRAM_BOT_TOKEN || "8973557526:AAFy1neG6ZKvXyKwtt0Ek2zElxgPvZpxXG0";
const PAYMENT_TOKEN = process.env.PAYMENT_PROVIDER_TOKEN || "";
const MINI_APP = process.env.MINI_APP_URL || "";
const AITUNNEL = process.env.AITUNNEL_KEY || "sk-aitunnel-A0PIkMCeZbhFW65hWXmis7UF1dIPwt21";
const XAI = process.env.XAI_API_KEY || "";

const TRIAL_DAYS = 5;
const PRICE_PRO = 25000; // копейки → 250 ₽
const PRICE_FOREVER = 299000; // 2 990 ₽

if (!TOKEN) {
  console.error("TELEGRAM_BOT_TOKEN is required");
  process.exit(1);
}

if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });

function loadUsers() {
  try {
    if (existsSync(USERS_FILE)) return JSON.parse(readFileSync(USERS_FILE, "utf8"));
  } catch {}
  return {};
}
function saveUsers(users) {
  writeFileSync(USERS_FILE, JSON.stringify(users, null, 2));
}

function getUser(id) {
  const users = loadUsers();
  const key = String(id);
  if (!users[key]) {
    users[key] = {
      id,
      trialStartedAt: null,
      plan: null,
      planUntil: null,
    };
    saveUsers(users);
  }
  return users[key];
}

function updateUser(id, patch) {
  const users = loadUsers();
  const key = String(id);
  users[key] = { ...getUser(id), ...patch };
  saveUsers(users);
  return users[key];
}

function accessStatus(user) {
  const now = Date.now();
  if (user.plan === "forever") return { ok: true, plan: "forever" };
  if (user.plan === "pro" && user.planUntil && user.planUntil > now) {
    return { ok: true, plan: "pro", until: user.planUntil };
  }
  if (user.plan === "trial" && user.trialStartedAt) {
    const ends = user.trialStartedAt + TRIAL_DAYS * 24 * 60 * 60 * 1000;
    if (now < ends) return { ok: true, plan: "trial", until: ends };
    return { ok: false, reason: "trial_ended" };
  }
  if (!user.trialStartedAt && !user.plan) return { ok: false, reason: "no_plan" };
  return { ok: false, reason: "expired" };
}

const START_TEXT = `ECHO Planner — это голосовой трекер личных данных.

Продукт решает задачу: запись и структурирование информации о расходах, встречах, задачах и приёмах пищи.

Вместо заполнения таблиц, форм или выбора категорий, вы отправляете голосовое или текстовое сообщение в свободной форме. Бот определяет тип записи, извлекает ключевые данные (сумму, дату, время, название) и сохраняет их в соответствующий раздел.

Разделы:
• Финансы — учёт доходов и расходов, остаток по бюджету.
• Календарь — хранение и просмотр встреч и событий.
• Задачи — список дел с отметкой о выполнении.
• Питание — учёт калорий, белков, жиров и углеводов.

Все данные доступны в мини-приложении в виде статистики и списков.`;

const TARIFFS_TEXT =
  "ECHO Planner работает по модели подписки. Это не ограничение, а способ поддерживать развитие продукта и сохранять его независимым.";

const TRIAL_ENDED_TEXT = "❗ БЕСПЛАТНЫЙ ПЕРИОД ОКОНЧЕН";

function startKeyboard() {
  const kb = new InlineKeyboard();
  if (MINI_APP) {
    kb.webApp("ECHO PLANNER 🏳️", MINI_APP).text("ТАРИФЫ", "tariffs");
  } else {
    kb.text("ECHO PLANNER 🏳️", "open_app").text("ТАРИФЫ", "tariffs");
  }
  return kb;
}

function tariffsKeyboard() {
  return new InlineKeyboard()
    .text("БЕСПЛАТНЫЙ ПЕРИОД | 5 дней", "plan_trial")
    .row()
    .text("ОСНОВНАЯ ПОДПИСКА | 250р мес", "plan_pro")
    .row()
    .text("НАВСЕГДА | 2990р", "plan_forever");
}

function expiredKeyboard() {
  return new InlineKeyboard()
    .text("ОСНОВНАЯ ПОДПИСКА | 250р мес", "plan_pro")
    .row()
    .text("НАВСЕГДА | 2990р", "plan_forever");
}

function miniAppKeyboard() {
  if (!MINI_APP) return undefined;
  return new InlineKeyboard().webApp("Открыть ECHO Planner", MINI_APP);
}

async function sendInvoice(ctx, kind) {
  if (!PAYMENT_TOKEN) {
    await ctx.reply(
      "Платежи пока не подключены.\n\nДобавь PAYMENT_PROVIDER_TOKEN (токен ЮKassa из BotFather → Payments) и перезапусти бота.\n\nДля теста тариф активируется кнопкой ниже.",
      {
        reply_markup: new InlineKeyboard().text(
          kind === "pro" ? "Активировать Pro (тест)" : "Активировать Навсегда (тест)",
          kind === "pro" ? "test_activate_pro" : "test_activate_forever",
        ),
      },
    );
    return;
  }

  if (kind === "pro") {
    await ctx.replyWithInvoice(
      "ECHO Planner Pro",
      "Основная подписка на 30 дней. Неограниченные запросы, полная статистика, ARTHUR.",
      `pro_${ctx.from.id}_${Date.now()}`,
      PAYMENT_TOKEN,
      "RUB",
      [{ label: "Подписка Pro · 30 дней", amount: PRICE_PRO }],
    );
  } else if (kind === "forever") {
    await ctx.replyWithInvoice(
      "ECHO Planner Навсегда",
      "Все функции Pro без срока действия. Один платёж.",
      `forever_${ctx.from.id}_${Date.now()}`,
      PAYMENT_TOKEN,
      "RUB",
      [{ label: "Навсегда", amount: PRICE_FOREVER }],
    );
  }
}

const SYSTEM = `Ты — структуратор данных для ECHO Planner. Из текста пользователя определи категорию: finances, calendar, tasks, nutrition, notes.
Извлеки: сумму, дату, время, название, калории и т.д.
Верни СТРОГО JSON:
{
  "reply": "короткий ответ по-братски на русском",
  "entries": [
    {
      "kind": "expense" | "meeting" | "task" | "meal" | "note",
      "title": "строка",
      "amount": 0,
      "category": "cafe|groceries|taxi|sub|shop|rent|health|other",
      "date": "YYYY-MM-DD",
      "time": "HH:mm",
      "calories": 0,
      "body": "строка"
    }
  ]
}
Без markdown. Если не понял — entries: [].`;

function localParse(text) {
  const t = text.toLowerCase();
  const amountMatch = text.replace(/\u00A0/g, " ").match(/(\d[\d\s]{0,8})\s*(?:₽|р(?:уб)?)?/i);
  const amount = amountMatch ? Number(amountMatch[1].replace(/\s/g, "")) : undefined;
  const now = new Date();
  const date = now.toISOString().slice(0, 10);
  const time = now.toTimeString().slice(0, 5);

  if (amount && amount > 0 && /(потрат|купил|заплат|₽|руб)/i.test(t)) {
    const title =
      text
        .replace(/\d[\d\s]*\s*(?:₽|р(?:уб.*)?)?/gi, "")
        .replace(/^(я\s+)?(потратил[аи]?|купил[аи]?)\s*/i, "")
        .trim() || "Расход";
    return { reply: `Записал. ${title} — ${amount} ₽.`, entries: [{ kind: "expense", title, amount, date, time }] };
  }
  if (/(встреч|созвон)/i.test(t)) {
    return { reply: "Поставил в календарь.", entries: [{ kind: "meeting", title: text.slice(0, 80), date, time }] };
  }
  if (/(поел|съел|ккал)/i.test(t)) {
    return {
      reply: "К еде.",
      entries: [{ kind: "meal", title: text.slice(0, 80), date, time, calories: 450 }],
    };
  }
  if (/(надо|задач|не забудь)/i.test(t)) {
    return {
      reply: "В задачи.",
      entries: [{ kind: "task", title: text.replace(/^(надо|не забудь)\s*/i, "").trim() || text }],
    };
  }
  return {
    reply: "Не понял. Примеры: «потратил 430 в кафе», «встреча завтра в 21:00», «поел курицу».",
    entries: [],
  };
}

async function aiStructure(text) {
  const messages = [
    { role: "system", content: SYSTEM },
    { role: "user", content: text },
  ];

  async function call(url, key, model) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
        body: JSON.stringify({ model, messages, stream: false, temperature: 0.2, max_tokens: 600 }),
      });
      if (!res.ok) return null;
      const body = await res.json();
      return body.choices?.[0]?.message?.content ?? null;
    } catch {
      return null;
    }
  }

  let content = null;
  if (XAI) content = await call("https://api.x.ai/v1/chat/completions", XAI, "grok-4.5");
  if (!content && AITUNNEL) {
    content = await call("https://api.aitunnel.ru/v1/chat/completions", AITUNNEL, "deepseek-v4-flash");
  }
  if (!content) return localParse(text);

  try {
    const start = content.indexOf("{");
    const end = content.lastIndexOf("}");
    const json = JSON.parse(content.slice(start, end + 1));
    return {
      reply: typeof json.reply === "string" ? json.reply : "Готово.",
      entries: Array.isArray(json.entries) ? json.entries : [],
    };
  } catch {
    return localParse(text);
  }
}

const bot = new Bot(TOKEN);

bot.command("start", async (ctx) => {
  const photoPath = join(ASSETS, "start.jpg");
  const kb = startKeyboard();

  if (existsSync(photoPath)) {
    await ctx.replyWithPhoto(new InputFile(photoPath), {
      caption: START_TEXT,
      reply_markup: kb,
    });
  } else {
    await ctx.reply(START_TEXT, { reply_markup: kb });
  }
});

bot.command("help", async (ctx) => {
  await ctx.reply(
    "Пиши или голосуй. Я структурирую запись.\n\nОткрой мини-приложение для статистики и разделов.",
    { reply_markup: miniAppKeyboard() },
  );
});

bot.command("tariffs", async (ctx) => {
  const photoPath = join(ASSETS, "tariffs.png");
  if (existsSync(photoPath)) {
    await ctx.replyWithPhoto(new InputFile(photoPath), {
      caption: TARIFFS_TEXT,
      reply_markup: tariffsKeyboard(),
    });
  } else {
    await ctx.reply(TARIFFS_TEXT, { reply_markup: tariffsKeyboard() });
  }
});

bot.callbackQuery("tariffs", async (ctx) => {
  await ctx.answerCallbackQuery();
  try {
    await ctx.deleteMessage();
  } catch {}

  const photoPath = join(ASSETS, "tariffs.png");
  if (existsSync(photoPath)) {
    await ctx.replyWithPhoto(new InputFile(photoPath), {
      caption: TARIFFS_TEXT,
      reply_markup: tariffsKeyboard(),
    });
  } else {
    await ctx.reply(TARIFFS_TEXT, { reply_markup: tariffsKeyboard() });
  }
});

bot.callbackQuery("open_app", async (ctx) => {
  await ctx.answerCallbackQuery({
    text: MINI_APP
      ? "Открой мини-приложение кнопкой"
      : "Задай MINI_APP_URL в env бота",
    show_alert: true,
  });
});

bot.callbackQuery("plan_trial", async (ctx) => {
  await ctx.answerCallbackQuery();
  const user = getUser(ctx.from.id);
  const status = accessStatus(user);

  if (status.ok && status.plan === "trial") {
    const left = Math.ceil((status.until - Date.now()) / (24 * 60 * 60 * 1000));
    await ctx.reply(`Бесплатный период уже активен. Осталось ≈ ${left} дн.`, {
      reply_markup: miniAppKeyboard(),
    });
    return;
  }
  if (user.plan === "pro" || user.plan === "forever") {
    await ctx.reply("У тебя уже оплаченный тариф.", { reply_markup: miniAppKeyboard() });
    return;
  }
  if (user.trialStartedAt && !status.ok) {
    await ctx.reply(TRIAL_ENDED_TEXT, { reply_markup: expiredKeyboard() });
    return;
  }

  updateUser(ctx.from.id, {
    plan: "trial",
    trialStartedAt: Date.now(),
  });

  await ctx.reply(
    `Бесплатный период на ${TRIAL_DAYS} дней активирован.\nМожно пользоваться всеми функциями.`,
    { reply_markup: miniAppKeyboard() },
  );
});

bot.callbackQuery("plan_pro", async (ctx) => {
  await ctx.answerCallbackQuery();
  await sendInvoice(ctx, "pro");
});

bot.callbackQuery("plan_forever", async (ctx) => {
  await ctx.answerCallbackQuery();
  await sendInvoice(ctx, "forever");
});

bot.callbackQuery("test_activate_pro", async (ctx) => {
  await ctx.answerCallbackQuery({ text: "Pro на 30 дней" });
  updateUser(ctx.from.id, {
    plan: "pro",
    planUntil: Date.now() + 30 * 24 * 60 * 60 * 1000,
  });
  await ctx.reply("Подписка Pro активирована на 30 дней.", { reply_markup: miniAppKeyboard() });
});

bot.callbackQuery("test_activate_forever", async (ctx) => {
  await ctx.answerCallbackQuery({ text: "Навсегда" });
  updateUser(ctx.from.id, { plan: "forever", planUntil: null });
  await ctx.reply("Тариф «Навсегда» активирован.", { reply_markup: miniAppKeyboard() });
});

bot.on("pre_checkout_query", async (ctx) => {
  await ctx.answerPreCheckoutQuery(true);
});

bot.on("message:successful_payment", async (ctx) => {
  const sp = ctx.message.successful_payment;
  const payload = sp.invoice_payload || "";
  if (payload.startsWith("pro_")) {
    updateUser(ctx.from.id, {
      plan: "pro",
      planUntil: Date.now() + 30 * 24 * 60 * 60 * 1000,
    });
    await ctx.reply("Оплата прошла. Подписка Pro активна 30 дней.", {
      reply_markup: miniAppKeyboard(),
    });
  } else if (payload.startsWith("forever_")) {
    updateUser(ctx.from.id, { plan: "forever", planUntil: null });
    await ctx.reply("Оплата прошла. Тариф «Навсегда» активирован.", {
      reply_markup: miniAppKeyboard(),
    });
  } else {
    await ctx.reply("Оплата получена. Спасибо!");
  }
});

async function ensureAccess(ctx) {
  const user = getUser(ctx.from.id);
  const status = accessStatus(user);

  if (status.ok) return true;

  if (status.reason === "trial_ended" || status.reason === "expired") {
    await ctx.reply(TRIAL_ENDED_TEXT, { reply_markup: expiredKeyboard() });
    return false;
  }

  await ctx.reply(
    "Чтобы пользоваться ботом, активируй бесплатный период или подписку.",
    { reply_markup: tariffsKeyboard() },
  );
  return false;
}

bot.on("message:text", async (ctx) => {
  const text = ctx.message.text.trim();
  if (text.startsWith("/")) return;

  if (!(await ensureAccess(ctx))) return;

  await ctx.replyWithChatAction("typing");
  const result = await aiStructure(text);
  await ctx.reply(result.reply, { reply_markup: miniAppKeyboard() });
});

bot.on("message:voice", async (ctx) => {
  if (!(await ensureAccess(ctx))) return;
  await ctx.reply(
    "Голос принял. Расшифровка в MVP — в мини-приложении (Артур → микрофон). Или напиши текстом.",
    { reply_markup: miniAppKeyboard() },
  );
});

bot.catch((err) => console.error("Bot error:", err));

bot.start({
  onStart: (info) => console.log(`ECHO Planner bot @${info.username} is running`),
});
