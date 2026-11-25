import { searchStocks, recentReports, reportUrl } from "./api.js";
import { labelPill } from "./labels.js";

const form = document.getElementById("search-form");
const input = document.getElementById("q");
const list = document.getElementById("suggestions");
const hint = document.getElementById("hint");
const recentEl = document.getElementById("recent-list");

let options = [];
let active = -1;
let timer = null;
let latest = 0;

function setHint(text, isError = false) {
  hint.textContent = text;
  hint.classList.toggle("error", isError);
}

function closeList() {
  list.hidden = true;
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("aria-activedescendant");
  active = -1;
}

function setActive(i) {
  active = i;
  [...list.children].forEach((li, idx) => li.setAttribute("aria-selected", String(idx === i)));
  if (i >= 0) input.setAttribute("aria-activedescendant", `opt-${i}`);
  else input.removeAttribute("aria-activedescendant");
}

function go(symbol) {
  window.location.href = reportUrl(symbol);
}

function renderOptions(items) {
  options = items;
  list.replaceChildren();
  items.forEach((s, i) => {
    const li = document.createElement("li");
    li.id = `opt-${i}`;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", "false");
    const name = document.createElement("span");
    name.textContent = s.name;
    const sym = document.createElement("span");
    sym.className = "sym";
    sym.textContent = `NSE: ${s.symbol}`;
    li.append(name, sym);
    li.addEventListener("mousedown", (e) => { e.preventDefault(); go(s.symbol); });
    list.append(li);
  });
  list.hidden = items.length === 0;
  input.setAttribute("aria-expanded", String(items.length > 0));
  active = -1;
}

async function lookup(q) {
  const ticket = ++latest;
  try {
    const items = await searchStocks(q);
    if (ticket !== latest) return; // a newer keystroke won
    renderOptions(items);
    setHint(items.length ? "" : "No NSE stock matches that. Try the company name or its symbol.");
  } catch (err) {
    if (ticket !== latest) return;
    renderOptions([]);
    setHint(err.message, true);
  }
}

input.addEventListener("input", () => {
  clearTimeout(timer);
  const q = input.value.trim();
  if (!q) { latest++; renderOptions([]); setHint(""); return; }
  timer = setTimeout(() => lookup(q), 200);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" && options.length) {
    e.preventDefault(); setActive((active + 1) % options.length);
  } else if (e.key === "ArrowUp" && options.length) {
    e.preventDefault(); setActive((active - 1 + options.length) % options.length);
  } else if (e.key === "Escape") {
    closeList();
  }
});

input.addEventListener("blur", () => setTimeout(closeList, 100));

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (active >= 0) return go(options[active].symbol);
  const q = input.value.trim();
  if (!q) { setHint("Type a company name or NSE symbol first.", true); return; }
  clearTimeout(timer);
  await lookup(q);
  if (options.length) go(options[0].symbol);
});

function formatDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return "today";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

async function loadRecent() {
  try {
    const rows = await recentReports();
    recentEl.replaceChildren();
    if (!rows.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = "Nothing yet. Search for a stock above and its report will show up here.";
      recentEl.append(li);
      return;
    }
    for (const r of rows) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = reportUrl(r.symbol);
      const left = document.createElement("div");
      const name = document.createElement("div");
      name.className = "recent-name";
      name.textContent = r.name;
      const sym = document.createElement("div");
      sym.className = "sym";
      sym.textContent = `NSE: ${r.symbol}`;
      left.append(name, sym);
      const meta = document.createElement("div");
      meta.className = "recent-meta";
      const when = document.createElement("span");
      when.textContent = `Updated ${formatDate(r.generated_at)}`;
      meta.append(labelPill(r.label), when);
      a.append(left, meta);
      li.append(a);
      recentEl.append(li);
    }
  } catch {
    recentEl.replaceChildren();
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Couldn't load earlier reports right now.";
    recentEl.append(li);
  }
}

loadRecent();
