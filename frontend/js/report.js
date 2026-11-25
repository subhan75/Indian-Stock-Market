import { getReport } from "./api.js";
import { initCombobox } from "./combobox.js";
import { labelPill, statusPill } from "./labels.js";
import { loadingNote } from "./loading.js";
import { announce, arrowIcon, el, externalLink } from "./ui.js";

initCombobox({
  form: document.getElementById("search-form"),
  input: document.getElementById("q"),
  list: document.getElementById("suggestions"),
  hint: document.getElementById("hint"),
});

const root = document.getElementById("main");
const params = new URLSearchParams(location.search);
const symbol = (params.get("symbol") || "").trim().toUpperCase();

// "Back" goes to where this report was opened from, and to the same place the browser's own Back button would.
const FROM = { search: ["/", "Search"], holdings: ["/holdings.html", "My stocks"], market: ["/market.html", "Market today"] };

function backLink() {
  const [href, label] = FROM[params.get("from")] || FROM.search;
  const link = el("a", "back-link");
  const arrow = el("span", null, "←");
  arrow.setAttribute("aria-hidden", "true");
  link.href = href;
  link.append(arrow, `Back to ${label}`);
  link.addEventListener("click", (event) => {
    try {
      if (history.length > 1 && document.referrer && new URL(document.referrer).pathname === href) {
        event.preventDefault();
        history.back();                 // restores the page as you left it (scroll position, search text)
      }
    } catch { /* an unreadable referrer: follow the plain link */ }
  });
  return link;
}

// ---------------------------------------------------------------- small DOM helpers
function chip(id, report) {
  const fact = report.facts.find((f) => f.id === id);
  const item = report.news.find((n) => n.id === id);
  const url = fact?.url ?? item?.url;
  const a = externalLink(url, id, "cite");
  a.title = fact ? `${fact.label} (${fact.source})` : item ? `${item.outlet}: ${item.title}` : id;
  if (a.tagName === "A") a.setAttribute("aria-label", `Source ${id}: ${a.title} (opens in a new tab)`);
  return a;
}

// "Sales grew 12% [F1]." -> text with a clickable source chip in place of each [F1]
function citedText(text, report) {
  const frag = document.createDocumentFragment();
  text.split(/(\[[FN]\d+\])/).forEach((part) => {
    const m = part.match(/^\[([FN]\d+)\]$/);
    frag.append(m ? chip(m[1], report) : document.createTextNode(part));
  });
  return frag;
}


// ---------------------------------------------------------------- sections
function renderHeader(r) {
  const head = el("header", "rep-head");
  const left = el("div");
  const h1 = el("h1", null, r.name);
  h1.tabIndex = -1;
  left.append(h1, el("p", "sym", `NSE: ${r.symbol}`));

  const price = el("div", "price");
  price.append(el("div", "price-main", r.price.display));
  const dir = r.price.direction || "flat";
  const change = el("div", `price-change ${dir}`);
  change.append(arrowIcon(dir), r.price.change_display ? `${r.price.change_display} today` : "Today's change unavailable");
  price.append(change, el("div", "asof", r.price.as_of ? `as of ${r.price.as_of}` : ""));
  head.append(left, price);
  return head;
}

function renderOverall(r) {
  const card = el("section", "card overall");
  card.setAttribute("aria-labelledby", "overall-title");
  const top = el("div", "overall-top");
  const title = el("h2", "sr-only", "Overall");
  title.id = "overall-title";
  top.append(title, labelPill(r.label.code));
  card.append(top);
  if (r.ai_text && r.overall.text) {
    const p = el("p", "overall-text");
    p.append(citedText(r.overall.text, r));
    card.append(p);
  } else {
    card.append(el("p", "overall-text", "A written summary isn't available right now. The facts below don't depend on it."));
  }
  card.append(el("p", "muted overall-note", "This label is worked out from the five questions below by fixed rules, not by AI."));
  return card;
}

function renderAbout(r) {
  const card = el("section", "card");
  card.append(el("h2", null, "What the company does"));
  if (r.ai_text && r.about.text) {
    const p = el("p");
    p.append(citedText(r.about.text, r));
    card.append(p);
    return card;
  }
  const desc = r.facts.find((f) => f.label.startsWith("What the company does"));
  if (!desc) return null;
  const p = el("p", null, desc.value_display);
  const src = el("p", "muted");
  src.append("Source: ", externalLink(desc.url, desc.source), ` (${desc.as_of})`);
  card.append(p, src);
  return card;
}

function renderQuestions(r) {
  const card = el("section", "card");
  card.append(el("h2", null, "The five questions"));
  const list = el("ol", "questions");
  for (const q of r.questions) {
    const row = el("li", "q-row");
    const body = el("div");
    body.append(el("h3", "q-title", q.question), el("p", "q-value", q.value_display), el("p", "q-meaning", q.meaning));
    if (q.cites.length) {
      const src = el("div", "q-sources");
      src.append("Sources: ");
      q.cites.forEach((id) => src.append(chip(id, r), " "));
      body.append(src);
    }
    row.append(statusPill(q.status), body);
    list.append(row);
  }
  card.append(list);
  return card;
}

const TONE_WORD = { good: "Positive", bad: "Negative", neutral: "Neutral" };
const TONE_COLOUR = { good: "green", bad: "red", neutral: "grey" };

function renderNews(r) {
  const card = el("section", "card");
  card.append(el("h2", null, "Recent news"));
  if (!r.news.length) {
    card.append(el("p", "muted", "No headlines from trusted outlets in the last 30 days."));
    return card;
  }
  card.append(el("p", "muted", `Top ${r.news.length} from the last 30 days, trusted outlets only.`));
  const list = el("ul", "news-list");
  for (const n of r.news) {
    const li = el("li", "news-item");
    const meta = el("div", "news-meta");
    meta.append(el("strong", null, n.outlet), `· ${n.date_display}`);
    if (r.ai_text || n.summary) {
      const tone = el("span", `pill ${TONE_COLOUR[n.tone] || "grey"}`, TONE_WORD[n.tone] || "Neutral");
      meta.append(tone);
    }
    li.append(meta, externalLink(n.url, n.title, "title"));
    if (n.summary && n.summary !== n.title) li.append(el("p", "news-summary", n.summary));
    list.append(li);
  }
  card.append(list);
  return card;
}

function renderFacts(r) {
  const details = el("details", "card");
  details.append(el("summary", null, "All numbers and where they came from"));
  const table = el("table", "facts");
  const head = el("tr");
  ["Reference", "What", "Value", "As of", "Source"].forEach((h, i) => {
    const th = el("th", i === 0 ? "sr-only-cell" : null, h);
    head.append(th);
  });
  table.append(head);
  for (const f of r.facts) {
    const tr = el("tr");
    const id = el("td", "num"); id.append(chip(f.id, r));
    const value = el("td", f.value_display.length > 18 ? "fact-text" : "num", f.value_display);
    const src = el("td"); src.append(externalLink(f.url, f.source));
    tr.append(id, el("td", null, f.label), value, el("td", null, f.as_of), src);
    table.append(tr);
  }
  const wrap = el("div", "facts-wrap");
  wrap.append(table);
  details.append(wrap);
  return details;
}

function renderFooter(r, onRefresh) {
  const card = el("section", "card");
  card.append(el("h2", null, "Where this came from"));
  const list = el("ul", "sources");
  for (const s of r.sources) {
    const li = el("li");
    li.append(el("strong", null, s.name));
    if (s.ok) {
      li.append(`fetched ${s.fetched_at_display}`);
    } else {
      const bad = el("span", "bad", "couldn't fetch this right now");
      li.append(bad, s.last_ok_display ? `· last worked ${s.last_ok_display}` : "· no earlier fetch on record");
    }
    list.append(li);
  }
  card.append(list);

  const actions = el("div", "foot-actions");
  actions.append(el("p", "muted", r.disclaimer));
  const btn = el("button", "btn-secondary", "Refresh report");
  btn.type = "button";
  btn.addEventListener("click", () => onRefresh(btn));
  actions.append(btn);
  card.append(actions);
  return card;
}

// ---------------------------------------------------------------- states
let stopLoading = () => {};

function showLoading(label) {
  stopLoading();
  root.setAttribute("aria-busy", "true");
  const heading = el("h1", "load-title", symbol ? `Report for ${symbol}` : "Stock report");
  heading.tabIndex = -1;
  const note = loadingNote(label);
  stopLoading = note.stop;
  document.title = `${symbol} report | Stock Analyst`;
  root.replaceChildren(backLink(), heading, note.node, el("div", "skeleton sk-card"), el("div", "skeleton sk-card"),
                       el("div", "skeleton sk-card"));
}

function showError(message) {
  stopLoading();
  root.setAttribute("aria-busy", "false");
  const card = el("section", "card error-card");
  card.append(el("h2", null, "We couldn't open this report"), el("p", null, message));
  const actions = el("div", "actions");
  const retry = el("button", "btn-secondary", "Try again");
  retry.type = "button";
  retry.addEventListener("click", () => load(false));
  const back = el("a", "link-btn", "Search another stock");
  back.href = "/";
  actions.append(retry, back);
  card.append(actions);
  root.replaceChildren(backLink(), card);
}

function showReport(r) {
  stopLoading();
  document.title = `${r.name} (${r.symbol}) | Stock Analyst`;
  const parts = [backLink(), renderHeader(r), renderOverall(r), renderAbout(r), renderQuestions(r), renderNews(r),
                 renderFacts(r), renderFooter(r, (btn) => refresh(btn))].filter(Boolean);
  root.replaceChildren(...parts);
  root.setAttribute("aria-busy", "false");
}

async function load(refreshNow) {
  if (!symbol) return showError("No stock was chosen. Search for a company name or NSE symbol.");
  showLoading(refreshNow
    ? "Fetching fresh numbers and news. This can take up to a minute."
    : "Getting the report. A new one can take up to a minute.");
  try {
    const report = await getReport(symbol, refreshNow);
    showReport(report);
    announce(`${report.name} report is ready.`);
    // After a click on Refresh the button is gone, so put focus on the heading. On a normal page load focus stays at the
    // top of the page, so the first Tab still reaches the skip link.
    if (refreshNow) root.querySelector("h1")?.focus();
  } catch (err) {
    showError(err.message);
    announce(`We couldn't open this report. ${err.message}`);
  }
}

async function refresh(btn) {
  btn.disabled = true;
  btn.textContent = "Refreshing…";
  await load(true);
}

load(false);
