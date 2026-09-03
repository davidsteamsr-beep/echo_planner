/**
 * ECHO Planner — Telegram bot
 *
 * Env:
 *   TELEGRAM_BOT_TOKEN  — from @BotFather
 *   AITUNNEL_KEY        — optional, AI Tunnel / DeepSeek
 *   XAI_API_KEY         — optional, xAI Grok
 *   MINI_APP_URL        — https://… GitHub Pages / Vercel URL of mini-app
 *
 * Start: npm start
 * Webhook (production): setWebhook to https://your-host/webhook
 * Polling (dev): default
 */

import { Bot, InlineKeyboard } from "grammy";

const TOKEN = process.env.TELEGRAM_BOT_TOKEN || "8973557526:AAFy1neG6ZKvXyKwtt0Ek2zElxgPvZpxXG0";
const AITUNNEL = process.env.AITUNNEL_KEY || "sk-aitunnel-A0PIkMCeZbhFW65hWXmis7UF1dIPwt21";
const XAI = process.env.XAI_API_KEY || "";
const MINI_APP = process.env.MINI_APP_URL || "";

if (!TOKEN) {
  console.error("TELEGRAM_BOT_TOKEN is required");
  process.exit(1);
}

const bot = new Bot(TOKEN);

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
    return {
      reply: `Записал. ${title} — ${amount} ₽.`,
      entries: [{ kind: "expense", title, amount, date, time }],
    };
  }
  if (/(встреч|созвон)/i.test(t)) {
    return {
      reply: `Поставил в календарь.`,
      entries: [{ kind: "meeting", title: text.slice(0, 80), date, time }],
    };
  }
  if (/(поел|съел|ккал)/i.test(t)) {
    return {
      reply: `К еде.`,
      entries: [{ kind: "meal", title: text.slice(0, 80), date, time, calories: 450 }],
    };
  }
  if (/(надо|задач|не забудь)/i.test(t)) {
    return {
      reply: `В задачи.`,
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
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${key}`,
      },
      body: JSON.stringify({ model, messages, stream: false, temperature: 0.2, max_tokens: 600 }),
    });
    if (!res.ok) return null;
    const body = await res.json();
    return body.choices?.[0]?.message?.content ?? null;
  }

  let content = null;
  if (XAI) {
    content = await call("https://api.x.ai/v1/chat/completions", XAI, "grok-4.5");
  }
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

function miniAppKeyboard() {
  if (!MINI_APP) return undefined;
  return new InlineKeyboard().webApp("Открыть ECHO Planner", MINI_APP);
}

bot.command("start", async (ctx) => {
  await ctx.reply(
    "ECHO Planner.\n\nКидай голос или текст — разложу по полочкам:\n• «потратил 430 в кафе»\n• «встреча завтра в 21:00»\n• «поел курицу с рисом»\n• «надо поставить Лосяру»\n\nПолная картина и Артур — в мини-приложении.",
    { reply_markup: miniAppKeyboard() },
  );
});

bot.command("help", async (ctx) => {
  await ctx.reply("Пиши или голосуй. Я структурирую и отвечу коротко. Открой мини-приложение, чтобы видеть статистику.");
});

bot.on("message:text", async (ctx) => {
  const text = ctx.message.text.trim();
  if (text.startsWith("/")) return;
  await ctx.replyWithChatAction("typing");
  const result = await aiStructure(text);
  let extra = "";
  if (result.entries?.length) {
    extra =
      "\n\nЧтобы это легло в статистику мини-приложения, открой ECHO и скажи Артуру то же самое — данные живут в приложении.";
  }
  await ctx.reply(result.reply + extra, { reply_markup: miniAppKeyboard() });
});

bot.on("message:voice", async (ctx) => {
  await ctx.reply(
    "Голос принял. В MVP расшифровка идёт в мини-приложении (кнопка с логотипом → Артур → микрофон). Или напиши текстом.",
    { reply_markup: miniAppKeyboard() },
  );
});

bot.catch((err) => console.error("Bot error:", err));

bot.start({
  onStart: (info) => console.log(`ECHO Planner bot @${info.username} is running`),
});
