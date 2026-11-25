// Thin wrapper over the backend. Errors always arrive as {error:{code,message}}.
export async function api(path) {
  let res;
  try {
    res = await fetch(path, { headers: { Accept: "application/json" } });
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

export const searchStocks = (q) => api(`/api/stocks/search?q=${encodeURIComponent(q)}`);
export const recentReports = () => api("/api/reports/recent");
export const getReport = (symbol, refresh = false) =>
  api(`/api/reports/${encodeURIComponent(symbol)}${refresh ? "?refresh=true" : ""}`);
export const reportUrl =(symbol) => `/report.html?symbol=${encodeURIComponent(symbol)}`;
