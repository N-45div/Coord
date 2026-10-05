"""Upgrade into stage 3 from the team's stage-1 and stage-2 services (stage-3 "Recurring reservations"
last paragraph; ledger S3-046, A-31, S3-024).

Needs TK_STAGE1_BASE_URL and/or TK_STAGE2_BASE_URL (candidate.py --with-stage1 / --with-stage2).
"""
import os

import pytest

import tk
from tk import THU, expect

SOURCES = [("stage1", os.environ.get("TK_STAGE1_BASE_URL", "").rstrip("/")),
           ("stage2", os.environ.get("TK_STAGE2_BASE_URL", "").rstrip("/"))]


@pytest.mark.ledger("S3-046", "A-31", "S3-024", "S2-026", "S1-088")
@pytest.mark.parametrize("name,url", SOURCES, ids=[s[0] for s in SOURCES])
def test_import_older_export_then_adopt(api, name, url):
    if not url:
        pytest.skip(f"TK_{name.upper()}_BASE_URL not set")
    src = tk.Api(url)
    try:
        src.reset(tk.fixture())
        ada = src.token(tk.ADA["email"], tk.ADA["password"])
        k1, b1 = tk.new_key(), tk.body("r_anker", "t_2", f"{THU}T19:00", 3)
        o1 = expect(src.create(ada, b1, key=k1), 201)
        k2, b2 = tk.new_key(), tk.body("r_anker", "t_1", f"{THU}T19:00", 2)
        o2 = expect(src.create(ada, b2, key=k2), 201)
        expect(src.cancel(ada, o2["reference"]), 200)
        exported = src.export()
    finally:
        src.close()
    api.reset(tk.fixture(users=(tk.CY,), restaurants=(tk.HARBOR,)))
    expect(api.import_(exported), 204)
    # sessions and original retries remain valid; replays return the original pre-stage-3 bodies
    r = api.create(ada, b1, key=k1)
    expect(r, 200)
    assert r.json == o1
    # imported bookings: revision 1, policy-0 terms; history synthesised (A-31)
    a = api.get_ok(ada, o1["reference"])
    tk.assert_res(a, tk.ANKER, "t_2", f"{THU}T19:00", 3, "confirmed")
    assert a["revision"] == 1
    tk.assert_terms(a["accepted_terms"], tk.terms0(tk.ANKER))
    es = api.entries(ada, o1["reference"])
    assert [e["event"] for e in es] == ["created"]
    assert es[0]["changes"] == [{"field": "table_id", "from": None, "to": "t_2"},
                                {"field": "starts_at_local", "from": None, "to": f"{THU}T19:00"},
                                {"field": "party_size", "from": None, "to": 3}]
    c = api.get_ok(ada, o2["reference"])
    assert c["status"] == "cancelled"
    ec = api.entries(ada, o2["reference"])
    assert [e["event"] for e in ec] == ["created", "cancelled"] and ec[-1]["changes"] == []
    assert c["revision"] == ec[-1]["revision"]
    # adoption works on an imported reservation
    s = api.series(ada, {"anchor_reference": o1["reference"], "count": 3, "interval_weeks": 1})
    expect(s, 201)
    assert s.json["occurrences"][0]["reservation"] == a
    assert [o["reservation"]["starts_at_local"] for o in s.json["occurrences"]] == \
        [f"{THU}T19:00", f"{tk.THU2}T19:00", "2027-07-01T19:00"]
