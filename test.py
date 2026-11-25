import os
import json
import urllib.request
import urllib.parse
import urllib.error

API_KEY = os.environ.get("INDIANAPI_KEY", "sk-live-ki0zXf8WtVGULiBeZODC3P1rmoaw409bEW444ROQ")
BASE_URL = "https://stock.indianapi.in"

def fetch_endpoint(path: str, params: dict | None = None) -> dict | list:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={
            "x-api-key": API_KEY,
            "Accept": "application/json",
            "User-Agent": "indianapi-test-script/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} on {path}: {body}") from e

if __name__ == "__main__":
    # 1. Test /stock endpoint (returns full company profile, prices, and financials)
    print("--- Testing /stock (TCS) ---")
    stock = fetch_endpoint("/stock", {"name": "TCS"})
    summary = {
        "company": stock.get("companyName"),
        "industry": stock.get("industry"),
        "nse_price": stock.get("currentPrice", {}).get("NSE"),
        "bse_price": stock.get("currentPrice", {}).get("BSE"),
        "percent_change": stock.get("percentChange"),
        "52w_high": stock.get("yearHigh"),
        "52w_low": stock.get("yearLow"),
        "top_level_keys": list(stock.keys()),
    }
    print(json.dumps(summary, indent=2))

    # 2. Test /trending endpoint (top gainers/losers snapshot)
    print("\n--- Testing /trending ---")
    trending = fetch_endpoint("/trending")
    print(json.dumps(trending, indent=2)[:800] + "\n... (truncated)")