// Small DOM helpers shared by every page. Server text is only ever set with textContent.
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Links come from scraped pages and RSS feeds, so only http(s) is ever allowed.
export function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

export function externalLink(url, text, className) {
  const href = safeUrl(url);
  if (!href) return el("span", className, text);
  const a = el("a", className, text);
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  const note = el("span", "sr-only", " (opens in a new tab)");
  a.append(note);
  return a;
}

// Links to our own pages. Only the report page is ever linked from a list.
export function reportLink(path, text, className) {
  const ok = typeof path === "string" && /^\/report\.html\?symbol=[A-Za-z0-9&%\-]+(&from=(search|holdings|market))?$/.test(path);
  if (!ok) return el("span", className, text);
  const a = el("a", className, text);
  a.href = path;
  return a;
}

// Tell screen-reader users something has happened without moving their focus. Clearing first means the same
// message is still read out if it is announced twice.
export function announce(message) {
  let region = document.getElementById("announcer");
  if (!region) {
    region = el("div", "sr-only");
    region.id = "announcer";
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    document.body.append(region);
  }
  region.textContent = "";
  setTimeout(() => { region.textContent = message; }, 60);
}

const ARROWS = {
  up: '<path d="M5 1l4 6H1z" fill="currentColor"/>',
  down: '<path d="M5 9L1 3h8z" fill="currentColor"/>',
  flat: '<path d="M1 5h8" stroke="currentColor" stroke-width="2"/>',
};

// Direction is always shown with an icon as well as colour.
export function arrowIcon(direction) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 10 10");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("arrow");
  svg.innerHTML = ARROWS[direction] || ARROWS.flat; // static strings only
  return svg;
}
