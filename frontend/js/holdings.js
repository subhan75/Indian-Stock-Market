import { addHolding, editHolding, getHoldings, refreshHolding, removeHolding } from "./api.js";
import { initCombobox } from "./combobox.js";
import { flagPill, labelPill, plainPill } from "./labels.js";
import { busyButton, loadingNote, spinnerIcon } from "./loading.js";
import { arrowIcon, el, reportLink } from "./ui.js";

const content = document.getElementById("content");
const totalsEl = document.getElementById("totals");
const statusEl = document.getElementById("status");
const addBtn = document.getElementById("add-btn");
const refreshBtn = document.getElementById("refresh-btn");

const dialog = document.getElementById("stock-dialog");
const form = document.getElementById("stock-form");
const stockInput = document.getElementById("stock-input");
const stockHint = document.getElementById("stock-hint");
const watchingBox = document.getElementById("watching");
const ownFields = document.getElementById("own-fields");
const sharesInput = document.getElementById("shares");
const priceInput = document.getElementById("buy-price");
const formError = document.getElementById("form-error");
const formNote = document.getElementById("form-note");
const saveBtn = document.getElementById("save-btn");
const cancelBtn = document.getElementById("cancel-btn");
const dialogTitle = document.getElementById("dialog-title");

let data = null;        // last response from GET /api/holdings
let editing = null;     // the row being edited, or null when adding
let chosen = null;      // symbol picked in the dialog
let busy = false;

// ---------------------------------------------------------------- status line
function setStatus(message, kind = "") {
  statusEl.className = `status ${kind}`.trim();
  statusEl.replaceChildren();
  if (!message) return;
  const line = el("p", kind === "busy" ? "status-busy" : null);
  if (kind === "busy") line.append(spinnerIcon());
  line.append(message);
  statusEl.append(line);
}

// ---------------------------------------------------------------- list
function cell(label, className) {
  const td = el("td", className);
  td.dataset.label = label;
  return td;
}

function moneyCell(text, direction) {
  const span = el("span", `money ${direction || ""}`.trim());
  if (direction) span.append(arrowIcon(direction));
  span.append(text);
  return span;
}

function renderRow(row) {
  const tr = el("tr");

  const stock = cell("Stock", "cell-stock");
  stock.append(reportLink(row.report_url, row.name, "name"), el("span", "sub sym", `NSE: ${row.symbol}`));
  if (row.watching) stock.append(el("div", "watch-tag", "")), stock.lastChild.append(plainPill("Watching"));

  const held = cell("Shares and buy price");
  held.append(row.watching ? el("span", "muted", "Not owned")
    : el("span", "num", `${row.shares} × ${row.buy_price_display}`));

  const value = cell("Value today");
  const valueBox = el("div");
  valueBox.append(el("span", "num", row.value_display ?? "—"));
  const priceNote = row.price_source === "report" ? `${row.price_display} (last report)` : row.price_display;
  valueBox.append(el("span", "sub", row.price_source ? `Price ${priceNote}` : row.price_display));
  value.append(valueBox);

  const gain = cell("Gain or loss");
  if (row.gain_display) gain.append(moneyCell(row.gain_display, row.direction));
  else gain.append(el("span", "muted", "—"));

  const label = cell("Label");
  const labelBox = el("div");
  labelBox.append(row.label ? labelPill(row.label.code) : plainPill("No report yet"));
  if (row.report_updated_display) labelBox.append(el("span", "sub", `Report updated ${row.report_updated_display}`));
  label.append(labelBox);

  const look = cell("Look at this");
  if (row.flag.on) {
    const box = el("div");
    box.append(flagPill());
    const list = el("ul", "reasons");
    row.flag.reasons.forEach((r) => list.append(el("li", null, r.text)));
    box.append(list);
    look.append(box);
  } else {
    look.append(el("span", "muted", "—"));
    look.lastChild.append(el("span", "sr-only", "No flag"));
  }

  const actions = cell("", "cell-actions");
  const box = el("div", "row-actions");
  const edit = el("button", "link-btn-sm", "Edit");
  edit.type = "button";
  edit.setAttribute("aria-label", `Edit ${row.name}`);
  edit.addEventListener("click", () => openDialog(row));
  const remove = el("button", "link-btn-sm danger", "Remove");
  remove.type = "button";
  remove.setAttribute("aria-label", `Remove ${row.name}`);
  remove.addEventListener("click", () => removeRow(row));
  box.append(edit, remove);
  actions.append(box);

  tr.append(stock, held, value, gain, label, look, actions);
  return tr;
}

function renderTotals(t) {
  totalsEl.replaceChildren();
  const make = (k, v, direction) => {
    const box = el("div", "total");
    box.append(el("div", "k", k));
    const val = el("div", "v");
    val.append(direction ? moneyCell(v, direction) : v);
    box.append(val);
    return box;
  };
  totalsEl.append(make("Total invested", t.invested_display), make("Value today", t.value_display),
                  make("Total gain or loss", t.gain_display, t.direction));
  if (t.note) totalsEl.append(el("p", "note", t.note));
  totalsEl.hidden = false;
}

function renderEmpty() {
  totalsEl.hidden = true;
  const card = el("section", "empty-card");
  card.append(el("h2", null, "No stocks yet"), el("p", null, "Add one to get started. You can also add a stock you only want to watch."));
  const btn = el("button", "btn", "Add a stock");
  btn.type = "button";
  btn.addEventListener("click", () => openDialog(null));
  card.append(btn);
  content.replaceChildren(card);
}

function renderList() {
  if (!data.rows.length) return renderEmpty();
  renderTotals(data.totals);
  const table = el("table", "holdings");
  const head = el("tr");
  ["Stock", "Shares and buy price", "Value today", "Gain or loss", "Label", "Look at this", ""].forEach((h) => {
    const th = el("th", null, h);
    th.scope = "col";
    if (!h) th.append(el("span", "sr-only", "Actions"));
    head.append(th);
  });
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  data.rows.forEach((r) => tbody.append(renderRow(r)));
  table.append(thead, tbody);
  const wrap = el("div", "table-wrap");
  wrap.append(table);
  content.replaceChildren(wrap, el("p", "muted", `Prices as of ${data.as_of}.`));
  content.lastChild.style.fontSize = "13px";
}

let stopLoading = () => {};

function renderLoading() {
  stopLoading();
  totalsEl.hidden = true;
  const note = loadingNote("Loading your stocks…");
  stopLoading = note.stop;
  content.replaceChildren(note.node, el("div", "skeleton sk-row"), el("div", "skeleton sk-row"), el("div", "skeleton sk-row"));
}

function renderError(message) {
  totalsEl.hidden = true;
  const card = el("section", "error-card");
  card.append(el("h2", null, "We couldn't load your stocks"), el("p", null, message));
  const actions = el("div", "actions");
  const retry = el("button", "btn-secondary", "Try again");
  retry.type = "button";
  retry.addEventListener("click", () => load(true));
  actions.append(retry);
  card.append(actions);
  content.replaceChildren(card);
}

async function load(showSkeleton) {
  content.setAttribute("aria-busy", "true");
  if (showSkeleton) renderLoading();
  try {
    data = await getHoldings();
    stopLoading();
    renderList();
  } catch (err) {
    stopLoading();
    renderError(err.message);
  } finally {
    content.setAttribute("aria-busy", "false");
  }
}

// ---------------------------------------------------------------- confirm dialog
const confirmDlg = document.getElementById("confirm-dialog");
const confirmText = document.getElementById("confirm-text");
const confirmYes = document.getElementById("confirm-yes");
const confirmNo = document.getElementById("confirm-no");

function confirmAction(message, yesLabel) {
  return new Promise((resolve) => {
    confirmText.textContent = message;
    confirmYes.textContent = yesLabel;
    const done = (answer) => {
      confirmYes.removeEventListener("click", onYes);
      confirmNo.removeEventListener("click", onNo);
      confirmDlg.removeEventListener("close", onNo);
      if (confirmDlg.open) confirmDlg.close();
      resolve(answer);
    };
    const onYes = () => done(true);
    const onNo = () => done(false);
    confirmYes.addEventListener("click", onYes);
    confirmNo.addEventListener("click", onNo);
    confirmDlg.addEventListener("close", onNo);
    confirmDlg.showModal();
    confirmNo.focus();
  });
}

async function removeRow(row) {
  const ok = await confirmAction(`Remove ${row.name} from My stocks? Its saved reports are kept.`, "Remove");
  if (!ok) return;
  setStatus(`Removing ${row.name}…`, "busy");
  try {
    await removeHolding(row.symbol);
    setStatus(`Removed ${row.name}.`);
    await load(false);
  } catch (err) {
    setStatus(err.message, "error");
  }
}

// ---------------------------------------------------------------- add / edit dialog
function showFormError(message) {
  formError.textContent = message;
  formError.hidden = !message;
}

function syncOwnFields() {
  ownFields.hidden = watchingBox.checked;
}

function openDialog(row) {
  editing = row;
  chosen = row ? row.symbol : null;
  dialogTitle.textContent = row ? `Edit ${row.name}` : "Add a stock";
  stockInput.value = row ? `${row.name} (${row.symbol})` : "";
  stockInput.readOnly = Boolean(row);
  stockHint.textContent = row ? "The stock can't be changed. Remove it and add another instead." : "Search, then pick a stock from the list.";
  stockHint.classList.remove("error");
  watchingBox.checked = row ? row.watching : false;
  sharesInput.value = row && !row.watching ? String(row.shares) : "";
  priceInput.value = row && !row.watching ? String(row.buy_price) : "";
  formNote.hidden = Boolean(row);
  showFormError("");
  syncOwnFields();
  dialog.showModal();
  (row ? sharesInput : stockInput).focus();
}

function readForm() {
  if (!chosen) return { error: "Choose a stock from the suggestions." };
  if (watchingBox.checked) return { body: { symbol: chosen, watching: true } };
  const sharesText = sharesInput.value.trim();
  if (!/^\d+$/.test(sharesText) || Number(sharesText) < 1) {
    return { error: "Enter the number of shares as a whole number, 1 or more." };
  }
  const price = Number(priceInput.value);
  if (!priceInput.value.trim() || !Number.isFinite(price) || price <= 0) {
    return { error: "Enter your average buy price in rupees, more than 0." };
  }
  return { body: { symbol: chosen, watching: false, shares: Number(sharesText), buy_price: price } };
}

initCombobox({
  input: stockInput,
  list: document.getElementById("stock-suggestions"),
  hint: stockHint,
  onSelect: (stock) => {
    chosen = stock.symbol;
    stockInput.value = `${stock.name} (${stock.symbol})`;
    stockHint.textContent = `Selected ${stock.symbol}.`;
    stockHint.classList.remove("error");
    showFormError("");
  },
});
// typing again after choosing means the choice no longer applies
stockInput.addEventListener("input", () => { if (!editing) chosen = null; });
watchingBox.addEventListener("change", syncOwnFields);
cancelBtn.addEventListener("click", () => dialog.close());

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (saveBtn.disabled) return;
  const { body, error } = readForm();
  if (error) return showFormError(error);

  if (editing && !editing.watching && body.watching) {
    const ok = await confirmAction(`This clears your shares and buy price for ${editing.name}. Continue?`, "Continue");
    if (!ok) return;
  }

  showFormError("");
  const restoreSave = busyButton(saveBtn, "Saving…");
  try {
    const saved = editing ? await editHolding(editing.symbol, body) : await addHolding(body);
    dialog.close();
    setStatus(`Saved ${saved.name}.`);
    await load(false);
  } catch (err) {
    showFormError(err.message);
  } finally {
    restoreSave();
  }
});

// ---------------------------------------------------------------- refresh all
function summary(result) {
  statusEl.className = "status";
  statusEl.replaceChildren();
  const n = result.refreshed.length;
  statusEl.append(el("p", null, n === 0 ? "No stocks were refreshed." : `Refreshed ${n} ${n === 1 ? "stock" : "stocks"}.`));
  if (result.failed.length) {
    statusEl.append(el("p", null, `${result.failed.length} couldn't be refreshed:`));
    const list = el("ul");
    result.failed.forEach((f) => list.append(el("li", null, `${f.symbol}: ${f.reason}`)));
    statusEl.append(list);
  }
  const flags = result.new_flags;
  statusEl.append(el("p", null, flags.length
    ? `${flags.length} new ${flags.length === 1 ? "flag" : "flags"}: ${flags.join(", ")}.`
    : "No new flags."));
}

let restoreRefresh = null;

function setBusy(on) {
  busy = on;
  addBtn.disabled = on;
  if (on) {
    restoreRefresh = busyButton(refreshBtn, "Refreshing…");
  } else if (restoreRefresh) {
    restoreRefresh();
    restoreRefresh = null;
  }
}

refreshBtn.addEventListener("click", async () => {
  if (busy) return;
  const rows = data?.rows ?? [];
  if (!rows.length) return setStatus("There are no stocks to refresh yet.");
  setBusy(true);
  const result = { refreshed: [], failed: [], new_flags: [] };
  for (const [i, row] of rows.entries()) {
    setStatus(`Refreshing ${i + 1} of ${rows.length}: ${row.symbol}. This takes about 5 seconds per stock.`, "busy");
    try {
      const r = await refreshHolding(row.symbol);
      if (r.refreshed) {
        result.refreshed.push(r.symbol);
        if (r.new_flag) result.new_flags.push(r.symbol);
      } else {
        result.failed.push({ symbol: r.symbol, reason: r.failed.reason });
      }
    } catch (err) {
      result.failed.push({ symbol: row.symbol, reason: err.message });   // one stock failing never stops the rest
    }
  }
  summary(result);
  setBusy(false);
  await load(false);
});

addBtn.addEventListener("click", () => openDialog(null));

load(true);
