"""Gate's independent black-box probe for tablekeeper stage 4 (spec stage-4.md + ledger 9c129ab only). Stdlib only.
Expected plans come from plan_oracle.py (independent brute force over the S4-006 objective).
Usage: py -3.12 probe_s4.py http://127.0.0.1:PORT [http://127.0.0.1:FRESH_PORT]"""
import datetime as dt
import http.client
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from plan_oracle import best_plan

BASE = urlparse(sys.argv[1])
BASE2 = urlparse(sys.argv[2]) if len(sys.argv) > 2 else None
RESULTS, FIVEXX, LOCK = [], [], threading.Lock()


class R:
    def __init__(self, status, raw):
        self.status, self.raw = status, raw
        try:
            self.json = json.loads(raw) if raw else None
        except Exception:
            self.json = None

    @property
    def code(self):
        try:
            return self.json["error"]["code"]
        except Exception:
            return None

    def __repr__(self):
        return f"<{self.status} {self.raw[:300]!r}>"


def call(method, path, body=None, token=None, key=None, base=None):
    b = base or BASE
    h = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    c = http.client.HTTPConnection(b.hostname, b.port, timeout=20)
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
    resp = c.getresponse()
    out = R(resp.status, resp.read())
    c.close()
    if out.status >= 500:
        with LOCK:
            FIVEXX.append((method, path, out.status))
    return out


def check(lid, cond, detail=""):
    RESULTS.append(("PASS" if cond else "FAIL", lid, detail))
    print("PASS" if cond else "FAIL", lid, detail[:160] if cond else detail[:500], flush=True)
    return cond


def note(lid, detail):
    RESULTS.append(("NOTE", lid, detail))
    print("NOTE", lid, detail, flush=True)


def expect(lid, r, status, code=None, what=""):
    return check(lid, r.status == status and (code is None or r.code == code), f"{what}: expected {status} {code or ''} got {r!r}")


KN = [0]


def k(tag="g4"):
    KN[0] += 1
    return f"{tag}-{KN[0]}-{time.time_ns()}"


ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HOURS = [{"weekday": d, "opens": "17:00", "closes": "23:00"} for d in ALL]
TABLES = [("t_1", 2), ("t_2", 4), ("t_3", 4), ("t_4", 6), ("t_5", 2), ("t_6", 8)]
PAIRS = [["t_1", "t_5"], ["t_2", "t_3"], ["t_1", "t_2"], ["t_4", "t_6"]]
TIDS = [t for t, _ in TABLES]
FIX = {
    "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"},
              {"id": "u_bob", "email": "bob@example.com", "password": "battery staple", "display_name": "Bob"},
              {"id": "u_mgr", "email": "mgr@example.com", "password": "manager pass", "display_name": "Mgr"},
              {"id": "u_mg2", "email": "mg2@example.com", "password": "manager two", "display_name": "Mg2"}],
    "restaurants": [
        {"id": "r_rp", "name": "Replan Hall", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120, "opening_hours": HOURS,
         "tables": [{"id": t, "label": t.upper(), "capacity": c} for t, c in TABLES],
         "combinable": PAIRS, "manager_user_ids": ["u_mgr"]},
        {"id": "r_o2", "name": "Other", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0, "opening_hours": HOURS,
         "tables": [{"id": "o_1", "label": "O1", "capacity": 4}, {"id": "o_2", "label": "O2", "capacity": 4}],
         "manager_user_ids": ["u_mg2"]},
    ],
    "reservations": [],
}
D1, D2, D3, D4, D5, D6 = "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17"


def login(e, p):
    r = call("POST", "/auth/login", {"email": e, "password": p})
    return r.json["token"] if r.status == 200 else None


def book(tok, tids, start, party, rid="r_rp", key=None):
    b = {"restaurant_id": rid, "starts_at_local": start, "party_size": party}
    if len(tids) == 1:
        b["table_id"] = tids[0]
    else:
        b["table_ids"] = tids
    return call("POST", "/reservations", b, token=tok, key=key or k())


def iso(date, hhmm):
    return f"{date}T{hhmm}:00+01:00"   # Berlin winter offset in November


def inst(s):
    return dt.datetime.fromisoformat(s)


def hist(tok, ref):
    r = call("GET", f"/reservations/{ref}/history", token=tok)
    return r.json.get("entries") if r.status == 200 else None


def run():
    expect("S1-007", call("POST", "/_test/reset", FIX), 204, what="reset")
    ada, bob, mgr, mg2 = (login("ada@example.com", "correct horse"), login("bob@example.com", "battery staple"),
                          login("mgr@example.com", "manager pass"), login("mg2@example.com", "manager two"))
    owners = {"ada": ada, "bob": bob}

    def preview(table, frm, to, tok=None, key=None, rid="r_rp"):
        return call("POST", f"/restaurants/{rid}/replans", {"table_id": table, "from": frm, "to": to},
                    token=tok or mgr, key=key or k())

    def rev():
        r = preview("t_6", iso("2030-01-03", "17:00"), iso("2030-01-03", "17:30"))
        return r.json.get("restaurant_revision") if r.status == 201 else f"ERR {r!r}"

    def apply(plan_id, tok=None, key=None, rid="r_rp"):
        return call("POST", f"/restaurants/{rid}/replans/{plan_id}/apply", {}, token=tok or mgr, key=key or k())

    def all_res():
        out = []
        for tok in owners.values():
            out += call("GET", "/reservations", token=tok).json["reservations"]
        return out

    def oracle_for(frm, to, table, closures):
        f0, t0 = inst(frm), inst(to)
        considered, fixed = [], []
        for x in all_res():
            if x["restaurant_id"] != "r_rp" or x["status"] != "confirmed":
                continue
            s, e = inst(x["starts_at"]), inst(x["ends_at"])
            row = {"reference": x["reference"], "party_size": x["party_size"], "table_ids": x["table_ids"],
                   "start": s, "end": e, "capacities": x["accepted_terms"]["capacities"]}
            (considered if (s < t0 and f0 < e) else fixed).append(row)
        cl = [{"table_id": c["table_id"], "from": inst(c["from"]), "to": inst(c["to"])} for c in closures] + \
             [{"table_id": table, "from": f0, "to": t0}]
        return best_plan(TIDS, PAIRS, considered, fixed, cl), considered

    # ------------------------------------------------------------- restaurant revision (S4-010)
    check("S4-010", rev() == 0, "revision 0 after reset")
    K1 = k()
    r1 = book(ada, ["t_2"], f"{D1}T19:00", 4, key=K1)
    check("S4-010", r1.status == 201 and rev() == 1, "create +1")
    book(ada, ["t_2"], f"{D1}T19:00", 4, key=K1)
    book(ada, ["t_2"], f"{D1}T19:30", 4)  # overlapping -> 409
    check("S4-010", rev() == 1, "replay and failed create do not increment")
    ref1 = r1.json["reference"]
    call("PATCH", f"/reservations/{ref1}", {"party_size": 4}, token=ada)
    check("S4-010", rev() == 1, "no-op PATCH does not increment")
    call("PATCH", f"/reservations/{ref1}", {"party_size": 3}, token=ada)
    check("S4-010", rev() == 2, "real PATCH +1")
    tmp = book(ada, ["t_5"], f"{D6}T21:00", 2).json["reference"]
    call("POST", f"/reservations/{tmp}/cancel", token=ada)
    call("POST", f"/reservations/{tmp}/cancel", token=ada)
    check("S4-010", rev() == 4, "create +1, cancel +1, repeat cancel 0")
    pol = {"effective_from": "2026-11-11", "slot_minutes": 30, "reservation_duration_minutes": 90,
           "cancellation_cutoff_minutes": 120, "opening_hours": HOURS,
           "capacities": {"t_1": 2, "t_2": 4, "t_3": 4, "t_4": 2, "t_5": 2, "t_6": 2}}
    KPOL = k()
    rp = call("POST", "/restaurants/r_rp/policies", pol, token=mgr, key=KPOL)
    call("POST", "/restaurants/r_rp/policies", pol, token=mgr, key=KPOL)
    check("S4-010", rp.status == 201 and rev() == 5, "policy publication +1, replay 0")
    # ------------------------------------------------------------- replan validation (S4-001/002, A-36)
    W = (iso(D1, "18:00"), iso(D1, "23:00"))
    expect("S4-001", call("POST", "/restaurants/r_rp/replans", {"table_id": "t_2", "from": W[0], "to": W[1]}, key=k()),
           401, "unauthenticated", "no token")
    expect("S4-001", preview("t_2", *W, tok=ada), 403, "forbidden", "non-manager")
    expect("S4-001", preview("t_2", *W, tok=mg2), 403, "forbidden", "manager of another restaurant")
    expect("S4-001", preview("t_2", *W, rid="r_nope"), 404, "not_found", "unknown restaurant")
    expect("S4-001", call("POST", "/restaurants/r_rp/replans", {"table_id": "t_2", "from": W[0], "to": W[1]}, token=mgr),
           400, "missing_idempotency_key", "no key")
    for what, b in [("no offset", {"table_id": "t_2", "from": f"{D1}T18:00:00", "to": W[1]}),
                    ("from == to", {"table_id": "t_2", "from": W[0], "to": W[0]}),
                    ("from > to", {"table_id": "t_2", "from": W[1], "to": W[0]}),
                    ("unparseable", {"table_id": "t_2", "from": "tomorrow", "to": W[1]}),
                    ("missing to", {"table_id": "t_2", "from": W[0]}),
                    ("missing table_id", {"from": W[0], "to": W[1]}),
                    ("table_id int", {"table_id": 2, "from": W[0], "to": W[1]})]:
        expect("S4-002", call("POST", "/restaurants/r_rp/replans", b, token=mgr, key=k()), 422, "validation_failed", what)
    expect("S4-002", preview("t_9", *W), 404, "not_found", "unknown table")
    expect("S4-002", preview("o_1", *W), 404, "not_found", "another restaurant's table")
    # ------------------------------------------------------------- scenario 1: own accepted terms + objective
    # bookings on D1 (policy above sets t_4/t_6 to 2 seats from 2026-11-11; bookings created now accept it)
    b4 = book(bob, ["t_4"], f"{D1}T19:00", 2)          # under new policy t_4 cap 2
    b3 = book(ada, ["t_1"], f"{D1}T18:00", 2)
    b2 = book(bob, ["t_3"], f"{D1}T19:30", 3)
    check("S4-005", all(x.status == 201 for x in (b4, b3, b2)), f"setup {b4!r} {b3!r} {b2!r}")
    check("S4-005", r1.json["accepted_terms"]["capacities"]["t_6"] == 8, "R1 accepted terms predate the policy (t_6 = 8)")
    before = {x["reference"]: x for x in all_res()}
    rv = rev()
    KPV = k()
    p1 = preview("t_2", *W, key=KPV)
    exp, cons = oracle_for(*W, "t_2", [])
    ok = p1.status == 201
    check("S4-007", ok and set(p1.json) >= {"plan_id", "restaurant_revision", "closure", "assignments", "moved_count",
                                            "unused_seats"} and p1.json["restaurant_revision"] == rv, f"preview shape {p1!r}")
    check("S4-007", ok and p1.json["closure"]["table_id"] == "t_2" and inst(p1.json["closure"]["from"]) == inst(W[0]) and
          inst(p1.json["closure"]["to"]) == inst(W[1]), "closure echo (A-39)")
    check("S4-006", ok and exp is not None and [(a["reference"], a["table_ids"], a["changed"]) for a in p1.json["assignments"]]
          == [(a["reference"], a["table_ids"], a["changed"]) for a in exp[0]] and p1.json["moved_count"] == exp[1] and
          p1.json["unused_seats"] == exp[2], f"plan equals oracle optimum (own accepted terms): got {p1.json} want {exp}")
    check("S4-003", ok and [a["reference"] for a in p1.json["assignments"]] == sorted(c["reference"] for c in cons),
          "assignments = every considered booking in reference order (A-35)")
    rp1 = preview("t_2", *W, key=KPV)
    check("S4-001", rp1.status == 200 and rp1.json == p1.json, "preview replay 200 identical")
    after = {x["reference"]: x for x in all_res()}
    av = call("GET", f"/availability?restaurant_id=r_rp&date={D1}&party_size=2").json
    check("S4-008", after == before and rev() == rv and any("t_2" in s["available_table_ids"] for s in av["slots"]
                                                              if s["starts_at_local"].endswith("17:00")),
          "preview changes nothing (bookings, revision, no closure)")
    # ------------------------------------------------------------- apply
    pid = p1.json["plan_id"] if ok else "x"
    expect("S4-011", apply(pid, tok=ada), 403, "forbidden", "non-manager apply")
    expect("S4-012", apply("nope-plan"), 404, "not_found", "unknown plan")
    KAP = k()
    a1 = apply(pid, key=KAP)
    ok = expect("S4-015", a1, 201, what="apply")
    if ok:
        check("S4-015", a1.json["plan_id"] == pid and a1.json["restaurant_revision"] == rv + 1 and
              [x["reference"] for x in a1.json["reservations"]] == [a["reference"] for a in p1.json["assignments"]],
              f"apply response {a1.json.get('restaurant_revision')} vs {rv + 1}")
        moved = {a["reference"]: a for a in p1.json["assignments"] if a["changed"]}
        for x in a1.json["reservations"]:
            b = before[x["reference"]]
            same = {f: x[f] for f in ("starts_at", "ends_at", "accepted_terms", "party_size", "reservation_id")} == \
                {f: b[f] for f in ("starts_at", "ends_at", "accepted_terms", "party_size", "reservation_id")}
            if x["reference"] in moved:
                tok = ada if x["reference"] in (ref1, b3.json["reference"]) else bob
                h = hist(tok, x["reference"])
                check("S4-017", same and x["table_ids"] == moved[x["reference"]]["table_ids"] and x["revision"] == b["revision"] + 1
                      and h and h[-1]["event"] == "reassigned" and h[-1].get("plan_id") == pid and
                      h[-1]["changes"] == [{"field": "table_ids", "from": b["table_ids"], "to": x["table_ids"]}] and
                      h[-1].get("revision") == x["revision"], f"moved {x['reference']}: {h[-1] if h else h}")
            else:
                check("S4-017", same and x["revision"] == b["revision"] and x["table_ids"] == b["table_ids"],
                      f"unmoved {x['reference']} unchanged")
        check("S4-010", rev() == rv + 1, "apply +1 once for the whole plan")
        ra = apply(pid, key=KAP)
        check("S4-014", ra.status == 200 and ra.json == a1.json, "apply replay 200 original")
        expect("S4-014", apply(pid), 409, "plan_already_applied", "apply under another key")
        # closure effects
        av = call("GET", f"/availability?restaurant_id=r_rp&date={D1}&party_size=2&explain=true").json
        s20 = [s for s in av["slots"] if s["starts_at_local"].endswith("20:00")][0]
        s17 = [s for s in av["slots"] if s["starts_at_local"].endswith("17:00")][0]
        e2 = [e for e in s20["explain"] if e["table_id"] == "t_2"][0]
        check("S4-018", "t_2" not in s20["available_table_ids"] and
              not any("t_2" in o["table_ids"] for o in s20.get("available_options", [])) and
              e2["rules"][1] == {"rule": "no_overlap", "holds": False} and e2["available"] is False,
              f"closure excluded from availability/options/explain: {e2}")
        check("S4-018", "t_2" not in s17["available_table_ids"], "17:00 slot (ends 18:30) overlaps the closure")
        expect("S4-018", book(ada, ["t_2"], f"{D1}T21:00", 2), 409, "table_unavailable", "create on closed table")
        expect("S4-018", book(ada, ["t_2", "t_3"], f"{D1}T21:30", 2), 409, "table_unavailable", "pair containing closed table")
        expect("S4-018", book(ada, ["t_1", "t_2"], f"{D1}T21:30", 2), 409, "table_unavailable",
               "pair whose SECOND member is the closed table")
        expect("S4-018", call("PATCH", f"/reservations/{b3.json['reference']}", {"table_id": "t_2"}, token=ada), 409,
               "table_unavailable", "PATCH onto closed table")
        r_ok = book(ada, ["t_2"], f"{D2}T19:00", 2)
        check("S4-018", r_ok.status == 201, "closure does not affect another day")
    # ------------------------------------------------------------- stale plan, other restaurant, concurrency
    W2 = (iso(D2, "18:00"), iso(D2, "23:00"))
    p2 = preview("t_2", *W2)
    book(bob, ["t_5"], f"{D3}T19:00", 2)
    rv2 = rev()
    expect("S4-013", apply(p2.json["plan_id"]), 409, "stale_plan", "intervening booking invalidates")
    check("S4-013", rev() == rv2 and any(x["table_ids"] == ["t_2"] and x["starts_at_local"] == f"{D2}T19:00" for x in all_res()),
          "stale apply changed nothing")
    p3 = preview("t_2", *W2)
    po = preview("o_1", iso(D2, "18:00"), iso(D2, "20:00"), tok=mg2, rid="r_o2")
    ao = apply(po.json["plan_id"], tok=mg2, rid="r_o2")
    check("S4-013", ao.status == 201, f"apply at r_o2 {ao!r}")
    expect("S4-012", apply(po.json["plan_id"]), 404, "not_found", "plan of another restaurant via r_rp path")
    bar = threading.Barrier(6)

    def w(_):
        bar.wait()
        return apply(p3.json["plan_id"])
    with ThreadPoolExecutor(6) as ex:
        rs = list(ex.map(w, range(6)))
    sts = sorted(x.status for x in rs)
    check("S4-016", sts.count(201) == 1 and sts.count(409) == 5 and all(x.code == "plan_already_applied" for x in rs if x.status == 409),
          f"closure at another restaurant does not invalidate; concurrent applies -> one 201: {sts}")
    # ------------------------------------------------------------- no feasible plan
    big = book(ada, ["t_6"], f"{D4}T19:00", 2)  # under policy t_6 cap 2
    book(bob, ["t_4"], f"{D4}T19:00", 2)
    book(bob, ["t_1"], f"{D4}T19:00", 2)
    book(bob, ["t_2"], f"{D4}T19:00", 2)
    book(bob, ["t_3"], f"{D4}T19:00", 2)
    book(bob, ["t_5"], f"{D4}T19:00", 2)
    rv4 = rev()
    W4 = (iso(D4, "18:00"), iso(D4, "23:00"))
    exp4, _ = oracle_for(*W4, "t_6", [])
    r = preview("t_6", *W4)
    check("S4-009", exp4 is None and r.status == 409 and r.code == "no_feasible_plan" and rev() == rv4,
          f"no feasible plan: oracle {exp4} got {r!r}")
    # ------------------------------------------------------------- tie-break by rank vector (scenario 2)
    s5 = book(ada, ["t_2"], f"{D5}T19:00", 4)
    W5 = (iso(D5, "18:00"), iso(D5, "22:00"))
    exp5, _ = oracle_for(*W5, "t_2", [])
    r = preview("t_2", *W5)
    check("S4-006", r.status == 201 and exp5 and [a["table_ids"] for a in r.json["assignments"]] == [a["table_ids"] for a in exp5[0]]
          and r.json["unused_seats"] == exp5[2], f"rank tie-break: got {r.json} want {exp5}")
    # ------------------------------------------------------------- unused seats beat rank (scenario 3, policy-0 date)
    D0 = "2026-11-05"
    s7 = book(ada, ["t_2"], f"{D0}T19:00", 4)
    book(bob, ["t_3"], f"{D0}T19:00", 2)
    W0 = (iso(D0, "18:00"), iso(D0, "22:00"))
    exp0, _ = oracle_for(*W0, "t_2", [])
    r = preview("t_2", *W0)
    mine = [a for a in (r.json or {}).get("assignments", []) if a["reference"] == s7.json.get("reference")]
    check("S4-006", r.status == 201 and exp0 and mine and mine[0]["table_ids"] == ["t_1", "t_5"] and
          [a["table_ids"] for a in r.json["assignments"]] == [a["table_ids"] for a in exp0[0]] and r.json["unused_seats"] == exp0[2],
          f"fewest unused seats wins over lower rank (pair t_1+t_5, not t_4): got {r.json} want {exp0}")
    # ------------------------------------------------------------- series amend (S4-021..029) + replan of occurrences
    A0 = book(ada, ["t_3"], f"{D6}T19:00", 2).json
    S = call("POST", "/series", {"anchor_reference": A0["reference"], "count": 4, "interval_weeks": 1}, token=ada, key=k()).json
    sid = S.get("series_id")
    occ = [o["reference"] for o in S.get("occurrences", [])]
    expect("S4-021", call("POST", f"/series/{sid}/amend", {"expected_revision": 1, "from_index": 1, "local_time": "20:00"}, key=k()),
           401, "unauthenticated", "amend no token")
    expect("S4-021", call("POST", f"/series/{sid}/amend", {"expected_revision": 1, "from_index": 1, "local_time": "20:00"},
                          token=bob, key=k()), 404, "not_found", "amend another owner's series")
    expect("S4-021", call("POST", "/series/nope/amend", {"expected_revision": 1, "from_index": 1, "local_time": "20:00"},
                          token=ada, key=k()), 404, "not_found", "unknown series")
    expect("S4-021", call("POST", f"/series/{sid}/amend", {"expected_revision": 1, "from_index": 1, "local_time": "20:00"},
                          token=ada), 400, "missing_idempotency_key", "amend no key")
    for what, b in [("from_index 4", {"from_index": 4}), ("from_index -1", {"from_index": -1}), ("from_index bool", {"from_index": True}),
                    ("local_time 24:00", {"local_time": "24:00"}), ("local_time 8:00", {"local_time": "8:00"}),
                    ("local_time seconds", {"local_time": "20:00:00"}), ("local_time int", {"local_time": 20}),
                    ("revision 0", {"expected_revision": 0}), ("revision bool", {"expected_revision": True}),
                    ("revision string", {"expected_revision": "1"}), ("missing local_time", {"local_time": None})]:
        body = {"expected_revision": 1, "from_index": 1, "local_time": "20:00", **b}
        body = {kk: v for kk, v in body.items() if v is not None}
        expect("S4-022", call("POST", f"/series/{sid}/amend", body, token=ada, key=k()), 422, "validation_failed", what)
    expect("S4-023", call("POST", f"/series/{sid}/amend", {"expected_revision": 9, "from_index": 1, "local_time": "22:00"},
                          token=ada, key=k()), 409, "stale_revision", "stale before validation (22:00 would end after close)")
    rv6 = rev()
    revs_before = {o: call("GET", f"/reservations/{o}", token=ada).json["revision"] for o in occ}
    KAM = k()
    am = call("POST", f"/series/{sid}/amend", {"expected_revision": 1, "from_index": 1, "local_time": "20:00", "x": 1},
              token=ada, key=KAM)
    ok = am.status == 201
    if ok:
        oc = am.json["occurrences"]
        check("S4-024", [o["reservation"]["starts_at_local"][11:] for o in oc] == ["19:00", "20:00", "20:00", "20:00"] and
              [o["reservation"]["starts_at_local"][:10] for o in oc] == [o["reservation"]["starts_at_local"][:10] for o in S["occurrences"]],
              "occurrences >= from_index moved to 20:00 on their scheduled dates")
        check("S4-027", am.json["revision"] == 2 and all(o["exception"] is False for o in oc) and
              [o["reservation"]["revision"] for o in oc] == [revs_before[occ[0]]] + [revs_before[o] + 1 for o in occ[1:]] and
              rev() == rv6 + 1, f"series rev +1, occurrence revs +1, no exceptions, restaurant rev +1 ({am.json['revision']})")
        h = hist(ada, occ[2])
        check("S4-027", h and h[-1]["event"] == "changed" and h[-1]["changes"] == [
            {"field": "starts_at_local", "from": S["occurrences"][2]["reservation"]["starts_at_local"],
             "to": S["occurrences"][2]["reservation"]["starts_at_local"][:11] + "20:00"}], f"changed entry: {h[-1] if h else h}")
        ram = call("POST", f"/series/{sid}/amend", {"expected_revision": 1, "from_index": 1, "local_time": "20:00", "x": 1},
                   token=ada, key=KAM)
        check("S4-028", ram.status == 200 and ram.json == am.json, "amend replay 200 original")
        rv7 = rev()
        noop = call("POST", f"/series/{sid}/amend", {"expected_revision": 2, "from_index": 1, "local_time": "20:00"}, token=ada, key=k())
        check("S4-027", noop.status == 201 and noop.json["revision"] == 2 and rev() == rv7, "all-no-op amend changes no revision")
        # exceptions and cancelled are excluded
        call("PATCH", f"/reservations/{occ[2]}", {"party_size": 3}, token=ada)       # exception, series rev 3
        call("POST", f"/reservations/{occ[3]}/cancel", token=ada)                     # series rev 4
        g = call("GET", f"/series/{sid}", token=ada).json
        am2 = call("POST", f"/series/{sid}/amend", {"expected_revision": g["revision"], "from_index": 0, "local_time": "21:00"},
                   token=ada, key=k())
        oc = am2.json.get("occurrences", []) if am2.status == 201 else []
        check("S4-024", am2.status == 201 and [o["reservation"]["starts_at_local"][11:] for o in oc] == ["21:00", "21:00", "20:00", "20:00"],
              f"exception and cancelled occurrences excluded: {[o['reservation']['starts_at_local'] for o in oc]}")
        # conflict -> table_unavailable, nothing changes
        g = call("GET", f"/series/{sid}", token=ada).json
        d1 = g["occurrences"][1]["reservation"]["starts_at_local"][:10]
        book(bob, ["t_3"], f"{d1}T17:30", 2)
        h_before = hist(ada, occ[1])
        rv8 = rev()
        r = call("POST", f"/series/{sid}/amend", {"expected_revision": g["revision"], "from_index": 0, "local_time": "18:00"},
                 token=ada, key=k())
        expect("S4-026", r, 409, "table_unavailable", "amend conflicts with bob")
        check("S4-026", hist(ada, occ[1]) == h_before and rev() == rv8 and
              call("GET", f"/series/{sid}", token=ada).json["revision"] == g["revision"], "failed amend changes nothing")
        r = call("POST", f"/series/{sid}/amend", {"expected_revision": g["revision"], "from_index": 0, "local_time": "22:00"},
                 token=ada, key=k())
        expect("S4-025", r, 422, "outside_opening_hours", "22:00 + 90 min ends after 23:00")
        # concurrent amends from the same revision
        g = call("GET", f"/series/{sid}", token=ada).json
        bar2 = threading.Barrier(6)

        def w2(i):
            bar2.wait()
            return call("POST", f"/series/{sid}/amend", {"expected_revision": g["revision"], "from_index": 0,
                                                         "local_time": "19:30" if i % 2 else "20:30"}, token=ada, key=k())
        with ThreadPoolExecutor(6) as ex:
            rs = list(ex.map(w2, range(6)))
        sts = sorted(x.status for x in rs)
        check("S4-029", sts.count(201) == 1 and all(x.code == "stale_revision" for x in rs if x.status == 409),
              f"concurrent amends from one revision: {sts}")
        # replan moves a series occurrence: flags/dates/terms kept, series rev +1
        g = call("GET", f"/series/{sid}", token=ada).json
        o1 = g["occurrences"][1]["reservation"]
        dd = o1["starts_at_local"][:10]
        pr = preview("t_3", iso(dd, "17:00"), iso(dd, "23:00"))
        ap = apply(pr.json["plan_id"]) if pr.status == 201 else pr
        g2 = call("GET", f"/series/{sid}", token=ada).json
        n1 = g2["occurrences"][1]
        check("S4-019", ap.status == 201 and n1["reservation"]["table_ids"] != ["t_3"] and n1["exception"] == g["occurrences"][1]["exception"]
              and n1["reservation"]["starts_at_local"] == o1["starts_at_local"] and
              n1["reservation"]["accepted_terms"] == o1["accepted_terms"] and g2["revision"] == g["revision"] + 1,
              f"replan moved occurrence: {n1['reservation']['table_ids']}, series rev {g['revision']}->{g2['revision']}")
        # amend keeps the replan-moved table set (S4-024)
        am3 = call("POST", f"/series/{sid}/amend", {"expected_revision": g2["revision"], "from_index": 1, "local_time": "17:00"},
                   token=ada, key=k())
        cur = n1["reservation"]
        new_s = inst(cur["starts_at"]).replace(hour=17, minute=0)
        new_e = new_s + (inst(cur["ends_at"]) - inst(cur["starts_at"]))
        clash = [x["reference"] for x in all_res() if x["reference"] != cur["reference"] and x["status"] == "confirmed"
                 and set(x["table_ids"]) & set(cur["table_ids"]) and inst(x["starts_at"]) < new_e and new_s < inst(x["ends_at"])]
        if clash:
            check("S4-024", am3.status == 409 and am3.code == "table_unavailable",
                  f"amend after replan: moved table {cur['table_ids']} is taken by {clash} at 17:00 -> 409 ({am3!r})")
        else:
            check("S4-024", am3.status == 201 and am3.json["occurrences"][1]["reservation"]["table_ids"] == cur["table_ids"],
                  f"amend after replan keeps the replan-moved tables {cur['table_ids']}: {am3!r}")
    # ------------------------------------------------------------- export / import round trip
    e = call("GET", "/_test/export")
    snap = {"res": sorted(all_res(), key=lambda x: x["reference"]), "rev": rev()}
    call("POST", "/_test/reset", FIX)
    expect("S4-030", call("POST", "/_test/import", e.json), 204, what="stage-4 import")
    check("S4-030", sorted(all_res(), key=lambda x: x["reference"]) == snap["res"] and rev() == snap["rev"],
          "bookings and restaurant revision round-trip")
    ra = apply(pid, key=KAP)
    check("S4-030", ra.status == 200 and ra.json == a1.json, "applied-plan receipt survives import")
    expect("S4-030", apply(pid), 409, "plan_already_applied", "applied state survives import")
    r = book(ada, ["t_2"], f"{D1}T21:00", 2)
    expect("S4-030", r, 409, "table_unavailable", "closure survives import")
    if BASE2:
        expect("S4-030", call("POST", "/_test/import", e.json, base=BASE2), 204, what="import into fresh instance")


if __name__ == "__main__":
    t0 = time.monotonic()
    try:
        run()
    except Exception as exc:  # noqa
        import traceback
        traceback.print_exc()
        RESULTS.append(("FAIL", "PROBE", f"probe crashed: {exc!r}"))
    check("S1-006", not FIVEXX, f"5xx: {FIVEXX[:5]}")
    fails = [x for x in RESULTS if x[0] == "FAIL"]
    print(f"SUMMARY pass={sum(1 for x in RESULTS if x[0] == 'PASS')} fail={len(fails)} "
          f"note={sum(1 for x in RESULTS if x[0] == 'NOTE')} {time.monotonic() - t0:.1f}s")
    for f in fails:
        print("FAILED", f[1], f[2][:300])
    sys.exit(1 if fails else 0)
