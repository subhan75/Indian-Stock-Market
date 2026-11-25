import { recentReports, reportUrl } from "./api.js";
import { initCombobox } from "./combobox.js";
import { labelPill } from "./labels.js";
import { loadingNote } from "./loading.js";

const searchInput = document.getElementById("q");
const combo = initCombobox({
  form: document.getElementById("search-form"),
  input: searchInput,
  list: document.getElementById("suggestions"),
  hint: document.getElementById("hint"),
});

// What you typed lives in the address (?q=abb), so the browser Back button from a report brings the search back.
const startQuery = new URLSearchParams(location.search).get("q");
if (startQuery) combo.run(startQuery);
searchInput.addEventListener("input", () => {
  const q = searchInput.value.trim();
  history.replaceState(null, "", q ? `?q=${encodeURIComponent(q)}` : location.pathname);
});

const recentEl = document.getElementById("recent-list");

function formatDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (d.toDateString() === new Date().toDateString()) return "today";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function note(text) {
  const li = document.createElement("li");
  li.className = "empty";
  li.textContent = text;
  recentEl.replaceChildren(li);
}

async function loadRecent() {
  const loading = loadingNote("Loading your stocks…");
  const row = document.createElement("li");
  row.className = "empty";
  row.append(loading.node);
  recentEl.replaceChildren(row);
  try {
    const rows = await recentReports();
    loading.stop();
    if (!rows.length) return note("Nothing yet. Search for a stock above and its report will show up here.");
    recentEl.replaceChildren();
    for (const r of rows) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = reportUrl(r.symbol, "search");
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
    loading.stop();
    note("Couldn't load earlier reports right now.");
  }
}

loadRecent();
