"""Seating-change previews (stage-4 "Seating changes after a table closure"; ledger S4-001..S4-010,
A-35, A-36, A-38, A-39).

Expected plans come from tk.plan_oracle, an independent brute-force implementation of the spec's
feasibility rules and three-level objective, fed with the bookings as the API reports them.
"""
import random
from datetime import datetime, timedelta

import pytest

import tk
from tk import REP, REP2, MGR, expect

D = "2027-06-17"


def iso(local):
    return tk.exp_start(local, "Europe/Berlin")


def seed(ref, tables, local, party, user="u_ada"):
    s = {"id": f"id_{ref}", "reference": ref, "user_id": user, "restaurant_id": "r_rep",
         "starts_at_local": local, "party_size": party}
    if len(tables) == 1:
        s["table_id"] = tables[0]
    else:
        s["table_ids"] = list(tables)
    return s


def world(api, seeds, restaurants=(REP, REP2)):
    w = tk.World(api, tk.fixture(users=(tk.ADA, tk.BOB, MGR), restaurants=restaurants, reservations=seeds))
    w.mgr = w.tok("u_mgr")
    return w


def all_bookings(api, w, rid="r_rep"):
    out = []
    for uid in ("u_ada", "u_bob"):
        out += [r for r in api.list(w.tok(uid)) if r["restaurant_id"] == rid]
    return out


def expected_plan(api, w, table_id, frm, to, closures=(), rest=REP):
    """Oracle input from the current API state: considered = confirmed bookings overlapping [frm, to)."""
    f, t = tk.parse_ts(frm), tk.parse_ts(to)
    blocked = {table_id: [(f, t)]}
    for ct, cf, cto in closures:
        blocked.setdefault(ct, []).append((tk.parse_ts(cf), tk.parse_ts(cto)))
    considered = []
    for r in all_bookings(api, w, rest["id"]):
        if r["status"] != "confirmed":
            continue
        s, e = tk.parse_ts(r["starts_at"]), tk.parse_ts(r["ends_at"])
        if s < t and f < e:
            considered.append({"reference": r["reference"], "tables": tuple(r["table_ids"]), "party": r["party_size"],
                               "caps": r["accepted_terms"]["capacities"], "start": s, "end": e})
        else:
            for tb in r["table_ids"]:
                blocked.setdefault(tb, []).append((s, e))
    return considered, tk.plan_oracle(considered, tk.rep_options(rest), blocked)


def check_plan(resp, considered, oracle, table_id, frm, to):
    best, obj = oracle
    expect(resp, 201)
    j = resp.json
    assert isinstance(j["plan_id"], str) and 1 <= len(j["plan_id"]) <= 64
    assert type(j["restaurant_revision"]) is int
    c = j["closure"]
    assert c["table_id"] == table_id
    assert tk.parse_ts(c["from"]) == tk.parse_ts(frm) and tk.parse_ts(c["to"]) == tk.parse_ts(to), c  # A-39
    refs = sorted(b["reference"] for b in considered)
    assert [a["reference"] for a in j["assignments"]] == refs, "assignments: every considered booking, reference order"
    cur = {b["reference"]: b for b in considered}
    want = {ref: list(opt) for ref, opt in best.items()}
    got = {a["reference"]: a["table_ids"] for a in j["assignments"]}
    assert got == want, f"plan is not the optimum: got {got}, expected {want} (objective {obj})"
    for a in j["assignments"]:
        assert a["changed"] is (set(a["table_ids"]) != set(cur[a["reference"]]["tables"])), a
    assert j["moved_count"] == obj[0]
    assert j["unused_seats"] == obj[1]


def preview(api, w, table_id, frm_local, to_local, rid="r_rep", closures=(), rest=REP):
    frm, to = iso(frm_local), iso(to_local)
    considered, oracle = expected_plan(api, w, table_id, frm, to, closures, rest)
    r = api.replan(w.mgr, rid, {"table_id": table_id, "from": frm, "to": to})
    return r, considered, oracle, frm, to


# ---- fixed scenarios ---------------------------------------------------------------------

@pytest.mark.ledger("S4-005", "S4-006", "S4-007")
def test_single_move_to_best_ranked_exact_fit(api):
    w = world(api, [seed("RA0001", ["r_3"], f"{D}T19:00", 4)])
    r, cons, orc, f, t = preview(api, w, "r_3", f"{D}T18:00", f"{D}T21:00")
    assert orc[0] == {"RA0001": ("r_4",)}  # hand check: r_4 and r_1+r_2 leave 0 seats; r_4 ranks first
    check_plan(r, cons, orc, "r_3", f, t)


@pytest.mark.ledger("S4-003", "S4-005", "S4-006", "A-35")
def test_other_considered_bookings_stay_and_pair_used(api):
    w = world(api, [seed("RA0001", ["r_3"], f"{D}T19:00", 4), seed("RB0002", ["r_4"], f"{D}T19:30", 3, "u_bob")])
    r, cons, orc, f, t = preview(api, w, "r_3", f"{D}T18:00", f"{D}T21:00")
    assert orc[0] == {"RA0001": ("r_1", "r_2"), "RB0002": ("r_4",)}
    check_plan(r, cons, orc, "r_3", f, t)
    a = {x["reference"]: x for x in r.json["assignments"]}
    assert a["RB0002"]["changed"] is False and a["RA0001"]["changed"] is True


@pytest.mark.ledger("S4-005", "S4-006")
def test_large_party_needs_declared_pair(api):
    w = world(api, [seed("RA0001", ["r_6"], f"{D}T19:00", 7)])
    r, cons, orc, f, t = preview(api, w, "r_6", f"{D}T19:00", f"{D}T20:00")
    assert orc[0] == {"RA0001": ("r_3", "r_4")}
    check_plan(r, cons, orc, "r_6", f, t)


@pytest.mark.ledger("S4-003", "S4-005")
def test_fixed_bookings_outside_the_window_constrain(api):
    # closure 19:00-20:00; RC0003 on r_4 starts 20:00 (not considered, fixed) and overlaps RA0001's 19:00-21:00
    w = world(api, [seed("RA0001", ["r_3"], f"{D}T19:00", 4), seed("RC0003", ["r_4"], f"{D}T20:00", 2)])
    r, cons, orc, f, t = preview(api, w, "r_3", f"{D}T19:00", f"{D}T20:00")
    assert [b["reference"] for b in cons] == ["RA0001"]
    assert orc[0] == {"RA0001": ("r_1", "r_2")}
    check_plan(r, cons, orc, "r_3", f, t)


@pytest.mark.ledger("S4-005", "S4-006", "S3-023")
def test_capacity_under_each_bookings_own_accepted_terms(api):
    w = world(api, [seed("RA0001", ["r_3"], f"{D}T19:00", 4)])
    caps = {"r_1": 2, "r_2": 2, "r_3": 4, "r_4": 2, "r_5": 6, "r_6": 8}
    pol = tk.policy(D, slot=30, dur=120, hours=REP["opening_hours"], caps=caps)
    expect(api.publish(w.mgr, "r_rep", pol), 201)  # later policy shrinks r_4; RA0001 keeps policy-0 terms
    r, cons, orc, f, t = preview(api, w, "r_3", f"{D}T18:00", f"{D}T21:00")
    assert orc[0] == {"RA0001": ("r_4",)}
    check_plan(r, cons, orc, "r_3", f, t)


@pytest.mark.ledger("S4-009", "S4-008")
def test_no_feasible_plan_changes_nothing(api):
    # RA0001 seats 8: r_6 is being closed and r_3+r_4 is blocked by the fixed RX0009 (20:00, outside the window)
    w = world(api, [seed("RA0001", ["r_6"], f"{D}T19:00", 8), seed("RX0009", ["r_3"], f"{D}T20:00", 2)])
    before = all_bookings(api, w)
    rev = api.rrev(w.mgr, "r_rep", "r_1")
    r, cons, orc, f, t = preview(api, w, "r_6", f"{D}T19:00", f"{D}T20:00")
    assert orc == (None, None)
    expect(r, 409, "no_feasible_plan")
    assert all_bookings(api, w) == before
    assert api.rrev(w.mgr, "r_rep", "r_1") == rev


@pytest.mark.ledger("S4-008", "S4-010")
def test_preview_changes_nothing(api):
    w = world(api, [seed("RA0001", ["r_3"], f"{D}T19:00", 4)])
    before = all_bookings(api, w)
    hist = api.entries(w.ada, "RA0001")
    av = api.avail("r_rep", D, 2).json
    rev = api.rrev(w.mgr, "r_rep", "r_1")
    r, *_ = preview(api, w, "r_3", f"{D}T18:00", f"{D}T21:00")
    expect(r, 201)
    assert r.json["restaurant_revision"] == rev
    assert all_bookings(api, w) == before
    assert api.entries(w.ada, "RA0001") == hist
    assert api.avail("r_rep", D, 2).json == av, "a preview must not record a closure"
    expect(api.create(w.bob, tk.body("r_rep", "r_3", f"{D}T21:00", 2)), 201)


@pytest.mark.ledger("A-38", "S4-007")
def test_empty_plan(api):
    w = world(api, [])
    r, cons, orc, f, t = preview(api, w, "r_2", f"{D}T12:00", f"{D}T13:00")
    expect(r, 201)
    assert r.json["assignments"] == [] and r.json["moved_count"] == 0 and r.json["unused_seats"] == 0


@pytest.mark.ledger("S4-004", "S4-005", "S4-006")
@pytest.mark.parametrize("seed_no", range(10))
def test_random_scenarios_match_oracle(api, seed_no):
    rnd = random.Random(1000 + seed_no)
    options = tk.rep_options(REP)
    caps = {t["id"]: t["capacity"] for t in REP["tables"]}
    times = [f"{h:02d}:{m:02d}" for h in range(17, 21) for m in (0, 30)] + ["21:00"]
    placed = []  # (tables, start_minute)
    seeds = []
    tries = 0
    while len(seeds) < 6 and tries < 200:
        tries += 1
        opt = rnd.choice(options)
        hm = rnd.choice(times)
        start = int(hm[:2]) * 60 + int(hm[3:])
        if any(set(opt) & set(o) and abs(start - s) < 120 for o, s in placed):
            continue
        cap = sum(caps[t] for t in opt)
        party = rnd.randint(max(1, cap - 3), cap)
        placed.append((opt, start))
        seeds.append(seed(f"R{seed_no}{len(seeds):02d}{rnd.randint(100, 999)}X", list(opt), f"{D}T{hm}", party,
                          rnd.choice(["u_ada", "u_bob"])))
    w = world(api, seeds)
    closed = rnd.choice([t["id"] for t in REP["tables"]])
    r, cons, orc, f, t = preview(api, w, closed, f"{D}T19:00", f"{D}T20:00")
    if orc == (None, None):
        expect(r, 409, "no_feasible_plan")
    else:
        check_plan(r, cons, orc, closed, f, t)


@pytest.mark.ledger("S4-004")
def test_more_than_six_considered_may_hit_planning_limit(api):
    seeds = [seed(f"RL{i:04d}", [tid], f"{D}T19:00", 1) for i, tid in enumerate(["r_1", "r_2", "r_3", "r_4", "r_5"])]
    seeds += [seed("RL0005", ["r_6"], f"{D}T18:00", 1), seed("RL0006", ["r_6"], f"{D}T20:00", 1)]
    w = world(api, seeds)
    r, cons, orc, f, t = preview(api, w, "r_1", f"{D}T18:00", f"{D}T22:00")
    tk.expect_no_5xx(r)
    if r.status == 422:
        expect(r, 422, "planning_limit")
    else:
        check_plan(r, cons, orc, "r_1", f, t)


# ---- request rules -----------------------------------------------------------------------

@pytest.mark.ledger("S4-001", "A-36")
def test_replan_permissions_and_key(api):
    w = world(api, [])
    b = {"table_id": "r_1", "from": iso(f"{D}T19:00"), "to": iso(f"{D}T20:00")}
    expect(api.replan(None, "r_rep", b), 401, "unauthenticated")
    expect(api.replan(w.ada, "r_rep", b), 403, "forbidden")
    expect(api.replan(w.mgr, "r_nowhere", b), 404, "not_found")
    expect(api.replan(w.mgr, "r_rep", b, key=None), 400, "missing_idempotency_key")
    expect(api.replan(w.mgr, "r_rep", b, key="k" * 256), 422, "validation_failed")
    expect(api.replan(w.mgr, "r_rep", raw="nope"), 400, "malformed_request")
    key = tk.new_key()
    first = expect(api.replan(w.mgr, "r_rep", b, key=key), 201)
    again = api.replan(w.mgr, "r_rep", b, key=key)
    expect(again, 200)
    assert again.json == first
    expect(api.replan(w.mgr, "r_rep", {**b, "table_id": "r_2"}, key=key), 409, "idempotency_key_reuse")
    k2 = tk.new_key()
    expect(api.replan(w.mgr, "r_rep", {**b, "table_id": "zz"}, key=k2), 404, "not_found")
    expect(api.replan(w.mgr, "r_rep", b, key=k2), 201)


@pytest.mark.ledger("S4-002", "A-36")
@pytest.mark.parametrize("patch", [
    {"from": f"{D}T19:00:00"}, {"to": f"{D}T20:00"}, {"from": "not a time"}, {"from": 5},
    {"to": None}, "SWAP", "EQUAL", "NO_FROM", "NO_TO", "NO_TABLE", {"table_id": 7},
], ids=lambda p: p if isinstance(p, str) else "-".join(f"{k}={v!r}" for k, v in p.items()))
def test_replan_body_validation(api, patch):
    w = world(api, [])
    b = {"table_id": "r_1", "from": iso(f"{D}T19:00"), "to": iso(f"{D}T20:00")}
    if patch == "SWAP":
        b["from"], b["to"] = b["to"], b["from"]
    elif patch == "EQUAL":
        b["to"] = b["from"]
    elif patch == "NO_FROM":
        del b["from"]
    elif patch == "NO_TO":
        del b["to"]
    elif patch == "NO_TABLE":
        del b["table_id"]
    else:
        b.update(patch)
    expect(api.replan(w.mgr, "r_rep", b), 422, "validation_failed")


@pytest.mark.ledger("S4-002")
def test_replan_unknown_or_foreign_table_404(api):
    w = world(api, [])
    b = {"from": iso(f"{D}T19:00"), "to": iso(f"{D}T20:00")}
    expect(api.replan(w.mgr, "r_rep", {**b, "table_id": "zz"}), 404, "not_found")
    expect(api.replan(w.mgr, "r_rep", {**b, "table_id": "t_1"}), 404, "not_found")


@pytest.mark.ledger("A-39", "S4-002")
def test_closure_accepts_any_explicit_offset(api):
    w = world(api, [seed("RA0001", ["r_3"], f"{D}T19:00", 4)])
    frm, to = "2027-06-17T16:00:00Z", "2027-06-17T21:00:00+02:00"
    cons, orc = expected_plan(api, w, "r_3", frm, to)
    r = api.replan(w.mgr, "r_rep", {"table_id": "r_3", "from": frm, "to": to})
    check_plan(r, cons, orc, "r_3", frm, to)


# ---- restaurant revision -------------------------------------------------------------------

@pytest.mark.ledger("S4-010", "A-32")
def test_restaurant_revision_counts_exactly_the_specified_writes(api):
    w = world(api, [seed("RA0001", ["r_3"], f"{D}T19:00", 4)])
    m = w.mgr

    def rev():
        return api.rrev(m, "r_rep", "r_1")
    assert rev() == 0, "restaurant revision starts at 0 after reset (seeds do not count)"
    key = tk.new_key()
    b = tk.body("r_rep", "r_1", f"{D}T13:00", 2)
    made = expect(api.create(w.ada, b, key=key), 201)
    assert rev() == 1
    expect(api.create(w.ada, b, key=key), 200)                             # replay
    expect(api.create(w.ada, tk.body("r_rep", "r_1", f"{D}T13:15", 2)), 422, "not_on_slot_grid")  # failure
    expect(api.patch(w.ada, made["reference"], {"party_size": 2}), 200)  # no-op
    assert rev() == 1
    expect(api.patch(w.ada, made["reference"], {"party_size": 1}), 200)
    assert rev() == 2
    expect(api.cancel(w.ada, made["reference"]), 200)
    expect(api.cancel(w.ada, made["reference"]), 200)                    # repeated cancel
    assert rev() == 3
    expect(api.publish(m, "r_rep", tk.policy("2028-01-01", caps={t["id"]: 4 for t in REP["tables"]})), 201)
    expect(api.publish(m, "r_rep", {"effective_from": "bad"}), 422, "validation_failed")
    assert rev() == 4
    b1 = api.book(w.ada, "r_rep", "r_1", f"{D}T14:00", 2)
    b2 = api.book(w.ada, "r_rep", "r_2", f"{D}T14:00", 2)
    assert rev() == 6
    expect(api.moves(w.ada, {"moves": [{"reference": b1["reference"], "table_id": "r_2"},
                                       {"reference": b2["reference"], "table_id": "r_1"}]}), 201)
    assert rev() == 7, "a batch move counts once"
    expect(api.moves(w.ada, {"moves": [{"reference": b1["reference"]}]}), 201)  # no-op batch
    assert rev() == 7
    expect(api.series(w.ada, {"anchor_reference": b1["reference"], "count": 3, "interval_weeks": 1}), 201)
    assert rev() == 8, "a series adoption counts once"
    assert api.rrev(m, "r_rep2", "r_1") == 0, "restaurant revisions are per restaurant"
