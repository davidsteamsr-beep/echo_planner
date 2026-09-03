const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor("#0a0a0a");
  tg.setBackgroundColor("#0a0a0a");
}

const state = {
  data: null,
  currentSection: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function initDataHeader() {
  return tg?.initData || "";
}

async function api(path, opts = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": initDataHeader(),
    ...(opts.headers || {}),
  };
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function loadData() {
  try {
    state.data = await api("/api/me");
    renderDashboard();
  } catch (e) {
    console.error(e);
    // fallback empty
    state.data = {
      stats: {
        finance: { month_spend: 0, avg_day: 0, count: 0 },
        calendar: { week_count: 0, nearest: null, total: 0 },
        tasks: { done: 0, total: 0, open: 0 },
        nutrition: { calories: 0, protein: 0, fat: 0, carbs: 0, meals_today: 0 },
        subscription: { active: false },
      },
      finance: [], calendar: [], tasks: [], nutrition: [],
    };
    renderDashboard();
  }
}

function renderDashboard() {
  const s = state.data.stats;
  $("#statFinance").textContent = `${s.finance.month_spend} ₽`;
  $("#statCalendar").textContent = s.calendar.week_count
    ? `${s.calendar.week_count} на неделе`
    : "нет встреч";
  $("#statTasks").textContent = `${s.tasks.done}/${s.tasks.total}`;
  $("#statNutrition").textContent = `${s.nutrition.calories} ккал`;

  const badge = $("#subBadge");
  if (s.subscription?.active) {
    badge.textContent = "PRO";
    badge.classList.add("pro");
  } else {
    badge.textContent = "Free";
    badge.classList.remove("pro");
  }
}

function showScreen(id) {
  $$(".screen").forEach((el) => el.classList.remove("active"));
  $(`#${id}`).classList.add("active");
  $("#arthurBtn").classList.toggle("hidden", id === "chat-screen");
}

function openSection(name) {
  state.currentSection = name;
  const titles = {
    finance: "Финансы",
    calendar: "Календарь",
    tasks: "Задачи",
    nutrition: "Питание",
  };
  $("#sectionTitle").textContent = titles[name];
  renderSection(name);
  showScreen("section-screen");
}

function renderSection(name) {
  const s = state.data.stats[name];
  const list = state.data[name] || [];
  const statsEl = $("#sectionStats");
  const listEl = $("#sectionList");

  // Stats cards
  let statsHtml = "";
  if (name === "finance") {
    statsHtml = `
      <div class="stat-card"><div class="val">${s.month_spend} ₽</div><div class="lbl">за месяц</div></div>
      <div class="stat-card"><div class="val">${s.avg_day} ₽</div><div class="lbl">в день</div></div>
      <div class="stat-card"><div class="val">${s.count}</div><div class="lbl">записей</div></div>
    `;
  } else if (name === "calendar") {
    const nearest = s.nearest ? (s.nearest.title || "Встреча") : "—";
    statsHtml = `
      <div class="stat-card"><div class="val">${s.week_count}</div><div class="lbl">на неделе</div></div>
      <div class="stat-card"><div class="val" style="font-size:14px">${nearest}</div><div class="lbl">ближайшая</div></div>
    `;
  } else if (name === "tasks") {
    statsHtml = `
      <div class="stat-card"><div class="val">${s.done}</div><div class="lbl">сделано</div></div>
      <div class="stat-card"><div class="val">${s.open}</div><div class="lbl">открыто</div></div>
    `;
  } else if (name === "nutrition") {
    statsHtml = `
      <div class="stat-card"><div class="val">${s.calories}</div><div class="lbl">ккал</div></div>
      <div class="stat-card"><div class="val">${s.protein}/${s.fat}/${s.carbs}</div><div class="lbl">Б / Ж / У</div></div>
    `;
  }
  statsEl.innerHTML = statsHtml;

  // List
  if (!list.length) {
    listEl.innerHTML = `<div class="empty">Нет записей</div>`;
    return;
  }

  listEl.innerHTML = list.map((item) => {
    if (name === "finance") {
      return `
        <div class="list-item">
          <div class="main">
            <div class="title">${esc(item.description || item.category || "Трата")}</div>
            <div class="meta">${item.date || ""} · ${item.category || ""}</div>
          </div>
          <div class="amount">−${item.amount} ₽</div>
        </div>`;
    }
    if (name === "calendar") {
      const dt = item.datetime ? item.datetime.replace("T", " ").slice(0, 16) : "";
      return `
        <div class="list-item">
          <div class="main">
            <div class="title">${esc(item.title)}</div>
            <div class="meta">${dt}</div>
          </div>
        </div>`;
    }
    if (name === "tasks") {
      const checked = item.done ? "checked" : "";
      const doneCls = item.done ? "done" : "";
      return `
        <div class="list-item ${doneCls}">
          <div class="checkbox ${checked}" data-id="${item.id}" onclick="toggleTask('${item.id}', ${!item.done})">
            ${item.done ? "✓" : ""}
          </div>
          <div class="main">
            <div class="title">${esc(item.title)}</div>
            <div class="meta">${item.due || ""}</div>
          </div>
        </div>`;
    }
    if (name === "nutrition") {
      return `
        <div class="list-item">
          <div class="main">
            <div class="title">${esc(item.title)}</div>
            <div class="meta">${item.date || ""} · ${item.meal || ""} · ${item.calories || 0} ккал</div>
          </div>
        </div>`;
    }
    return "";
  }).join("");
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

async function toggleTask(id, done) {
  try {
    await api("/api/task/toggle", {
      method: "POST",
      body: JSON.stringify({ task_id: id, done }),
    });
    // локально обновить
    const t = state.data.tasks.find((x) => x.id === id);
    if (t) t.done = done;
    state.data.stats.tasks.done += done ? 1 : -1;
    state.data.stats.tasks.open += done ? -1 : 1;
    renderSection("tasks");
    renderDashboard();
  } catch (e) {
    console.error(e);
  }
}

// Chat
function openChat() {
  showScreen("chat-screen");
  $("#chatInput").focus();
}

async function sendMessage() {
  const input = $("#chatInput");
  const q = input.value.trim();
  if (!q) return;
  input.value = "";

  const box = $("#chatMessages");
  box.innerHTML += `<div class="msg user">${esc(q)}</div>`;
  box.scrollTop = box.scrollHeight;

  try {
    const res = await api("/api/arthur", {
      method: "POST",
      body: JSON.stringify({ question: q }),
    });
    box.innerHTML += `<div class="msg bot">${esc(res.answer)}</div>`;
  } catch (e) {
    box.innerHTML += `<div class="msg bot">Сбой связи</div>`;
  }
  box.scrollTop = box.scrollHeight;
}

// Events
$$(".section-btn").forEach((btn) => {
  btn.addEventListener("click", () => openSection(btn.dataset.section));
});

$("#backBtn").addEventListener("click", () => showScreen("dashboard"));
$("#chatBackBtn").addEventListener("click", () => showScreen("dashboard"));
$("#arthurBtn").addEventListener("click", openChat);
$("#sendBtn").addEventListener("click", sendMessage);
$("#chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

// Start
loadData();
