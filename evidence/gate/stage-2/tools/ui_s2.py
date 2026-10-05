"""Gate's independent Playwright probe for the tablekeeper stage-2 browser product (spec stage-2.md + ledger only).
Uses only the spec's data-testid contract and HTTP API. Usage:
  uivenv/Scripts/python.exe ui_s2.py http://127.0.0.1:PORT <screenshot-dir>
PASS/FAIL lines tagged with ledger ids; NOTE lines for Coordinator readings and observations."""
import http.client
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
ART = sys.argv[2]
os.makedirs(ART, exist_ok=True)
U = urlparse(BASE)
RESULTS = []
FOREIGN = []
THU = "2026-11-12"
FRI = "2026-11-13"
CLOSED = "2026-11-10"  # Tuesday: closed
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def check(lid, cond, detail=""):
    RESULTS.append(("PASS" if cond else "FAIL", lid, detail))
    print("PASS" if cond else "FAIL", lid, detail[:150] if cond else detail[:400], flush=True)
    return cond


def note(lid, detail):
    RESULTS.append(("NOTE", lid, detail))
    print("NOTE", lid, detail, flush=True)


def api(method, path, body=None, token=None, key=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if key:
        h["Idempotency-Key"] = key
    c = http.client.HTTPConnection(U.hostname, U.port, timeout=15)
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw) if raw else None
    except Exception:
        return r.status, raw


from zoneinfo import ZoneInfo
now = datetime.now(timezone.utc)
near_local = (now + timedelta(minutes=30)).astimezone(ZoneInfo("Europe/Berlin"))
if near_local.hour * 60 + near_local.minute > 22 * 60 + 30:
    near_local = (near_local + timedelta(days=1)).replace(hour=0, minute=0)
LK_DATE = "2026-11-11"  # Wednesday
FIX = {
    "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada Lovelace"},
              {"id": "u_bob", "email": "bob@example.com", "password": "battery staple", "display_name": "Bob"}],
    "restaurants": [
        {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
         "opening_hours": [{"weekday": d, "opens": "18:00", "closes": "23:00"} for d in ["wed", "thu", "fri", "sat"]],
         "tables": [{"id": "t_1", "label": "Window 1", "capacity": 2}, {"id": "t_2", "label": "Booth 2", "capacity": 4},
                    {"id": "t_3", "label": "Garden 3", "capacity": 4}, {"id": "t_4", "label": "Bar 4", "capacity": 2}],
         "combinable": [["t_1", "t_2"], ["t_3", "t_2"]]},
        {"id": "r_kueche", "name": "Kleine Küche", "timezone": "Europe/Berlin", "slot_minutes": 15,
         "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 180,
         "opening_hours": [{"weekday": d, "opens": "00:00", "closes": "23:45"} for d in ALL],
         "tables": [{"id": "k_1", "label": "Corner", "capacity": 4}], "combinable": []},
    ],
    "reservations": [],
}


def reset():
    st, _ = api("POST", "/_test/reset", FIX)
    assert st == 204, st
    return api("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[1]["token"], \
        api("POST", "/auth/login", {"email": "bob@example.com", "password": "battery staple"})[1]["token"]


def tid(page, t):
    return page.get_by_test_id(t)


def no_hscroll(page):
    return page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


def shot(page, name):
    page.screenshot(path=os.path.join(ART, name + ".png"), full_page=True)


def login_ui(page, email="ada@example.com", pw="correct horse"):
    page.goto(BASE + "/login")
    tid(page, "login-email").fill(email)
    tid(page, "login-password").fill(pw)
    tid(page, "login-submit").click()
    tid(page, "current-user").wait_for(timeout=5000)


def search(page, rid, date, party, wait=True):
    if urlparse(page.url).path not in ("/", ""):
        page.goto(BASE + "/")
    tid(page, "restaurant-select").select_option(rid)
    tid(page, "date-input").fill(date)
    tid(page, "party-size-input").fill(str(party))
    tid(page, "search-button").click()
    if wait:
        page.wait_for_function("""() => document.querySelector('[data-testid="availability-grid"] [data-available]')
                                   || document.querySelector('[data-testid="no-slots"]')""", timeout=8000)
        page.wait_for_timeout(300)


def cell(page, key, hhmm):
    return page.locator(f'[data-testid="slot-{key}-{hhmm}"]')


def grid_matches_api(page, rid, date, party, lid):
    st, av = api("GET", f"/availability?restaurant_id={rid}&date={date}&party_size={party}")
    _, rest = api("GET", f"/restaurants/{rid}")
    bad, n = [], 0
    for s in av["slots"]:
        hh = s["starts_at_local"][11:]
        for t in rest["tables"]:
            n += 1
            loc = cell(page, t["id"], hh)
            want = "true" if t["id"] in s["available_table_ids"] else "false"
            got = loc.get_attribute("data-available") if loc.count() == 1 else f"count={loc.count()}"
            if got != want:
                bad.append((t["id"], hh, want, got))
        for pair in rest.get("combinable", []):
            n += 1
            loc = cell(page, "+".join(pair), hh)
            want = "true" if any(o["table_ids"] == pair for o in s.get("available_options", [])) else "false"
            got = loc.get_attribute("data-available") if loc.count() == 1 else f"count={loc.count()}"
            if got != want:
                bad.append(("+".join(pair), hh, want, got))
    check(lid, not bad, f"{n} cells vs API for {rid} {date} party {party}; mismatches {bad[:6]}")
    return av


def run(pw):
    browser = pw.chromium.launch()
    ada, bob = reset()

    def new_page(width=1280, height=900):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        pg = ctx.new_page()
        pg.on("request", lambda req: FOREIGN.append(req.url) if urlparse(req.url).netloc not in (U.netloc, "")
              and not req.url.startswith(("data:", "blob:")) else None)
        return ctx, pg

    # ---------------------------------------------------------------- routes, responsive, assets
    for width in (1280, 375):
        ctx, pg = new_page(width)
        for route in ("/", "/signup", "/login", "/lookup"):
            resp = pg.goto(BASE + route)
            ct = resp.headers.get("content-type", "")
            check("S2-001", resp.status == 200 and ct.startswith("text/html"), f"{route} @{width}: {resp.status} {ct}")
            pg.wait_for_load_state("networkidle")
            check("S2-024", no_hscroll(pg), f"no horizontal scroll {route} @{width}")
            shot(pg, f"route{route.replace('/', '_') or '_root'}-{width}")
        ctx.close()

    # ---------------------------------------------------------------- auth
    ctx, pg = new_page()
    pg.goto(BASE + "/signup")
    check("S2-004", tid(pg, "auth-error").count() == 0, "auth-error absent before any error (A-26)")
    tid(pg, "signup-email").fill("ada@example.com")
    tid(pg, "signup-password").fill("long enough pw")
    tid(pg, "signup-display-name").fill("Dup")
    tid(pg, "signup-submit").click()
    try:
        tid(pg, "auth-error").wait_for(timeout=4000)
        check("S2-004", tid(pg, "auth-error").inner_text().strip() != "", "signup dup email -> auth-error")
    except Exception:
        check("S2-004", False, "signup dup email did not show auth-error")
    shot(pg, "auth-error-signup-1280")
    tid(pg, "signup-email").fill("dee@example.com")
    tid(pg, "signup-display-name").fill("Dee Signup")
    tid(pg, "signup-submit").click()
    try:
        tid(pg, "current-user").wait_for(timeout=5000)
        check("S2-004", "Dee Signup" in tid(pg, "current-user").inner_text(), "signup signs in; current-user has name")
        check("S2-004", tid(pg, "auth-error").count() == 0, "auth-error removed after success")
    except Exception as e:
        check("S2-004", False, f"signup flow: {e}")
    for route in ("/", "/lookup", "/login", "/signup"):
        pg.goto(BASE + route)
        try:
            tid(pg, "current-user").wait_for(timeout=4000)
            ok = "Dee Signup" in tid(pg, "current-user").inner_text()
        except Exception:
            ok = False
        check("S2-003", ok, f"current-user visible on {route}")
    try:
        tid(pg, "logout-button").click()
        pg.wait_for_timeout(500)
        check("S2-003", tid(pg, "current-user").count() == 0 or not tid(pg, "current-user").is_visible(), "logout")
    except Exception as e:
        check("S2-003", False, f"logout: {e}")
    pg.goto(BASE + "/login")
    tid(pg, "login-email").fill("ada@example.com")
    tid(pg, "login-password").fill("wrong password")
    tid(pg, "login-submit").click()
    try:
        tid(pg, "auth-error").wait_for(timeout=4000)
        check("S2-004", True, "wrong password -> auth-error")
    except Exception:
        check("S2-004", False, "wrong password did not show auth-error")
    tid(pg, "login-password").fill("correct horse")
    tid(pg, "login-submit").click()
    try:
        tid(pg, "current-user").wait_for(timeout=5000)
        check("S2-004", tid(pg, "auth-error").count() == 0 and "Ada Lovelace" in tid(pg, "current-user").inner_text(),
              "login ok, auth-error gone")
    except Exception as e:
        check("S2-004", False, f"login: {e}")
    ctx.close()

    # ---------------------------------------------------------------- signed-out click
    ctx, pg = new_page()
    pg.goto(BASE + "/")
    search(pg, "r_anker", THU, 2)
    c = cell(pg, "t_1", "19:00")
    if c.count():
        c.click()
        pg.wait_for_timeout(700)
        ok = tid(pg, "auth-error").count() > 0 or urlparse(pg.url).path == "/login"
        check("S2-008", ok and tid(pg, "booking-form").count() == 0 or ok, f"signed-out click -> auth-error or /login ({pg.url})")
    ctx.close()

    # ---------------------------------------------------------------- grid vs API, combination cells, no-slots
    ctx, pg = new_page()
    login_ui(pg)
    pg.goto(BASE + "/")
    api("POST", "/reservations", {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
                                  "starts_at_local": f"{THU}T20:00", "party_size": 5}, token=bob, key="seed-b1")
    search(pg, "r_anker", THU, 2)
    grid_matches_api(pg, "r_anker", THU, 2, "S2-006/S2-010")
    shot(pg, "grid-party2-1280")
    search(pg, "r_anker", THU, 5)
    grid_matches_api(pg, "r_anker", THU, 5, "S2-006/S2-010")
    shot(pg, "grid-party5-1280")
    search(pg, "r_anker", CLOSED, 2)
    check("S2-007", tid(pg, "no-slots").count() == 1 and pg.locator('[data-testid^="slot-"]').count() == 0,
          "closed day -> no-slots, no cells")
    shot(pg, "no-slots-1280")
    search(pg, "r_anker", THU, 2)
    u = cell(pg, "t_1", "20:00")
    if u.count() and u.get_attribute("data-available") == "false":
        u.click(force=True)
        pg.wait_for_timeout(500)
        check("S2-008", tid(pg, "booking-form").count() == 0, "clicking an unavailable cell does nothing")
    av_style = pg.evaluate("""() => { const a = document.querySelector('[data-available="true"]');
        const b = document.querySelector('[data-available="false"]'); if (!a || !b) return null;
        const s = e => { const c = getComputedStyle(e); return [c.backgroundColor, c.color, c.borderColor, c.opacity, c.textDecorationLine].join('|'); };
        return [s(a), s(b)]; }""")
    check("S2-023", av_style is not None and av_style[0] != av_style[1], f"available vs unavailable cells styled differently {av_style}")
    ctx.close()

    # ---------------------------------------------------------------- booking, confirmation, resubmit, change field
    ctx, pg = new_page()
    login_ui(pg)
    pg.goto(BASE + "/")
    reqs = []
    pg.on("request", lambda r: reqs.append((r.headers.get("idempotency-key"), r.post_data)) if r.method == "POST"
          and urlparse(r.url).path == "/reservations" else None)
    search(pg, "r_anker", THU, 2)
    cell(pg, "t_3", "19:00").click()
    tid(pg, "booking-form").wait_for(timeout=4000)
    summ = tid(pg, "booking-summary").inner_text()
    check("S2-011", "Garden 3" in summ and "19:00" in summ, f"booking-summary names table label and time: {summ!r}")
    check("S2-011", tid(pg, "booking-party-size").input_value() == "2", "booking-party-size prefilled from search")
    shot(pg, "booking-form-1280")
    tid(pg, "booking-submit").click()
    tid(pg, "confirmation").wait_for(timeout=5000)
    ref = tid(pg, "confirmation-reference").inner_text()
    check("S2-012", re.fullmatch(r"[A-Z0-9]{6,12}", ref) is not None, f"confirmation-reference exactly a reference: {ref!r}")
    det = tid(pg, "confirmation-details").inner_text()
    check("S2-012", "Zum Anker" in det and "Garden 3" in det and "19:00" in det, f"confirmation-details: {det!r}")
    check("S2-012", "Garden 3" in tid(pg, "confirmation-tables").inner_text(), "confirmation-tables")
    st, lst = api("GET", "/reservations", token=ada)
    n1 = len(lst["reservations"])
    check("S2-012", any(x["reference"] == ref for x in lst["reservations"]), "reference exists server-side")
    shot(pg, "confirmation-1280")
    check("S2-013", tid(pg, "booking-form").count() == 1 and tid(pg, "booking-form").is_visible(), "form stays after success")
    tid(pg, "booking-submit").click()
    pg.wait_for_timeout(1200)
    ref2 = tid(pg, "confirmation-reference").inner_text()
    n2 = len(api("GET", "/reservations", token=ada)[1]["reservations"])
    check("S2-013", ref2 == ref and tid(pg, "booking-error").count() == 0 and n2 == n1,
          f"unchanged resubmit -> same reference, no error, no new booking ({ref2} n {n1}->{n2})")
    check("S2-013", len(reqs) >= 2 and reqs[0] == reqs[1], f"resubmit reused key and body: {reqs[:2]}")
    tid(pg, "booking-party-size").fill("3")
    tid(pg, "booking-submit").click()
    pg.wait_for_timeout(1500)
    check("S2-013", len(reqs) >= 3 and reqs[2][0] != reqs[0][0], f"changed field -> new key: {[r[0] for r in reqs]}")
    note("S2-013", f"after changing party to 3 on the same table: error={tid(pg, 'booking-error').count()} "
                   f"ref={tid(pg, 'confirmation-reference').inner_text() if tid(pg, 'confirmation-reference').count() else None}")
    ctx.close()

    # ---------------------------------------------------------------- 409 while form open
    ctx, pg = new_page()
    login_ui(pg)
    pg.goto(BASE + "/")
    search(pg, "r_anker", THU, 2)
    cell(pg, "t_4", "21:00").click()
    tid(pg, "booking-form").wait_for(timeout=4000)
    st, _ = api("POST", "/reservations", {"restaurant_id": "r_anker", "table_id": "t_4", "starts_at_local": f"{THU}T21:00",
                                          "party_size": 2}, token=bob, key="bob-steal")
    tid(pg, "booking-submit").click()
    try:
        tid(pg, "booking-error").wait_for(timeout=5000)
        check("S2-014", tid(pg, "booking-error").inner_text().strip() != "", "409 -> booking-error")
    except Exception:
        check("S2-014", False, "409 did not show booking-error")
    pg.wait_for_timeout(800)
    check("S2-014", tid(pg, "confirmation").count() == 0, "no confirmation for the refused attempt")
    check("S2-014", cell(pg, "t_4", "21:00").get_attribute("data-available") == "false", "availability refreshed")
    check("S2-014", tid(pg, "booking-form").count() == 1 and tid(pg, "booking-party-size").input_value() == "2"
          and "Bar 4" in tid(pg, "booking-summary").inner_text(), "form and inputs preserved")
    shot(pg, "booking-409-1280")
    ctx.close()

    # ---------------------------------------------------------------- lost response after commit (pair), retry identity
    ctx, pg = new_page()
    login_ui(pg)
    pg.goto(BASE + "/")
    search(pg, "r_anker", FRI, 5)
    seen, committed = [], {}

    def lose_after_commit(route):
        resp = route.fetch()
        committed["status"], committed["body"] = resp.status, resp.json()
        seen.append((route.request.headers.get("idempotency-key"), route.request.post_data))
        route.abort("failed")
    pg.route("**/reservations", lambda r: lose_after_commit(r) if r.request.method == "POST" else r.continue_())
    cell(pg, "t_1+t_2", "19:00").click()
    tid(pg, "booking-form").wait_for(timeout=4000)
    summ = tid(pg, "booking-summary").inner_text()
    check("S2-011", "Window 1" in summ and "Booth 2" in summ, f"pair summary names every table: {summ!r}")
    tid(pg, "booking-submit").click()
    try:
        tid(pg, "booking-uncertain").wait_for(timeout=6000)
        check("S2-015", tid(pg, "booking-uncertain").inner_text().strip() != "", "lost response -> booking-uncertain text")
    except Exception:
        check("S2-015", False, "no booking-uncertain after lost response")
    check("S2-015", tid(pg, "booking-error").count() == 0 and tid(pg, "confirmation").count() == 0,
          "no booking-error, no confirmation while uncertain")
    check("S2-015", committed.get("status") == 201, f"server committed the lost booking: {committed.get('status')}")
    shot(pg, "booking-uncertain-1280")
    pg.unroute("**/reservations")
    retry = []
    pg.on("request", lambda r: retry.append((r.headers.get("idempotency-key"), r.post_data)) if r.method == "POST"
          and urlparse(r.url).path == "/reservations" else None)
    tid(pg, "booking-submit").click()
    try:
        tid(pg, "confirmation").wait_for(timeout=6000)
        got = tid(pg, "confirmation-reference").inner_text()
        check("S2-016", got == committed.get("body", {}).get("reference"), f"retry shows the original reference {got}")
    except Exception as e:
        check("S2-016", False, f"retry after uncertainty: {e}")
    check("S2-016", retry[:1] == seen[:1], f"retry used the same key and body: {retry[:1]} vs {seen[:1]}")
    check("S2-016", tid(pg, "booking-uncertain").count() == 0 and tid(pg, "booking-error").count() == 0,
          "uncertainty/error elements removed after successful retry")
    check("S2-018", "Window 1" in tid(pg, "confirmation-tables").inner_text() and
          "Booth 2" in tid(pg, "confirmation-tables").inner_text(), "pair confirmation-tables")
    pairs = [x for x in api("GET", "/reservations", token=ada)[1]["reservations"] if x["starts_at_local"] == f"{FRI}T19:00"]
    check("S2-016", len(pairs) == 1, f"exactly one booking after lost+retry: {len(pairs)}")
    shot(pg, "confirmation-pair-1280")
    ctx.close()

    # ---------------------------------------------------------------- lost before commit, then confirmed rejection
    ctx, pg = new_page()
    login_ui(pg)
    pg.goto(BASE + "/")
    search(pg, "r_anker", FRI, 2)
    pg.route("**/reservations", lambda r: r.abort("failed") if r.request.method == "POST" else r.continue_())
    cell(pg, "t_3", "20:00").click()
    tid(pg, "booking-form").wait_for(timeout=4000)
    tid(pg, "booking-submit").click()
    try:
        tid(pg, "booking-uncertain").wait_for(timeout=6000)
        check("S2-015", True, "lost before commit -> uncertain")
    except Exception:
        check("S2-015", False, "no booking-uncertain (lost before commit)")
    pg.unroute("**/reservations")
    api("POST", "/reservations", {"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": f"{FRI}T20:00",
                                  "party_size": 2}, token=bob, key="bob-steal-2")
    tid(pg, "booking-submit").click()
    try:
        tid(pg, "booking-error").wait_for(timeout=6000)
        check("S2-016", tid(pg, "confirmation").count() == 0, "confirmed rejection after uncertainty -> booking-error")
    except Exception:
        check("S2-016", False, "confirmed rejection did not show booking-error")
    note("S2-016", f"after confirmed rejection: booking-uncertain count={tid(pg, 'booking-uncertain').count()}")
    shot(pg, "booking-rejected-after-uncertain-1280")
    ctx.close()

    # ---------------------------------------------------------------- out-of-order search
    ctx, pg = new_page()
    login_ui(pg)
    pg.goto(BASE + "/")
    held = []

    def hold_first(route):
        if "party_size=2" in route.request.url and not held:
            held.append(route)
        else:
            route.continue_()
    pg.route("**/availability**", hold_first)
    search(pg, "r_anker", THU, 2, wait=False)          # A (held)
    pg.wait_for_timeout(300)
    search(pg, "r_anker", THU, 5)                      # B
    b_state = cell(pg, "t_1", "18:00").get_attribute("data-available"), cell(pg, "t_1+t_2", "18:00").get_attribute("data-available")
    if held:
        held[0].continue_()
    pg.wait_for_timeout(1500)
    after = cell(pg, "t_1", "18:00").get_attribute("data-available"), cell(pg, "t_1+t_2", "18:00").get_attribute("data-available")
    check("S2-009", held and b_state == ("false", "true") and after == b_state,
          f"late response A must not restore A: B={b_state} after A arrived={after}")
    cell(pg, "t_1+t_2", "18:00").click()
    try:
        tid(pg, "booking-form").wait_for(timeout=3000)
        check("S2-009", tid(pg, "booking-party-size").input_value() == "5", "booking form describes B (party 5)")
    except Exception as e:
        check("S2-009", False, f"form after out-of-order: {e}")
    pg.unroute("**/availability**")
    ctx.close()

    # ---------------------------------------------------------------- lookup
    ctx, pg = new_page()
    login_ui(pg)
    st, mine = api("POST", "/reservations", {"restaurant_id": "r_anker", "table_ids": ["t_3", "t_2"],
                                             "starts_at_local": f"{LK_DATE}T18:00", "party_size": 6}, token=ada, key="lk1")
    st, theirs = api("POST", "/reservations", {"restaurant_id": "r_anker", "table_id": "t_4",
                                               "starts_at_local": f"{LK_DATE}T18:00", "party_size": 2}, token=bob, key="lk2")
    near = near_local.replace(minute=(near_local.minute // 15) * 15).strftime("%Y-%m-%dT%H:%M")
    st, nearres = api("POST", "/reservations", {"restaurant_id": "r_kueche", "table_id": "k_1", "starts_at_local": near,
                                                "party_size": 2}, token=ada, key="lk3")
    pg.goto(BASE + "/lookup")
    check("S2-021", tid(pg, "reservation-error").count() == 0, "reservation-error absent initially")
    tid(pg, "lookup-reference-input").fill(mine["reference"])
    tid(pg, "lookup-submit").click()
    try:
        tid(pg, "reservation-detail").wait_for(timeout=5000)
        check("S2-019", tid(pg, "reservation-status").inner_text().strip() == "confirmed", "status confirmed")
        t = tid(pg, "reservation-tables").inner_text()
        check("S2-019", "Garden 3" in t and "Booth 2" in t, f"reservation-tables names every label: {t!r}")
        shot(pg, "lookup-found-1280")
        tid(pg, "reservation-cancel-button").click()
        pg.wait_for_function("""() => { const s = document.querySelector('[data-testid="reservation-status"]');
                                return s && s.textContent.trim() === 'cancelled'; }""", timeout=5000)
        check("S2-020", tid(pg, "reservation-cancel-button").count() == 0, "cancel button absent once cancelled")
        check("S2-020", api("GET", f"/reservations/{mine['reference']}", token=ada)[1]["status"] == "cancelled", "server cancelled")
        shot(pg, "lookup-cancelled-1280")
    except Exception as e:
        check("S2-019", False, f"lookup found flow: {e}")
    for refv, what in (("NOPE0000", "unknown"), (theirs["reference"], "another user's")):
        tid(pg, "lookup-reference-input").fill(refv)
        tid(pg, "lookup-submit").click()
        try:
            tid(pg, "reservation-error").wait_for(timeout=4000)
            check("S2-021", tid(pg, "reservation-detail").count() == 0 or not tid(pg, "reservation-detail").is_visible(),
                  f"{what} -> reservation-error, no detail")
        except Exception:
            check("S2-021", False, f"{what} reference did not show reservation-error")
    shot(pg, "lookup-error-1280")
    if st == 201:
        tid(pg, "lookup-reference-input").fill(nearres["reference"])
        tid(pg, "lookup-submit").click()
        try:
            tid(pg, "reservation-detail").wait_for(timeout=4000)
            tid(pg, "reservation-cancel-button").click()
            tid(pg, "reservation-error").wait_for(timeout=4000)
            check("S2-021", tid(pg, "reservation-status").inner_text().strip() == "confirmed",
                  "refused cancel (cutoff) -> reservation-error, still confirmed")
        except Exception as e:
            check("S2-021", False, f"refused cancel: {e}")
        shot(pg, "lookup-cancel-refused-1280")
    else:
        note("S2-021", f"could not create the near booking for the cutoff case: {st} {nearres}")
    ctx.close()

    # ---------------------------------------------------------------- upgrade between requests (no reload)
    ctx, pg = new_page()
    login_ui(pg)
    pg.goto(BASE + "/")
    search(pg, "r_anker", "2026-11-14", 2)
    lost = {}

    def lose(route):
        resp = route.fetch()
        lost["body"] = resp.json()
        lost["req"] = (route.request.headers.get("idempotency-key"), route.request.post_data)
        route.abort("failed")
    pg.route("**/reservations", lambda r: lose(r) if r.request.method == "POST" else r.continue_())
    cell(pg, "t_2", "19:00").click()
    tid(pg, "booking-form").wait_for(timeout=4000)
    tid(pg, "booking-submit").click()
    try:
        tid(pg, "booking-uncertain").wait_for(timeout=6000)
    except Exception:
        pass
    pg.unroute("**/reservations")
    st, exp = api("GET", "/_test/export")
    api("POST", "/_test/reset", FIX)
    st2, _ = api("POST", "/_test/import", exp)
    check("S2-029", st == 200 and st2 == 204, "export -> reset -> import between browser requests")
    retry = []
    pg.on("request", lambda r: retry.append((r.headers.get("idempotency-key"), r.post_data)) if r.method == "POST"
          and urlparse(r.url).path == "/reservations" else None)
    tid(pg, "booking-submit").click()
    try:
        tid(pg, "confirmation").wait_for(timeout=6000)
        check("S2-029", tid(pg, "confirmation-reference").inner_text() == lost.get("body", {}).get("reference"),
              "after upgrade, retry recovers the original confirmation without reload")
    except Exception as e:
        check("S2-029", False, f"retry after upgrade: {e}")
    check("S2-029", retry[:1] == [lost.get("req")], "pending retry identity survived the upgrade")
    check("S2-027", "Ada Lovelace" in tid(pg, "current-user").inner_text(), "still signed in after upgrade")
    pg.goto(BASE + "/lookup")
    tid(pg, "lookup-reference-input").fill(lost.get("body", {}).get("reference", "X"))
    tid(pg, "lookup-submit").click()
    try:
        tid(pg, "reservation-detail").wait_for(timeout=4000)
        check("S2-028", tid(pg, "reservation-status").inner_text().strip() == "confirmed", "retained reference via lookup")
    except Exception as e:
        check("S2-028", False, f"lookup after upgrade: {e}")
    ctx.close()

    # ---------------------------------------------------------------- 375 px flows + keyboard
    ctx, pg = new_page(375, 812)
    login_ui(pg)
    pg.goto(BASE + "/")
    search(pg, "r_anker", "2026-11-18", 2)
    check("S2-024", no_hscroll(pg), "375px: no horizontal page scroll with the grid")
    shot(pg, "grid-375")
    tid(pg, "search-button").focus()
    for _ in range(80):  # real keyboard navigation from the search button into the grid
        pg.keyboard.press("Tab")
        if (pg.evaluate("() => document.activeElement && document.activeElement.getAttribute('data-testid')") or "").startswith("slot-"):
            break
    focused = pg.evaluate("""() => { const e = document.activeElement; if (!e) return null; const c = getComputedStyle(e);
        return {testid: e.getAttribute('data-testid'), outline: c.outlineStyle + ' ' + c.outlineWidth, shadow: c.boxShadow}; }""")
    check("S2-025", focused and (focused["testid"] or "").startswith("slot-"), f"grid cell reachable by Tab: {focused}")
    check("S2-025", focused and (not focused["outline"].startswith("none") or focused["shadow"] != "none"),
          f"visible focus indicator on cell: {focused}")
    shot(pg, "grid-focus-375")
    pg.keyboard.press("Enter")
    try:
        tid(pg, "booking-form").wait_for(timeout=3000)
        check("S2-025", True, "Enter on a focused cell opens the booking form")
    except Exception:
        check("S2-025", False, "keyboard: Enter on cell did not open the form")
    check("S2-024", no_hscroll(pg), "375px: no horizontal scroll with the booking form")
    shot(pg, "booking-form-375")
    tid(pg, "booking-submit").focus()
    pg.keyboard.press("Enter")
    try:
        tid(pg, "confirmation").wait_for(timeout=5000)
        check("S2-025", True, "keyboard submit works")
    except Exception:
        check("S2-025", False, "keyboard submit did not confirm")
    check("S2-024", no_hscroll(pg), "375px: no horizontal scroll with confirmation")
    shot(pg, "confirmation-375")
    labels = pg.evaluate("""() => [...document.querySelectorAll('input, select')].filter(e => e.offsetParent !== null)
        .map(e => ({id: e.getAttribute('data-testid'), label: !!(e.labels && e.labels.length) || !!e.getAttribute('aria-label') || !!e.getAttribute('aria-labelledby')}))""")
    check("S2-025", all(x["label"] for x in labels), f"inputs have labels: {labels}")
    pg.goto(BASE + "/lookup")
    check("S2-024", no_hscroll(pg), "375px lookup")
    shot(pg, "lookup-375")
    ctx.close()
    browser.close()


if __name__ == "__main__":
    t0 = time.monotonic()
    with sync_playwright() as p:
        try:
            run(p)
        except Exception as exc:  # noqa
            import traceback
            traceback.print_exc()
            RESULTS.append(("FAIL", "PROBE", f"probe crashed: {exc!r}"))
    check("S2-002", not FOREIGN, f"requests to other origins: {sorted(set(FOREIGN))[:5]}")
    fails = [x for x in RESULTS if x[0] == "FAIL"]
    print(f"SUMMARY pass={sum(1 for x in RESULTS if x[0] == 'PASS')} fail={len(fails)} "
          f"note={sum(1 for x in RESULTS if x[0] == 'NOTE')} {time.monotonic() - t0:.1f}s")
    for f in fails:
        print("FAILED", f[1], f[2][:300])
    sys.exit(1 if fails else 0)
