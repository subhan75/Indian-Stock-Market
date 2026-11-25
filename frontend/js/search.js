import { recentReports, reportUrl } from "./api.js";
import { initCombobox } from "./combobox.js";
import { labelPill } from "./labels.js";

initCombobox({
  form: document.getElementById("search-form"),
  input: document.getElementById("q"),
  list: document.getElementById("suggestions"),
  hint: document.getElementById("hint"),
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
  try {
    const rows = await recentReports();
    if (!rows.length) return note("Nothing yet. Search for a stock above and its report will show up here.");
    recentEl.replaceChildren();
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
    note("Couldn't load earlier reports right now.");
  }
}

loadRecent();
