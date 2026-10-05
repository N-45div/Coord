"""Gate S4-020 browser check: availability, confirmation and lookup screens reflect an applied seating plan.
Usage: uivenv python ui_s4.py http://127.0.0.1:PORT <shots-dir>"""
import os
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
import ui_s2 as u  # reuse helpers (api, login_ui, search, cell, tid, no_hscroll)

BASE, ART = u.BASE, u.ART
FIX = dict(u.FIX)
FIX["restaurants"] = [dict(u.FIX["restaurants"][0], manager_user_ids=["u_bob"])] + u.FIX["restaurants"][1:]
RES = []


def check(lid, cond, detail=""):
    RES.append(cond)
    print("PASS" if cond else "FAIL", lid, detail[:300], flush=True)


st, _ = u.api("POST", "/_test/reset", FIX)
bob = u.api("POST", "/auth/login", {"email": "bob@example.com", "password": "battery staple"})[1]["token"]
DATE = "2026-11-19"
with sync_playwright() as p:
    b = p.chromium.launch()
    for width in (1280, 375):
        ctx = b.new_context(viewport={"width": width, "height": 900})
        pg = ctx.new_page()
        u.login_ui(pg)
        pg.goto(BASE + "/")
        u.search(pg, "r_anker", DATE, 2)
        start = "19:00" if width == 1280 else "21:00"
        u.cell(pg, "t_2", start).click()
        u.tid(pg, "booking-form").wait_for(timeout=4000)
        u.tid(pg, "booking-submit").click()
        u.tid(pg, "confirmation").wait_for(timeout=5000)
        ref = u.tid(pg, "confirmation-reference").inner_text()
        check("S4-020", "Booth 2" in u.tid(pg, "confirmation-tables").inner_text(), f"@{width} booked on Booth 2")
        frm, to = f"{DATE}T{start}:00+01:00", f"{DATE}T{'20:30' if width == 1280 else '22:30'}:00+01:00"
        st, plan = u.api("POST", "/restaurants/r_anker/replans", {"table_id": "t_2", "from": frm, "to": to}, token=bob,
                         key=f"pv-{width}")
        st2, ap = u.api("POST", f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", {}, token=bob, key=f"ap-{width}")
        moved = [a for a in plan["assignments"] if a["reference"] == ref]
        check("S4-020", st == 201 and st2 == 201 and moved and moved[0]["changed"], f"@{width} plan applied: {plan}")
        new_tables = moved[0]["table_ids"] if moved else []
        labels = {"t_1": "Window 1", "t_2": "Booth 2", "t_3": "Garden 3", "t_4": "Bar 4"}
        want = [labels[t] for t in new_tables]
        u.tid(pg, "booking-submit").click()            # unchanged resubmit -> replay of the original booking
        pg.wait_for_timeout(1500)
        ct = u.tid(pg, "confirmation-tables").inner_text()
        check("S4-020", u.tid(pg, "confirmation-reference").inner_text() == ref and all(w in ct for w in want) and "Booth 2" not in ct,
              f"@{width} confirmation shows the reassigned tables {want}: {ct!r}")
        u.search(pg, "r_anker", DATE, 2)
        check("S4-020", u.cell(pg, "t_2", start).get_attribute("data-available") == "false", f"@{width} grid: closed Booth 2 unavailable")
        pg.goto(BASE + "/lookup")
        u.tid(pg, "lookup-reference-input").fill(ref)
        u.tid(pg, "lookup-submit").click()
        u.tid(pg, "reservation-detail").wait_for(timeout=4000)
        rt = u.tid(pg, "reservation-tables").inner_text()
        check("S4-020", all(w in rt for w in want) and "Booth 2" not in rt, f"@{width} lookup shows {want}: {rt!r}")
        check("S2-024", u.no_hscroll(pg), f"@{width} no horizontal scroll on lookup after replan")
        pg.screenshot(path=os.path.join(ART, f"s4-lookup-after-replan-{width}.png"), full_page=True)
        ctx.close()
    b.close()
print(f"SUMMARY pass={sum(RES)} fail={len(RES) - sum(RES)}")
sys.exit(0 if all(RES) else 1)
