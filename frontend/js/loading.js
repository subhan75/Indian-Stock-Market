// One small, accessible loader used wherever something takes time.
// - The spinning icon is decoration (aria-hidden); the words are what screen readers get.
// - With "reduce motion" on, the icon stops spinning but the words stay, so nothing is lost.
import { el } from "./ui.js";

const SPINNER_SVG =
  '<svg viewBox="0 0 24 24" focusable="false"><circle class="spinner-track" cx="12" cy="12" r="9" fill="none" stroke-width="3"/>' +
  '<circle class="spinner-arc" cx="12" cy="12" r="9" fill="none" stroke-width="3" stroke-linecap="round" stroke-dasharray="42 100"/></svg>';

export function spinnerIcon(extraClass = "") {
  const span = el("span", `spinner ${extraClass}`.trim());
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = SPINNER_SVG; // a static string, never server data
  return span;
}

// A status line with a spinner. After `slowAfter` seconds the words change to say it is taking longer, and a
// running seconds counter (visual only, so it isn't read out every second) shows that it is still alive.
export function loadingNote(message, { slowAfter = 8, slowMessage = "This is taking longer than usual. Still working…" } = {}) {
  const node = el("div", "loading-note");
  node.setAttribute("role", "status");
  const text = el("span", "loading-text", message);
  const elapsed = el("span", "loading-elapsed");
  elapsed.setAttribute("aria-hidden", "true");
  node.append(spinnerIcon(), text, elapsed);
  const started = Date.now();
  const timer = setInterval(() => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    elapsed.textContent = seconds >= 3 ? `${seconds} s` : "";
    if (seconds >= slowAfter && text.textContent !== slowMessage) text.textContent = slowMessage;
  }, 1000);
  return { node, stop: () => clearInterval(timer) };
}

// Put a button into its "working" state (spinner + new words, disabled). Returns a function that restores it.
export function busyButton(button, label) {
  const original = [...button.childNodes];
  const wasDisabled = button.disabled;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.replaceChildren(spinnerIcon(), label);
  return () => {
    button.replaceChildren(...original);
    button.disabled = wasDisabled;
    button.removeAttribute("aria-busy");
  };
}
