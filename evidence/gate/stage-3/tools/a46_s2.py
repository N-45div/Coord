"""Gate A-46 check: restaurant-select holds only restaurant ids at the load event; the embedded list is
not an injection vector; it reflects the current state after reset. Usage: uivenv python a46_s2.py http://127.0.0.1:PORT"""
import http.client
import json
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
U = urlparse(BASE)
RES = []


def check(lid, cond, detail=""):
    RES.append(cond)
    print("PASS" if cond else "FAIL", lid, detail if not cond else detail[:120], flush=True)


def reset(fix):
    c = http.client.HTTPConnection(U.hostname, U.port, timeout=15)
    c.request("POST", "/_test/reset", body=json.dumps(fix).encode(), headers={"Content-Type": "application/json"})
    st = c.getresponse().status
    c.close()
    return st


def rest(rid, name):
    return {"id": rid, "name": name, "timezone": "Europe/Berlin", "slot_minutes": 30, "reservation_duration_minutes": 90,
            "cancellation_cutoff_minutes": 0, "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}],
            "tables": [{"id": "t_1", "label": "1", "capacity": 2}]}


EVIL = 'Anker </script><img src=x onerror="window.__pwned=1"><b>x</b> & "q"  '
check("setup", reset({"users": [], "restaurants": [rest("r_a", EVIL), rest("r_b", "Bistro")], "reservations": []}) == 204)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    ok_all = True
    for i in range(10):
        pg.goto(BASE + "/")
        vals = pg.evaluate("() => [...document.querySelectorAll('[data-testid=restaurant-select] option')].map(o => o.value)")
        ok_all &= vals == ["r_a", "r_b"]
    check("A-46", ok_all, f"10/10 loads: options exactly the restaurant ids at the load event (last {vals})")
    pg.wait_for_load_state("networkidle")
    texts = pg.evaluate("() => [...document.querySelectorAll('[data-testid=restaurant-select] option')].map(o => o.textContent)")
    check("A-46", texts and texts[0] == EVIL, f"hostile name rendered as text: {texts}")
    check("A-46", pg.evaluate("() => window.__pwned") is None and not errors and
          pg.evaluate("() => document.querySelectorAll('img[src=x]').length") == 0, f"no injection, no page errors {errors}")
    # deterministic: hold back the client's GET /restaurants so only a server-embedded list can fill the select
    held = []
    pg.route("**/restaurants", lambda route: held.append(route) if route.request.method == "GET" else route.continue_())
    pg.goto(BASE + "/")
    vals = pg.evaluate("() => [...document.querySelectorAll('[data-testid=restaurant-select] option')].map(o => o.value)")
    check("A-46", vals == ["r_a", "r_b"], f"with GET /restaurants held back, options at load are still the ids: {vals}")
    for r in held:
        r.continue_()
    pg.unroute("**/restaurants")
    check("setup", reset({"users": [], "restaurants": [rest("r_c", "Café Neu")], "reservations": []}) == 204)
    pg.goto(BASE + "/")
    vals = pg.evaluate("() => [...document.querySelectorAll('[data-testid=restaurant-select] option')].map(o => o.value)")
    check("A-46", vals == ["r_c"], f"embedded list reflects the current state after reset: {vals}")
    b.close()
print(f"SUMMARY pass={sum(RES)} fail={len(RES) - sum(RES)}")
sys.exit(0 if all(RES) else 1)
