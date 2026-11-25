// Thin wrapper over the backend. Errors always arrive as {error:{code,message}}.
// A 401 anywhere means "sign in again": the page is sent to the login page and brought back afterwards.

export function loginUrl() {
  const here = location.pathname + location.search;
  return here === "/login.html" ? "/login.html" : `/login.html?next=${encodeURIComponent(here)}`;
}

export async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: { Accept: "application/json" }, credentials: "same-origin" };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error("Couldn't reach the server. Is it running?");
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error page */ }
  if (res.status === 401 && !options.noRedirect) {
    window.location.assign(loginUrl());
    return new Promise(() => {}); // never settles: the page is leaving, so nothing half-renders
  }
  if (!res.ok) {
    const err = new Error(body?.error?.message || "Something went wrong. Please try again.");
    err.status = res.status;
    err.code = body?.error?.code;
    throw err;
  }
  return body;
}

const enc = encodeURIComponent;

// Sign in / out
export const login = (email, password) => api("/api/auth/login", { method: "POST", body: { email, password }, noRedirect: true });
export const logout = () => api("/api/auth/logout", { method: "POST", noRedirect: true });
export const getMe = (options = {}) => api("/api/auth/me", options);

// Search and reports
export const searchStocks = (q) => api(`/api/stocks/search?q=${enc(q)}`);
export const recentReports = () => api("/api/reports/recent");
export const getReport = (symbol, refresh = false) =>
  api(`/api/reports/${enc(symbol)}${refresh ? "?refresh=true" : ""}`);
export const reportUrl = (symbol) => `/report.html?symbol=${enc(symbol)}`;

// My stocks
export const getHoldings = () => api("/api/holdings");
export const addHolding = (body) => api("/api/holdings", { method: "POST", body });
export const editHolding = (symbol, body) => api(`/api/holdings/${enc(symbol)}`, { method: "PUT", body });
export const removeHolding = (symbol) => api(`/api/holdings/${enc(symbol)}`, { method: "DELETE" });
export const refreshAll = () => api("/api/refresh-all", { method: "POST" });
// One stock per request keeps every request short (a proxy may cut off long ones) and lets the page show progress.
export const refreshHolding = (symbol) => api(`/api/holdings/${enc(symbol)}/refresh`, { method: "POST" });

// Market today
export const getMarket = (refresh = false) => api(`/api/market/today${refresh ? "?refresh=true" : ""}`);
