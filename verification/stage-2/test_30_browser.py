"""Stage-2 browser product (stage-2.md screens, competing clients, upgrade; ledger S2-001..S2-029).

Playwright drives Chromium against the service's own pages. Expected grid states come from
GET /availability through the API client, which is the spec's definition of the grid (S2-006).
"""
import re

import httpx
import pytest
from playwright.sync_api import sync_playwright

import tk
import ui
from tk import COMBO, THU, MON, expect
from ui import T

T19 = f"{THU}T19:00"
PAST_SEED = {"id": "sp_past", "reference": "OLDPAST1", "user_id": "u_ada", "restaurant_id": "r_combo",
             "table_id": "c_3", "starts_at_local": "2025-06-19T19:00", "party_size": 2}


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _page(browser, width=1280, height=900):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    pg = ctx.new_page()
    pg.set_default_timeout(ui.WAIT)
    return ctx, pg


@pytest.fixture
def page(browser):
    ctx, pg = _page(browser)
    yield pg
    ctx.close()


@pytest.fixture
def uw(api):
    return tk.World(api, tk.fixture(restaurants=(COMBO, tk.ANKER), reservations=[PAST_SEED]))


def ada_ui(page):
    ui.login(page, tk.ADA["email"], tk.ADA["password"])


def open_form(page, tables, local, party):
    ui.search(page, "r_combo", local[:10], party)
    cid = ui.cell_id(tables, local)
    ui.wait_cell(page, cid, True)
    T(page, cid).first.click()
    ui.wait_visible(page, "booking-form")


# ---- routes and assets -------------------------------------------------------------------

@pytest.mark.ledger("S2-001")
@pytest.mark.parametrize("path", ["/", "/signup", "/login", "/lookup"])
def test_screen_routes_return_html(uw, path):
    r = httpx.get(tk.BASE_URL + path, timeout=5)
    assert r.status_code == 200, r
    assert r.headers.get("content-type", "").lower().startswith("text/html"), r.headers.get("content-type")
    assert "<html" in r.text.lower() or "<!doctype html" in r.text.lower()


@pytest.mark.ledger("S2-002")
def test_every_asset_served_by_the_service(uw, browser, api):
    ctx, page = _page(browser)
    seen = []
    ctx.on("request", lambda req: seen.append(req.url))
    try:
        for path in ("/", "/signup", "/login", "/lookup"):
            page.goto(ui.url(path), wait_until="networkidle")
        ada_ui(page)
        ui.search(page, "r_combo", THU, 2)
        ui.wait_cell(page, "slot-c_1-19:00", True)
        page.wait_for_load_state("networkidle")
    finally:
        ctx.close()
    origin = re.match(r"^(https?://[^/]+)", tk.BASE_URL).group(1)
    foreign = [u for u in seen if not (u.startswith(origin) or u.startswith("data:") or u.startswith("blob:"))]
    assert not foreign, f"the UI fetches resources from outside the service: {sorted(set(foreign))}"


# ---- signup, login, current user ---------------------------------------------------------

@pytest.mark.ledger("S2-003", "S2-004", "A-26")
def test_signup_login_logout_and_auth_error(uw, page, api):
    page.goto(ui.url("/signup"))
    assert T(page, "auth-error").count() == 0, "auth-error present without an error (A-26)"
    T(page, "signup-email").fill(tk.ADA["email"])  # already registered -> 409 email_taken
    T(page, "signup-password").fill("long enough pw")
    T(page, "signup-display-name").fill("Neo")
    T(page, "signup-submit").click()
    ui.wait_visible(page, "auth-error")
    assert ui.text(page, "auth-error")
    T(page, "signup-email").fill("neo@example.com")
    T(page, "signup-password").fill("long enough pw")
    T(page, "signup-display-name").fill("Neo")
    T(page, "signup-submit").click()
    ui.wait_visible(page, "current-user")
    assert "Neo" in ui.text(page, "current-user")
    ui.wait_gone(page, "auth-error")
    expect(api.login("neo@example.com", "long enough pw"), 200)
    T(page, "logout-button").first.click()
    page.wait_for_timeout(300)
    assert not ui.visible(page, "current-user"), "still shown as signed in after logout"
    page.goto(ui.url("/login"))
    T(page, "login-email").fill("neo@example.com")
    T(page, "login-password").fill("wrong password")
    T(page, "login-submit").click()
    ui.wait_visible(page, "auth-error")
    T(page, "login-email").fill("neo@example.com")
    T(page, "login-password").fill("long enough pw")
    T(page, "login-submit").click()
    ui.wait_visible(page, "current-user")
    ui.wait_gone(page, "auth-error")
    ui.shot(page, "login-signed-in")


@pytest.mark.ledger("S2-003")
def test_current_user_on_every_screen(uw, page):
    ada_ui(page)
    page.goto(ui.url("/"))
    for path in ("/lookup", "/", "/login", "/signup"):
        ui.nav(page, path)
        ui.wait_visible(page, "current-user")
        assert "Ada" in ui.text(page, "current-user"), path


# ---- search and grid ---------------------------------------------------------------------

@pytest.mark.ledger("S2-005", "S2-006", "S2-010")
def test_grid_matches_availability_api(uw, page, api):
    api.book(uw.bob, "r_combo", "c_2", T19)
    expect(api.create(uw.cy, {"restaurant_id": "r_combo", "table_ids": ["c_4", "c_1"],
                              "starts_at_local": f"{THU}T20:30", "party_size": 7}), 201)
    page.goto(ui.url("/"))
    values = T(page, "restaurant-select").locator("option").evaluate_all("os => os.map(o => o.value)")
    assert {"r_combo", "r_anker"} <= set(values), values
    assert T(page, "party-size-input").get_attribute("type") == "number"
    ui.search(page, "r_combo", THU, 2, goto=False)
    want = ui.expected_cells(api, COMBO, THU, 2)
    ui.wait_cell(page, "slot-c_2-19:00", False)
    ui.wait_cell(page, "slot-c_3-19:00", True)
    assert T(page, "date-input").input_value() == THU
    got = ui.cells(page)
    errors = []
    for k, v in want.items():
        if "+" in k:
            if v == "true" and got.get(k) != "true":
                errors.append(f"{k}: pair available but cell is {got.get(k)!r}")
            if v == "false" and k in got and got[k] != "false":
                errors.append(f"{k}: pair unavailable but cell is {got[k]!r}")
        elif got.get(k) != v:
            errors.append(f"{k}: expected data-available={v!r}, got {got.get(k)!r}")
    extra = sorted(set(got) - set(want))
    assert not errors, "grid differs from GET /availability:\n" + "\n".join(errors[:40])
    assert not extra, f"cells for tables/slots/pairs that do not exist: {extra[:20]}"
    ui.shot(page, "grid-desktop")


@pytest.mark.ledger("A-21", "S2-010")
def test_every_declared_pair_rendered_at_every_slot(uw, page, api):
    api.book(uw.bob, "r_combo", "c_2", T19)
    ui.search(page, "r_combo", THU, 2)
    ui.wait_cell(page, "slot-c_2-19:00", False)
    got = ui.cells(page)
    want = ui.expected_cells(api, COMBO, THU, 2)
    missing = [k for k in want if "+" in k and k not in got]
    assert not missing, f"combination cells missing (A-21 renders every declared pair): {missing[:12]}"
    for k in (k for k in want if "+" in k):
        assert got[k] == want[k], f"{k}: {got[k]} != {want[k]}"


@pytest.mark.ledger("S2-006")
def test_grid_follows_searched_party_size(uw, page, api):
    ui.search(page, "r_combo", THU, 5)
    ui.wait_cell(page, "slot-c_4-19:00", True)
    ui.wait_cell(page, "slot-c_1-19:00", False)
    ui.wait_cell(page, "slot-c_2-19:00", False)
    got = ui.cells(page)
    for k, v in ui.expected_cells(api, COMBO, THU, 5).items():
        if "+" not in k:
            assert got.get(k) == v, k


@pytest.mark.ledger("S2-007")
def test_closed_day_shows_no_slots(uw, page):
    ui.search(page, "r_anker", MON, 2)
    ui.wait_visible(page, "no-slots")
    assert not ui.cells(page), "slot cells shown on a day without slots"


@pytest.mark.ledger("S2-008")
def test_signed_out_click_on_available_cell(uw, page):
    ui.search(page, "r_combo", THU, 2)
    ui.wait_cell(page, "slot-c_1-19:00", True)
    T(page, "slot-c_1-19:00").first.click()
    page.wait_for_timeout(500)
    assert ui.visible(page, "auth-error") or "/login" in page.url, \
        "signed out: an available cell must show auth-error or go to /login"
    assert not ui.visible(page, "booking-form") or "/login" in page.url


@pytest.mark.ledger("S2-008")
def test_unavailable_cell_does_nothing(uw, page, api):
    api.book(uw.bob, "r_combo", "c_2", T19)
    ada_ui(page)
    ui.search(page, "r_combo", THU, 2)
    ui.wait_cell(page, "slot-c_2-19:00", False)
    T(page, "slot-c_2-19:00").first.click(force=True)
    page.wait_for_timeout(600)
    assert not ui.visible(page, "booking-form"), "clicking an unavailable cell opened the booking form"


# ---- booking form, confirmation, resubmission --------------------------------------------

@pytest.mark.ledger("S2-011", "S2-012", "S2-013")
def test_book_confirm_resubmit_and_change(uw, page, api):
    ada_ui(page)
    net = ui.Net(page)
    open_form(page, "c_2", T19, 3)
    summary = ui.text(page, "booking-summary")
    assert "Kamin" in summary and "19:00" in summary, summary
    assert T(page, "booking-party-size").input_value() == "3"
    ui.shot(page, "booking-form")
    T(page, "booking-submit").click()
    ui.wait_visible(page, "confirmation-reference")
    ref = ui.text(page, "confirmation-reference")
    assert tk.REF_RE.match(ref), f"confirmation-reference must be exactly the reference: {ref!r}"
    mine = [m for m in api.list(uw.ada) if m["reference"] != "OLDPAST1"]
    assert [m["reference"] for m in mine] == [ref]
    tk.assert_res(mine[0], COMBO, "c_2", T19, 3, "confirmed")
    details = ui.text(page, "confirmation-details")
    for part in ("Gasthaus Linde", "Kamin", "19:00"):
        assert part in details, f"confirmation-details lacks {part!r}: {details!r}"
    assert "Kamin" in ui.text(page, "confirmation-tables")
    assert ui.visible(page, "booking-form"), "the booking form must stay on screen after success"
    ui.shot(page, "confirmation")
    # unchanged resubmission: same reference, no error, no second booking, same key and body
    T(page, "booking-submit").click()
    page.wait_for_timeout(800)
    assert ui.text(page, "confirmation-reference") == ref
    assert T(page, "booking-error").count() == 0 or not ui.visible(page, "booking-error")
    assert len(api.list(uw.ada)) == 2  # OLDPAST1 + one new booking
    assert len(net.posts) == 2 and net.posts[0] == net.posts[1], net.posts
    # a changed field makes the next submission a new booking request (new key, new body). The table
    # is now taken by Ada's own booking, so the server answers 409 and no second booking exists.
    T(page, "booking-party-size").fill("2")
    T(page, "booking-submit").click()
    for _ in range(50):
        if len(net.posts) >= 3:
            break
        page.wait_for_timeout(100)
    assert len(net.posts) == 3, net.posts
    assert net.posts[2]["key"] != net.posts[0]["key"], "a changed form must use a new idempotency key"
    assert net.posts[2]["body"]["party_size"] == 2
    ui.wait_visible(page, "booking-error")
    assert len(api.list(uw.ada)) == 2  # OLDPAST1 + the first booking


@pytest.mark.ledger("S2-011", "S2-012", "S2-018", "S2-022")
def test_book_a_combination(uw, page, api):
    ada_ui(page)
    open_form(page, ["c_1", "c_2"], T19, 5)
    summary = ui.text(page, "booking-summary")
    assert "Fenster" in summary and "Kamin" in summary and "19:00" in summary, summary
    T(page, "booking-submit").click()
    ui.wait_visible(page, "confirmation-reference")
    ref = ui.text(page, "confirmation-reference")
    r = api.get_ok(uw.ada, ref)
    assert r["table_ids"] == ["c_1", "c_2"] and r["party_size"] == 5
    tables = ui.text(page, "confirmation-tables")
    assert "Fenster" in tables and "Kamin" in tables, tables
    ui.shot(page, "confirmation-combination")


@pytest.mark.ledger("S2-014", "S2-018")
@pytest.mark.parametrize("tables,party", [("c_3", 2), (["c_3", "c_2"], 5)], ids=["single", "pair"])
def test_conflict_shows_error_refreshes_and_keeps_form(uw, page, api, tables, party):
    ada_ui(page)
    open_form(page, tables, T19, party)
    api.book(uw.bob, "r_combo", "c_3", T19)  # another client takes the table
    T(page, "booking-submit").click()
    ui.wait_visible(page, "booking-error")
    assert ui.text(page, "booking-error")
    assert T(page, "confirmation-reference").count() == 0, "a confirmation was shown for a refused attempt"
    assert ui.visible(page, "booking-form"), "the form must be preserved after a 409"
    assert T(page, "booking-party-size").input_value() == str(party)
    ui.wait_cell(page, ui.cell_id(tables, T19), False)  # availability refreshed
    assert api.list(uw.ada) == [api.get_ok(uw.ada, "OLDPAST1")]
    ui.shot(page, f"conflict-{'pair' if isinstance(tables, list) else 'single'}")


def _abort_after_commit(page, captured):
    def handler(route):
        req = route.request
        if req.method == "POST" and re.search(r"/reservations(\?|$)", req.url):
            resp = route.fetch()
            captured.append({"status": resp.status, "body": resp.json(), "key": req.header_value("idempotency-key")})
            route.abort("connectionreset")
        else:
            route.continue_()
    pred = lambda u: "/reservations" in u  # noqa: E731
    page.route(pred, handler)
    return pred, handler


@pytest.mark.ledger("S2-015", "S2-016", "S2-017", "S2-018")
@pytest.mark.parametrize("tables,party", [("c_4", 2), (["c_4", "c_1"], 7)], ids=["single", "pair"])
def test_lost_response_then_retry_recovers_original(uw, page, api, tables, party):
    ada_ui(page)
    net = ui.Net(page)
    open_form(page, tables, T19, party)
    captured = []
    pred, handler = _abort_after_commit(page, captured)
    T(page, "booking-submit").click()
    ui.wait_visible(page, "booking-uncertain")
    assert ui.text(page, "booking-uncertain"), "booking-uncertain must be nonempty"
    assert T(page, "booking-error").count() == 0 or not ui.visible(page, "booking-error")
    assert T(page, "confirmation-reference").count() == 0, "no confirmation may be shown for an uncertain outcome"
    assert captured and captured[0]["status"] == 201, captured
    committed = captured[0]["body"]["reference"]
    ui.shot(page, "uncertain")
    page.unroute(pred, handler)
    T(page, "booking-submit").click()
    ui.wait_visible(page, "confirmation-reference")
    assert ui.text(page, "confirmation-reference") == committed
    ui.wait_gone(page, "booking-uncertain")
    assert T(page, "booking-error").count() == 0
    assert [r["reference"] for r in api.list(uw.ada) if r["status"] == "confirmed" and r["reference"] != "OLDPAST1"] == [committed]
    assert len(net.posts) == 2 and net.posts[0] == net.posts[1], "the retry must reuse the same key and body"


@pytest.mark.ledger("S2-016")
def test_lost_request_then_confirmed_rejection_shows_booking_error(uw, page, api):
    ada_ui(page)
    open_form(page, "c_4", T19, 2)

    def drop(route):
        if route.request.method == "POST":
            route.abort("connectionreset")  # never reaches the server
        else:
            route.continue_()
    pred = lambda u: "/reservations" in u  # noqa: E731
    page.route(pred, drop)
    T(page, "booking-submit").click()
    ui.wait_visible(page, "booking-uncertain")
    page.unroute(pred, drop)
    api.book(uw.bob, "r_combo", "c_4", T19)
    T(page, "booking-submit").click()
    ui.wait_visible(page, "booking-error")
    assert T(page, "confirmation-reference").count() == 0


@pytest.mark.ledger("S2-009")
def test_late_search_response_never_restores_old_results(uw, page, api):
    ada_ui(page)
    page.goto(ui.url("/"))
    held = []

    def hold_anker(route):
        req = route.request
        is_search = "/availability" in req.url or req.resource_type == "document"
        if "r_anker" in req.url and is_search and not held:
            held.append(route)
        else:
            route.continue_()
    page.route(lambda u: True, hold_anker)
    ui.search(page, "r_anker", THU, 2, goto=False)
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, "search A (r_anker) issued no request carrying the restaurant id"
    ui.search(page, "r_combo", THU, 2, goto=False)
    ui.wait_cell(page, "slot-c_1-19:00", True)
    held[0].continue_()
    page.wait_for_timeout(2000)
    got = ui.cells(page)
    assert got, "grid disappeared"
    assert not [k for k in got if k.startswith("slot-t_")], "late response A replaced the grid of search B"
    assert "slot-c_1-19:00" in got
    T(page, "slot-c_1-19:00").first.click()
    ui.wait_visible(page, "booking-form")
    summary = ui.text(page, "booking-summary")
    assert "Fenster" in summary, f"booking form does not describe search B: {summary!r}"


# ---- lookup ------------------------------------------------------------------------------

@pytest.mark.ledger("S2-019", "S2-020", "S2-021")
def test_lookup_status_tables_cancel(uw, page, api):
    pair = expect(api.create(uw.ada, {"restaurant_id": "r_combo", "table_ids": ["c_1", "c_2"],
                                      "starts_at_local": T19, "party_size": 5}), 201)
    ada_ui(page)
    page.goto(ui.url("/lookup"))
    T(page, "lookup-reference-input").fill(pair["reference"])
    T(page, "lookup-submit").click()
    ui.wait_visible(page, "reservation-detail")
    assert ui.text(page, "reservation-status") == "confirmed"
    tables = ui.text(page, "reservation-tables")
    assert "Fenster" in tables and "Kamin" in tables, tables
    ui.shot(page, "lookup-confirmed")
    T(page, "reservation-cancel-button").click()
    page.wait_for_function("() => { const e = document.querySelector('[data-testid=reservation-status]');"
                           " return e && e.innerText.trim() === 'cancelled'; }")
    ui.wait_gone(page, "reservation-cancel-button")
    assert api.get_ok(uw.ada, pair["reference"])["status"] == "cancelled"


@pytest.mark.ledger("S2-021")
@pytest.mark.parametrize("which", ["unknown", "foreign"])
def test_lookup_not_found_shows_reservation_error(uw, page, api, which):
    ref = "ZZZZZZ99"
    if which == "foreign":
        ref = api.book(uw.bob, "r_combo", "c_1", T19)["reference"]
    ada_ui(page)
    page.goto(ui.url("/lookup"))
    T(page, "lookup-reference-input").fill(ref)
    T(page, "lookup-submit").click()
    ui.wait_visible(page, "reservation-error")
    assert not ui.visible(page, "reservation-detail")


@pytest.mark.ledger("S2-021", "S1-072")
def test_refused_cancel_shows_reservation_error(uw, page, api):
    ada_ui(page)
    page.goto(ui.url("/lookup"))
    T(page, "lookup-reference-input").fill("OLDPAST1")
    T(page, "lookup-submit").click()
    ui.wait_visible(page, "reservation-detail")
    assert ui.text(page, "reservation-status") == "confirmed"
    T(page, "reservation-cancel-button").click()
    ui.wait_visible(page, "reservation-error")
    assert ui.text(page, "reservation-status") == "confirmed"
    ui.shot(page, "lookup-refused")


@pytest.mark.ledger("A-24")
def test_signed_out_lookup(uw, page, api):
    ref = api.book(uw.ada, "r_combo", "c_1", T19)["reference"]
    page.goto(ui.url("/lookup"))
    T(page, "lookup-reference-input").fill(ref)
    T(page, "lookup-submit").click()
    page.wait_for_timeout(800)
    assert ui.visible(page, "reservation-error") or ui.visible(page, "auth-error") or "/login" in page.url
    assert not ui.visible(page, "reservation-detail")


# ---- layout, keyboard, labels, states ------------------------------------------------------

@pytest.mark.ledger("S2-024")
@pytest.mark.parametrize("width", [375, 1280])
def test_no_horizontal_scrolling(uw, browser, api, width):
    ctx, page = _page(browser, width, 800)
    try:
        bad = []
        for path in ("/", "/signup", "/login", "/lookup"):
            page.goto(ui.url(path))
            m = ui.no_hscroll(page)
            if max(m["doc"], m["body"]) > m["inner"]:
                bad.append((path, m))
        ada_ui(page)
        open_form(page, ["c_1", "c_2"], T19, 5)
        m = ui.no_hscroll(page)
        if max(m["doc"], m["body"]) > m["inner"]:
            bad.append(("/ grid+form", m))
        ui.shot(page, f"grid-form-{width}")
        T(page, "booking-submit").click()
        ui.wait_visible(page, "confirmation-reference")
        m = ui.no_hscroll(page)
        if max(m["doc"], m["body"]) > m["inner"]:
            bad.append(("/ confirmation", m))
        ui.shot(page, f"confirmation-{width}")
        assert not bad, f"horizontal page scrolling at {width}px: {bad}"
    finally:
        ctx.close()


@pytest.mark.ledger("S2-025", "S2-008")
def test_grid_cells_and_submit_keyboard_operable(uw, page, api):
    ada_ui(page)
    ui.search(page, "r_combo", THU, 2)
    ui.wait_cell(page, "slot-c_3-19:00", True)
    cell = T(page, "slot-c_3-19:00").first
    cell.focus()
    focused = page.evaluate("() => { const a = document.activeElement; const c = document.querySelector("
                            "'[data-testid=\"slot-c_3-19:00\"]'); return !!a && (a === c || c.contains(a)); }")
    assert focused, "an available grid cell cannot take keyboard focus"
    page.keyboard.press("Enter")
    ui.wait_visible(page, "booking-form")
    T(page, "booking-submit").focus()
    page.keyboard.press("Enter")
    ui.wait_visible(page, "confirmation-reference")


@pytest.mark.ledger("S2-025")
def test_keyboard_focus_is_visible(uw, page):
    page.goto(ui.url("/"))
    T(page, "party-size-input").click()
    page.keyboard.press("Tab")
    diff = page.evaluate("""() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const props = ['outlineStyle','outlineWidth','outlineColor','boxShadow','borderColor','backgroundColor','textDecorationLine'];
        const on = getComputedStyle(el); const a = props.map(p => on[p]);
        el.blur();
        const off = getComputedStyle(el); const b = props.map(p => off[p]);
        return {tag: el.tagName, changed: props.filter((p, i) => a[i] !== b[i]),
                outline: a[0] !== 'none' && a[1] !== '0px'};
    }""")
    assert diff is not None, "Tab did not move focus to a control"
    assert diff["changed"] or diff["outline"], f"keyboard focus has no visible indicator on {diff['tag']}"


@pytest.mark.ledger("S2-025")
@pytest.mark.parametrize("path,ids", [
    ("/signup", ["signup-email", "signup-password", "signup-display-name"]),
    ("/login", ["login-email", "login-password"]),
    ("/", ["restaurant-select", "date-input", "party-size-input"]),
    ("/lookup", ["lookup-reference-input"]),
])
def test_inputs_have_visible_labels(uw, page, path, ids):
    page.goto(ui.url(path))
    for i in ids:
        ok = T(page, i).first.evaluate("""el => {
            const vis = n => n && n.getClientRects().length > 0 && n.innerText.trim().length > 0;
            if (el.labels && Array.from(el.labels).some(vis)) return true;
            const ref = el.getAttribute('aria-labelledby');
            if (ref) return ref.split(/\\s+/).some(id => vis(document.getElementById(id)));
            return false;
        }""")
        assert ok, f"{path}: input {i} has no visible label"


@pytest.mark.ledger("S2-023")
def test_available_unavailable_selected_cells_look_different(uw, page, api):
    api.book(uw.bob, "r_combo", "c_2", T19)
    ada_ui(page)
    ui.search(page, "r_combo", THU, 2)
    ui.wait_cell(page, "slot-c_2-19:00", False)
    style = """el => { const s = getComputedStyle(el);
        return [s.backgroundColor, s.color, s.borderColor, s.opacity, s.textDecorationLine, s.backgroundImage].join('|'); }"""
    avail = T(page, "slot-c_1-19:00").first.evaluate(style)
    unavail = T(page, "slot-c_2-19:00").first.evaluate(style)
    assert avail != unavail, "available and unavailable cells are styled identically"
    T(page, "slot-c_1-19:00").first.click()
    ui.wait_visible(page, "booking-form")
    page.mouse.move(0, 0)
    selected = T(page, "slot-c_1-19:00").first.evaluate(style)
    other = T(page, "slot-c_3-19:00").first.evaluate(style)
    assert selected != other, "the selected cell looks like any other available cell"
    ui.shot(page, "selected-cell")


# ---- upgrade (export/import between browser requests) --------------------------------------

@pytest.mark.ledger("S2-027", "S2-028", "S2-029", "A-25")
def test_signed_in_browser_and_pending_retry_survive_export_import(uw, page, api):
    ada_ui(page)
    net = ui.Net(page)
    open_form(page, "c_4", T19, 2)
    captured = []
    pred, handler = _abort_after_commit(page, captured)
    T(page, "booking-submit").click()
    ui.wait_visible(page, "booking-uncertain")
    page.unroute(pred, handler)
    committed = captured[0]["body"]["reference"]
    exported = api.export()
    api.reset(tk.fixture(users=(tk.BOB,), restaurants=(tk.HARBOR,)))
    expect(api.import_(exported), 204)
    T(page, "booking-submit").click()  # same page, no reload
    ui.wait_visible(page, "confirmation-reference")
    assert ui.text(page, "confirmation-reference") == committed
    assert ui.visible(page, "current-user") and "Ada" in ui.text(page, "current-user")
    assert net.posts[0] == net.posts[-1]
    confirmed = [r for r in api.list(uw.ada) if r["status"] == "confirmed" and r["reference"] != "OLDPAST1"]
    assert [r["reference"] for r in confirmed] == [committed]
    page.goto(ui.url("/lookup"))
    T(page, "lookup-reference-input").fill(committed)
    T(page, "lookup-submit").click()
    ui.wait_visible(page, "reservation-detail")
    assert ui.text(page, "reservation-status") == "confirmed"
