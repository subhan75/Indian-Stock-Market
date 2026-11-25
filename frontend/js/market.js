import { getMarket } from "./api.js";
import { labelPill, plainPill } from "./labels.js";
import { loadingNote } from "./loading.js";
import { announce, arrowIcon, el, externalLink, reportLink } from "./ui.js";

const root = document.getElementById("main");

// "Shares rose [H2]." -> text with a clickable chip (linking to that headline) in place of each [H2]
function citedText(text, headlines) {
  const frag = document.createDocumentFragment();
  text.split(/(\[H\d+\])/).forEach((part) => {
    const m = part.match(/^\[(H\d+)\]$/);
    if (!m) return frag.append(document.createTextNode(part));
    const h = headlines.find((x) => x.id === m[1]);
    const chip = externalLink(h?.url, m[1], "cite");
    if (h) {
      chip.title = `${h.outlet}: ${h.title}`;
      if (chip.tagName === "A") chip.setAttribute("aria-label", `Headline ${m[1]}: ${h.title}`);
    }
    frag.append(chip);
  });
  return frag;
}

function card(title, ...children) {
  const section = el("section", "card");
  section.append(el("h2", null, title), ...children);
  return section;
}

function sourceOk(m, name) {
  return m.sources.find((s) => s.name === name)?.ok ?? false;
}

// ---------------------------------------------------------------- blocks
function renderHead(m) {
  const head = el("div", "m-head");
  const left = el("div");
  const h1 = el("h1", null, "Market today");
  h1.tabIndex = -1;
  left.append(h1, el("p", null, `As of ${m.as_of}`));
  const btn = el("button", "btn-secondary", "Refresh");
  btn.type = "button";
  btn.addEventListener("click", () => load(true));
  head.append(left, btn);
  return head;
}

function renderIndices(m) {
  const body = [];
  if (m.indices.length) {
    const grid = el("div", "indices");
    for (const i of m.indices) {
      const box = el("div", "index-card");
      box.append(el("div", "k", i.name), el("div", "level", i.value_display));
      const chg = el("div", `chg ${i.direction}`);
      chg.append(arrowIcon(i.direction), i.change_display ? `${i.change_display} vs previous close` : "Change unavailable");
      box.append(chg);
      const src = el("div", "src");
      src.append("Source: ", externalLink(i.url, i.source));
      box.append(src);
      grid.append(box);
    }
    body.push(grid);
  }
  if (!m.indices.length) {
    body.push(el("p", "empty-note", "Couldn't fetch the index levels right now."));
  } else if (m.indices.length < 2) {
    body.push(el("p", "note", "One index couldn't be fetched right now."));
  } else {
    body.push(el("p", "note", "After the market closes, and at weekends, this shows the last session."));
  }
  return card("Market move", ...body);
}

function renderPoints(m) {
  if (m.ai_text && m.points.length) {
    const list = el("ul", "points");
    for (const p of m.points) {
      const li = el("li");
      li.append(citedText(p.text, m.headlines));
      list.append(li);
    }
    return card("What happened today", list,
      el("p", "note", "Written from the headlines below by AI. Each [H#] opens the headline it comes from."));
  }
  const why = m.headlines.length
    ? "A written summary isn't available right now. The headlines below are unaffected."
    : "There are no headlines to summarise right now.";
  return card("What happened today", el("p", "empty-note", why));
}

function renderHeadlines(m) {
  if (!m.headlines.length) {
    const down = !sourceOk(m, "ET Markets") && !sourceOk(m, "Business Standard");
    return card("Top headlines", el("p", "empty-note",
      down ? "Couldn't fetch market headlines right now." : "No market headlines in the last 24 hours."));
  }
  const list = el("ol", "hl-list");
  for (const h of m.headlines) {
    const li = el("li", "hl");
    const body = el("div");
    body.append(el("div", "meta", `${h.outlet} · ${h.time_display}`), externalLink(h.url, h.title, "title"));
    li.append(el("span", "id", h.id), body);
    list.append(li);
  }
  return card("Top headlines", list);
}

function renderYourStocks(m) {
  if (!m.your_stocks_in_news.length) {
    const p = el("p", "empty-note");
    const link = el("a", null, "My stocks");
    link.href = "/holdings.html";
    p.append("None of your stocks are in today's headlines. Add or review them in ", link, ".");
    return card("Your stocks in the news", p);
  }
  const wrap = el("div");
  for (const r of m.your_stocks_in_news) {
    const row = el("div", "stock-row");
    const left = el("div", "name");
    left.append(reportLink(`${r.report_url}&from=market`, r.name), el("span", "sym", `NSE: ${r.symbol}`));
    const what = el("div", "what");
    what.append(el("span", "meta", `${r.outlet} · ${r.time_display}${r.headline_id ? ` · ${r.headline_id}` : ""}`),
                externalLink(r.url, r.title, "title"));
    row.append(left, what);
    wrap.append(row);
  }
  return card("Your stocks in the news", wrap);
}

function renderWatching(m) {
  if (!m.watching.length) {
    return card("Watching", el("p", "empty-note", "Stocks you mark as watching in My stocks appear here."));
  }
  const wrap = el("div");
  for (const w of m.watching) {
    const row = el("div", "stock-row");
    const left = el("div", "name");
    left.append(reportLink(`${w.report_url}&from=market`, w.name), el("span", "sym", `NSE: ${w.symbol}`));
    const right = el("div", "what");
    right.append(w.label ? labelPill(w.label.code) : plainPill("No report yet"));
    row.append(left, right);
    wrap.append(row);
  }
  return card("Watching", wrap);
}

function renderSources(m) {
  const section = el("section", "card");
  section.append(el("h2", null, "Where this came from"));
  const list = el("ul", "sources");
  for (const s of m.sources) {
    const li = el("li");
    li.append(el("strong", null, s.name));
    if (s.ok) {
      li.append(`fetched ${s.fetched_at_display}`);
    } else {
      li.append(el("span", "bad", "couldn't fetch this right now"),
        s.last_ok_display ? `· last worked ${s.last_ok_display}` : "· no earlier fetch on record");
    }
    list.append(li);
  }
  section.append(list, el("p", "muted", m.disclaimer));
  return section;
}

// ---------------------------------------------------------------- states
let stopLoading = () => {};

function showLoading() {
  stopLoading();
  root.setAttribute("aria-busy", "true");
  const heading = el("h1", "load-title", "Market today");
  heading.tabIndex = -1;
  const note = loadingNote("Getting today's market. This can take a few seconds.");
  stopLoading = note.stop;
  root.replaceChildren(heading, note.node, el("div", "skeleton sk-card"), el("div", "skeleton sk-card"),
                       el("div", "skeleton sk-card"));
}

function showError(message) {
  stopLoading();
  root.setAttribute("aria-busy", "false");
  const section = el("section", "card error-card");
  section.append(el("h2", null, "We couldn't load the market page"), el("p", null, message));
  const actions = el("div", "actions");
  const retry = el("button", "btn-secondary", "Try again");
  retry.type = "button";
  retry.addEventListener("click", () => load(false));
  actions.append(retry);
  section.append(actions);
  root.replaceChildren(section);
}

async function load(refresh) {
  showLoading();
  try {
    const m = await getMarket(refresh);
    stopLoading();
    root.replaceChildren(renderHead(m), renderIndices(m), renderPoints(m), renderHeadlines(m),
                         renderYourStocks(m), renderWatching(m), renderSources(m));
    root.setAttribute("aria-busy", "false");
    announce("Market today is ready.");
    if (refresh) root.querySelector("h1")?.focus();   // the Refresh button is gone; a normal load keeps focus at the top
  } catch (err) {
    showError(err.message);
    announce(`We couldn't load the market page. ${err.message}`);
  }
}

load(false);
