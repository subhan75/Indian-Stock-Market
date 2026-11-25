// Shared by every signed-in page: marks the current page in the nav, checks that you are signed in
// (an API 401 sends you to the login page), and shows who you are with a Log out button.
import { getMe, logout } from "./api.js";
import { busyButton } from "./loading.js";

const here = location.pathname === "/" ? "/index.html" : location.pathname;
document.querySelectorAll(".nav a").forEach((a) => {
  const target = a.getAttribute("href") === "/" ? "/index.html" : a.getAttribute("href");
  if (target === here || (target === "/index.html" && here === "/report.html")) a.setAttribute("aria-current", "page");
});

function userMenu(email) {
  const box = document.createElement("div");
  box.className = "user-menu";
  const who = document.createElement("span");
  who.className = "user-email";
  who.textContent = email;
  who.title = `Signed in as ${email}`;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "link-btn-sm";
  button.textContent = "Log out";
  button.setAttribute("aria-label", `Log out ${email}`);
  button.addEventListener("click", async () => {
    busyButton(button, "Logging out…");
    try { await logout(); } catch { /* the server clears what it can; leaving the page is still right */ }
    window.location.assign("/login.html");
  });
  box.append(who, button);
  return box;
}

const header = document.querySelector(".topbar");
getMe()
  .then((me) => { if (header && me?.user?.email) header.append(userMenu(me.user.email)); })
  .catch(() => { /* a failed check is not "signed out"; the page's own requests will show any real problem */ });

// Tell people when the connection drops, instead of letting requests fail one by one.
const banner = document.createElement("div");
banner.className = "offline-banner";
banner.setAttribute("role", "status");
banner.textContent = "You're offline. Some things won't work until you reconnect.";
banner.hidden = navigator.onLine !== false;
document.body.prepend(banner);
window.addEventListener("offline", () => { banner.hidden = false; });
window.addEventListener("online", () => { banner.hidden = true; });
