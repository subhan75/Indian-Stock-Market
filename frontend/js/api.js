// Thin wrapper over the backend. Errors always arrive as {error:{code,message}}.
export async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: { Accept: "application/json" } };
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
  if (!res.ok) {
    throw new Error(body?.error?.message || "Something went wrong. Please try again.");
  }
  return body;
}

const enc = encodeURIComponent;

export const searchStocks = (q) => api(`/api/stocks/search?q=${enc(q)}`);
export const recentReports = () => api("/api/reports/recent");
export const getReport = (symbol, refresh = false) =>
  api(`/api/reports/${enc(symbol)}${refresh ? "?refresh=true" : ""}`);
export const reportUrl = (symbol) => `/report.html?symbol=${enc(symbol)}`;

export const getHoldings = () => api("/api/holdings");
export const addHolding = (body) => api("/api/holdings", { method: "POST", body });
export const editHolding = (symbol, body) => api(`/api/holdings/${enc(symbol)}`, { method: "PUT", body });
export const removeHolding = (symbol) => api(`/api/holdings/${enc(symbol)}`, { method: "DELETE" });
export const refreshAll = () => api("/api/refresh-all", { method: "POST" });

export const getMarket = (refresh = false) => api(`/api/market/today${refresh ? "?refresh=true" : ""}`);
