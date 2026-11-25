import { searchStocks, reportUrl } from "./api.js";

// Accessible stock-search combobox.
// - Search pages: pass `form`; choosing a stock opens its report.
// - Dialogs: pass `onSelect` (and no form); choosing a stock calls it instead of navigating.
export function initCombobox({ form = null, input, list, hint = null, onSelect = null }) {
  let options = [];
  let active = -1;
  let timer = null;
  let latest = 0;

  const setHint = (text, isError = false) => {
    if (!hint) return;
    hint.textContent = text;
    hint.classList.toggle("error", isError);
  };

  function closeList() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }

  function choose(stock) {
    closeList();
    if (onSelect) onSelect(stock);
    else window.location.href = reportUrl(stock.symbol);
  }

  function setActive(i) {
    active = i;
    [...list.children].forEach((li, idx) => li.setAttribute("aria-selected", String(idx === i)));
    if (i >= 0) input.setAttribute("aria-activedescendant", list.children[i].id);
    else input.removeAttribute("aria-activedescendant");
  }

  function renderOptions(items) {
    options = items;
    list.replaceChildren();
    items.forEach((s, i) => {
      const li = document.createElement("li");
      li.id = `${list.id}-opt-${i}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      const name = document.createElement("span");
      name.textContent = s.name;
      const sym = document.createElement("span");
      sym.className = "sym";
      sym.textContent = `NSE: ${s.symbol}`;
      li.append(name, sym);
      li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(s); });
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
    } else if (e.key === "Enter" && active >= 0 && !list.hidden) {
      e.preventDefault(); choose(options[active]);
    } else if (e.key === "Escape" && !list.hidden) {
      e.stopPropagation(); closeList(); // closes the list, not the dialog around it
    }
  });

  input.addEventListener("blur", () => setTimeout(closeList, 100));

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (!q) { setHint("Type a company name or NSE symbol first.", true); return; }
      clearTimeout(timer);
      await lookup(q);
      if (options.length) choose(options[0]);
    });
  }
}
