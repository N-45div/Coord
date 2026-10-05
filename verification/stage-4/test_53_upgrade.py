"""Upgrade into stage 4 from the team's stage-1..3 services (stage-4 last paragraph; ledger S4-030).

Needs TK_STAGE1_BASE_URL / TK_STAGE2_BASE_URL / TK_STAGE3_BASE_URL (candidate.py --with-stageN).
Stage-1/2 exports carry no managers (introduced in stage 3), so replans are exercised on the stage-3
export; series amendments are exercised on every source.
"""
import os

import pytest

import tk
from tk import REP, MGR, expect
from test_50_replan import D, iso, expected_plan, check_plan

SOURCES = [(n, os.environ.get(f"TK_STAGE{n}_BASE_URL", "").rstrip("/")) for n in (1, 2, 3)]


class _W:
    """Minimal World stand-in holding tokens that came from the source service."""

    def __init__(self, toks):
        self._t = toks

    def tok(self, uid):
        return self._t[uid]


@pytest.mark.ledger("S4-030", "S3-046", "S1-088")
@pytest.mark.parametrize("n,url", SOURCES, ids=[f"stage{s[0]}" for s in SOURCES])
def test_import_older_export_then_replan_and_amend(api, n, url):
    if not url:
        pytest.skip(f"TK_STAGE{n}_BASE_URL not set")
    src = tk.Api(url)
    try:
        src.reset(tk.fixture(users=(tk.ADA, tk.BOB, MGR), restaurants=(REP,)))
        ada = src.token(tk.ADA["email"], tk.ADA["password"])
        bob = src.token(tk.BOB["email"], tk.BOB["password"])
        key, b = tk.new_key(), tk.body("r_rep", "r_3", f"{D}T19:00", 4)
        o = expect(src.create(ada, b, key=key), 201)
        series = None
        if n == 3:
            series = expect(src.series(ada, {"anchor_reference": o["reference"], "count": 4, "interval_weeks": 1}), 201)
            refs = [x["reference"] for x in series["occurrences"]]
            expect(src.patch(ada, refs[1], {"starts_at_local": "2027-06-24T20:00"}), 200)  # moved -> exception
            expect(src.cancel(ada, refs[2]), 200)
        exported = src.export()
    finally:
        src.close()
    api.reset(tk.fixture(users=(tk.CY,), restaurants=(tk.HARBOR,)))
    expect(api.import_(exported), 204)
    r = api.create(ada, b, key=key)
    expect(r, 200)
    assert r.json == o, "original booking retry must return the original response after the upgrade"
    if series is None:
        series = expect(api.series(ada, {"anchor_reference": o["reference"], "count": 4, "interval_weeks": 1}), 201)
    sid = series["series_id"]
    g = expect(api.get_series(ada, sid), 200)
    amended = api.amend(ada, sid, {"expected_revision": g["revision"], "from_index": 0, "local_time": "19:30"})
    expect(amended, 201)
    occ = amended.json["occurrences"]
    if n == 3:
        assert [x["reservation"]["starts_at_local"][11:] for x in occ] == ["19:30", "20:00", "19:00", "19:30"]
        assert occ[1]["exception"] is True and occ[2]["reservation"]["status"] == "cancelled"
    else:
        assert all(x["reservation"]["starts_at_local"][11:] == "19:30" for x in occ)
    if n == 3:
        mgr = api.token(MGR["email"], MGR["password"])
        w = _W({"u_ada": ada, "u_bob": bob, "u_mgr": mgr})
        frm, to = iso(f"{D}T18:00"), iso(f"{D}T21:00")
        cons, orc = expected_plan(api, w, "r_3", frm, to)
        p = api.replan(mgr, "r_rep", {"table_id": "r_3", "from": frm, "to": to})
        check_plan(p, cons, orc, "r_3", frm, to)
        expect(api.apply(mgr, "r_rep", p.json["plan_id"]), 201)
        assert api.get_ok(ada, o["reference"])["table_ids"] == list(orc[0][o["reference"]])
