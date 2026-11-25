// Colour + icon + words for labels and statuses. Colour is never the only signal.
const ICONS = {
  green: '<path d="M2 6.5l2.5 2.5L10 3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  amber: '<path d="M2.5 6h7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  red: '<path d="M6 2v5M6 9.6v.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  grey: '<circle cx="6" cy="6" r="3.5" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  eye: '<path d="M1 6s2-3.5 5-3.5S11 6 11 6s-2 3.5-5 3.5S1 6 1 6z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><circle cx="6" cy="6" r="1.4" fill="currentColor"/>',
};

// Overall label (from the backend's label.code)
const LABELS = {
  looks_solid: { colour: "green", text: "Looks solid" },
  mixed: { colour: "amber", text: "Mixed" },
  be_careful: { colour: "red", text: "Be careful" },
};

// Per-question status
const STATUS = {
  green: { colour: "green", text: "Good" },
  amber: { colour: "amber", text: "OK" },
  red: { colour: "red", text: "Poor" },
  grey: { colour: "grey", text: "No data" },
};

function makePill(colour, text, icon = colour) {
  const pill = document.createElement("span");
  pill.className = `pill ${colour}`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 12 12");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = ICONS[icon]; // static strings only, never server data
  pill.append(svg, text);
  return pill;
}

export function labelPill(code) {
  const info = LABELS[code] || { colour: "grey", text: "No label" };
  return makePill(info.colour, info.text);
}

export function statusPill(status) {
  const info = STATUS[status] || STATUS.grey;
  return makePill(info.colour, info.text);
}

// "Look at this": says a stock deserves a look, never what to do about it.
export function flagPill() {
  return makePill("amber", "Look at this", "eye");
}

export function plainPill(text, colour = "grey") {
  return makePill(colour, text, "grey");
}
