// Overall label -> colour, icon and words. Shared by every screen.
const ICONS = {
  green: '<path d="M2 6.5l2.5 2.5L10 3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  amber: '<path d="M2.5 6h7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  red: '<path d="M6 2v5M6 9.6v.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  grey: '<circle cx="6" cy="6" r="3.5" fill="none" stroke="currentColor" stroke-width="1.6"/>',
};

const LABELS = {
  looks_solid: { colour: "green", text: "Looks solid" },
  mixed: { colour: "amber", text: "Mixed" },
  be_careful: { colour: "red", text: "Be careful" },
};

export function labelPill(code) {
  const info = LABELS[code] || { colour: "grey", text: "No label" };
  const pill = document.createElement("span");
  pill.className = `pill ${info.colour}`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 12 12");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = ICONS[info.colour]; // static strings only, never user data
  pill.append(svg, info.text);
  return pill;
}
