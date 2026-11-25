import { getMe, login } from "./api.js";

const form = document.getElementById("login-form");
const email = document.getElementById("email");
const password = document.getElementById("password");
const toggle = document.getElementById("toggle-password");
const submit = document.getElementById("submit");
const errorBox = document.getElementById("form-error");

// Only ever go back to a page on this site, never to another address.
function nextPage() {
  const raw = new URLSearchParams(location.search).get("next") || "/";
  try {
    const url = new URL(raw, location.origin);
    const ok = url.origin === location.origin && !url.pathname.startsWith("//") && url.pathname !== "/login.html";
    return ok ? url.pathname + url.search + url.hash : "/";
  } catch {
    return "/";
  }
}

function showError(message, field) {
  errorBox.textContent = message;
  errorBox.hidden = !message;
  [email, password].forEach((input) => {
    if (message) input.setAttribute("aria-describedby", "form-error"); else input.removeAttribute("aria-describedby");
    input.setAttribute("aria-invalid", String(Boolean(message) && (!field || input === field)));
  });
  if (message && field) field.focus();
}

toggle.addEventListener("click", () => {
  const showing = password.type === "text";
  password.type = showing ? "password" : "text";
  toggle.textContent = showing ? "Show" : "Hide";
  toggle.setAttribute("aria-pressed", String(!showing));
  toggle.setAttribute("aria-label", showing ? "Show password" : "Hide password");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submit.disabled) return;
  const emailValue = email.value.trim();
  if (!emailValue) return showError("Enter your email and password.", email);
  if (!password.value) return showError("Enter your email and password.", password);

  showError("");
  submit.disabled = true;
  submit.textContent = "Signing in…";
  try {
    await login(emailValue, password.value);
    window.location.replace(nextPage());
  } catch (err) {
    submit.disabled = false;
    submit.textContent = "Sign in";
    password.value = "";
    showError(err.message, password);
  }
});

// Already signed in? Skip the form.
getMe({ noRedirect: true }).then(() => window.location.replace(nextPage())).catch(() => {});
