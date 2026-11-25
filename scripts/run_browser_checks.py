"""Run the browser checks, each against a FRESH fake-Supabase server (so no check depends on another's data).

    python scripts/run_browser_checks.py                 # all of them (about 10 to 15 minutes; they use real data sources)
    python scripts/run_browser_checks.py mobile a11y     # just these

Checks: login, loaders, mobile, a11y, axe, csp. Needs `pip install -r requirements-dev.txt axe-playwright-python` and
Playwright's Chromium (`python -m playwright install chromium`), or CHROME_PATH pointing at a Chrome/Chromium.
Screenshots are written to scripts/browser/output/. Exit code 1 if any check fails.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BROWSER = ROOT / "scripts" / "browser"
ALL = {"login": "login_check.py", "loaders": "loaders_check.py", "mobile": "mobile_check.py",
       "a11y": "a11y_check.py", "axe": "axe_scan.py", "csp": "csp_check.py"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(name: str) -> bool:
    port = free_port()
    env = {**os.environ, "ALLOW_FAKE_SUPABASE": "1", "PYTHONUTF8": "1", "BASE_URL": f"http://127.0.0.1:{port}"}
    server = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "dev_fake_server.py"), str(port)], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2)
                break
            except Exception:
                time.sleep(1)
        else:
            print(f"[{name}] the server did not start")
            return False
        print(f"\n=========== {name} ===========", flush=True)
        done = subprocess.run([sys.executable, "-X", "utf8", str(BROWSER / ALL[name])], cwd=ROOT, env=env)
        return done.returncode == 0
    finally:
        server.terminate()


def main(argv: list[str]) -> int:
    names = argv or list(ALL)
    unknown = [n for n in names if n not in ALL]
    if unknown:
        print(f"Unknown check(s): {unknown}. Choose from {list(ALL)}.")
        return 2
    results = {n: run(n) for n in names}
    print("\n=========== summary ===========")
    for n, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
