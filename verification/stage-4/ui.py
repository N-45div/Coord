"""Browser helpers (Playwright, sync API) for the stage-2 UI checks.

Only the data-testid hooks named in stage-2.md are relied on; everything else about the
markup is the team's choice.
"""
import json
import os
import re
import time

import tk

SHOTS = os.environ.get("TK_SCREENSHOT_DIR", "")
WAIT = 8000  # ms


def T(page, testid):
    return page.get_by_test_id(testid)


def url(path):
    return tk.BASE_URL + path


def present(page, testid):
    return T(page, testid).count() > 0


def visible(page, testid):
    loc = T(page, testid)
    return loc.count() > 0 and loc.first.is_visible()


def wait_visible(page, testid, timeout=WAIT):
    T(page, testid).first.wait_for(state="visible", timeout=timeout)


def wait_gone(page, testid, timeout=WAIT):
    """'Present only when there is one' (A-26): absent from the DOM."""
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        if T(page, testid).count() == 0:
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"{testid} still present in the DOM")


def text(page, testid):
    return T(page, testid).first.inner_text().strip()


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"{name}.png"), full_page=True)


def nav(page, path):
    """Navigate like a user: follow an in-app link to `path` when one is visible, else load the URL."""
    link = page.locator(f'a[href="{path}"]')
    for i in range(link.count()):
        if link.nth(i).is_visible():
            link.nth(i).click()
            page.wait_for_load_state()
            return
    page.goto(url(path))


def login(page, email, password):
    page.goto(url("/login"))
    T(page, "login-email").fill(email)
    T(page, "login-password").fill(password)
    T(page, "login-submit").click()
    wait_visible(page, "current-user")


def search(page, rid, date, party, goto=True):
    if goto:
        page.goto(url("/"))
    T(page, "restaurant-select").select_option(rid)
    T(page, "date-input").fill(date)
    T(page, "party-size-input").fill(str(party))
    T(page, "search-button").click()


def cell_id(tables, local):
    hm = local[11:16]
    if isinstance(tables, (list, tuple)):
        return f"slot-{'+'.join(tables)}-{hm}" if len(tables) > 1 else f"slot-{tables[0]}-{hm}"
    return f"slot-{tables}-{hm}"


def cells(page):
    """{testid: data-available} for every slot cell currently in the DOM."""
    return page.evaluate("""() => {
        const out = {};
        for (const el of document.querySelectorAll('[data-testid^="slot-"]')) {
            out[el.getAttribute('data-testid')] = el.getAttribute('data-available');
        }
        return out;
    }""")


def wait_cell(page, testid, available, timeout=WAIT):
    want = "true" if available else "false"
    deadline = time.monotonic() + timeout / 1000
    last = None
    while time.monotonic() < deadline:
        loc = T(page, testid)
        if loc.count():
            last = loc.first.get_attribute("data-available")
            if last == want:
                return
        page.wait_for_timeout(100)
    raise AssertionError(f"{testid}: data-available={last!r}, expected {want!r}")


def expected_cells(api, rest, date, party, pairs=True):
    """Expected {testid: 'true'/'false'} from GET /availability (stage-2 grid rules, A-21)."""
    out = {}
    for s in api.slots(rest["id"], date, party):
        hm = s["starts_at_local"][11:16]
        for t in rest["tables"]:
            out[f"slot-{t['id']}-{hm}"] = "true" if t["id"] in s["available_table_ids"] else "false"
        if pairs:
            avail_pairs = [o["table_ids"] for o in s.get("available_options", []) if len(o["table_ids"]) == 2]
            for p in rest.get("combinable", []):
                out[f"slot-{p[0]}+{p[1]}-{hm}"] = "true" if p in avail_pairs else "false"
    return out


class Net:
    """Records POST /reservations requests (headers + body) seen by the browser."""

    def __init__(self, page):
        self.posts = []
        page.on("request", self._on)

    def _on(self, req):
        if req.method == "POST" and re.search(r"/reservations(\?|$)", req.url):
            self.posts.append({"key": req.header_value("idempotency-key"),
                               "body": json.loads(req.post_data) if req.post_data else None})


def no_hscroll(page):
    return page.evaluate("""() => {
        const d = document.documentElement, b = document.body;
        return {doc: d.scrollWidth, body: b ? b.scrollWidth : 0, inner: window.innerWidth};
    }""")
