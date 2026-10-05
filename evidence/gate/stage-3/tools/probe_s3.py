"""Gate's independent black-box probe for tablekeeper stage 3 (spec stage-3.md + ledger 309ed4d only). Stdlib only.
Usage: py -3.12 probe_s3.py http://127.0.0.1:PORT [http://127.0.0.1:FRESH_PORT]
PASS/FAIL tagged with ledger ids; NOTE lines record readings of Coordinator decisions (A-27..A-34)."""
import datetime as dt
import http.client
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

BASE = urlparse(sys.argv[1])
BASE2 = urlparse(sys.argv[2]) if len(sys.argv) > 2 else None
RESULTS, FIVEXX, LOCK = [], [], threading.Lock()
RFC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")


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
        return f"<{self.status} {self.raw[:260]!r}>"


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
    print("PASS" if cond else "FAIL", lid, detail[:150] if cond else detail[:420], flush=True)
    return cond


def note(lid, detail):
    RESULTS.append(("NOTE", lid, detail))
    print("NOTE", lid, detail, flush=True)


def expect(lid, r, status, code=None, what=""):
    return check(lid, r.status == status and (code is None or r.code == code),
                 f"{what}: expected {status} {code or ''} got {r!r}")


KN = [0]


def k(tag="g3"):
    KN[0] += 1
    return f"{tag}-{KN[0]}-{time.time_ns()}"


# ------------------------------------------------------------------------------------------- fixture
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def ist_slot(minutes_ahead):
    t = dt.datetime.now(IST) + dt.timedelta(minutes=minutes_ahead)
    t = t.replace(second=0, microsecond=0)
    t += dt.timedelta(minutes=(15 - t.minute % 15) % 15)
    if t.hour * 60 + t.minute > 23 * 60 + 30:
        t = (t + dt.timedelta(days=1)).replace(hour=0, minute=30)
    return t.strftime("%Y-%m-%dT%H:%M")


TODAY_IST = dt.datetime.now(IST).strftime("%Y-%m-%d")
NEAR60, NEAR75 = ist_slot(60), ist_slot(75)
THU1, THU2, THU3, THU4, THU5, THU6 = "2026-11-12", "2026-11-19", "2026-11-26", "2026-12-03", "2026-12-10", "2026-12-17"
OLD = "2025-12-04"
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HOURS0 = [{"weekday": "thu", "opens": "17:00", "closes": "23:00"}]
CAPS0 = {"p_1": 2, "p_2": 4, "p_3": 4}
T0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
      "opening_hours": HOURS0, "capacities": CAPS0}
NOW_HOURS = [{"weekday": d, "opens": "00:00", "closes": "23:45"} for d in ALL]
FIX = {
    "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"},
              {"id": "u_bob", "email": "bob@example.com", "password": "battery staple", "display_name": "Bob"},
              {"id": "u_mgr", "email": "mgr@example.com", "password": "manager pass", "display_name": "Mgr"}],
    "restaurants": [
        {"id": "r_pol", "name": "Policy Haus", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120, "opening_hours": HOURS0,
         "tables": [{"id": "p_1", "label": "Window", "capacity": 2}, {"id": "p_2", "label": "Booth", "capacity": 4},
                    {"id": "p_3", "label": "Garden", "capacity": 4}],
         "combinable": [["p_1", "p_2"]], "manager_user_ids": ["u_mgr"]},
        {"id": "r_now", "name": "Now", "timezone": "Asia/Kolkata", "slot_minutes": 15,
         "reservation_duration_minutes": 15, "cancellation_cutoff_minutes": 0, "opening_hours": NOW_HOURS,
         "tables": [{"id": f"n_{i}", "label": f"N{i}", "capacity": 4} for i in range(1, 5)],
         "manager_user_ids": ["u_mgr"]},
        {"id": "r_night", "name": "Night", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 0,
         "opening_hours": [{"weekday": "sun", "opens": "00:00", "closes": "06:00"}],
         "tables": [{"id": "g_1", "label": "G1", "capacity": 4}]},
        {"id": "r_other", "name": "Other", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0, "opening_hours": HOURS0,
         "tables": [{"id": "o_1", "label": "O1", "capacity": 4}]},
    ],
    "reservations": [
        {"id": "s_a", "reference": "SEEDA0001", "user_id": "u_ada", "restaurant_id": "r_pol", "table_id": "p_3",
         "starts_at_local": f"{THU5}T19:00", "party_size": 2},
        {"id": "s_c", "reference": "SEEDC0001", "user_id": "u_ada", "restaurant_id": "r_pol", "table_id": "p_3",
         "starts_at_local": f"{THU5}T21:00", "party_size": 2, "status": "cancelled"},
        {"id": "s_n", "reference": "SEEDN0001", "user_id": "u_ada", "restaurant_id": "r_now", "table_id": "n_1",
         "starts_at_local": NEAR60, "party_size": 2},
        {"id": "s_n2", "reference": "SEEDN0002", "user_id": "u_ada", "restaurant_id": "r_now", "table_id": "n_2",
         "starts_at_local": NEAR60, "party_size": 2},
    ],
}
POL = {
    1: {"effective_from": THU2, "slot_minutes": 60, "reservation_duration_minutes": 120, "cancellation_cutoff_minutes": 60,
        "opening_hours": [{"weekday": "thu", "opens": "17:00", "closes": "23:00"}], "capacities": {"p_1": 2, "p_2": 6, "p_3": 4}},
    2: {"effective_from": THU4, "slot_minutes": 30, "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 0,
        "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "22:00"}], "capacities": {"p_1": 3, "p_2": 4, "p_3": 4}},
    3: {"effective_from": THU2, "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 30,
        "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}], "capacities": {"p_1": 2, "p_2": 5, "p_3": 4}},
    4: {"effective_from": "2026-01-01", "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
        "opening_hours": [{"weekday": "thu", "opens": "17:00", "closes": "23:00"}], "capacities": {"p_1": 2, "p_2": 4, "p_3": 3}},
}


def terms(v):
    if v == 0:
        return T0
    p = POL[v]
    return {"policy_version": v, **{f: p[f] for f in ("slot_minutes", "reservation_duration_minutes",
                                                      "cancellation_cutoff_minutes", "opening_hours", "capacities")}}


def login(e, p):
    r = call("POST", "/auth/login", {"email": e, "password": p})
    return r.json["token"] if r.status == 200 else None


def book(tok, tid, start, party, rid="r_pol", key=None, tids=None):
    b = {"restaurant_id": rid, "starts_at_local": start, "party_size": party}
    if tids:
        b["table_ids"] = tids
    else:
        b["table_id"] = tid
    return call("POST", "/reservations", b, token=tok, key=key or k())


def get(tok, ref):
    return call("GET", f"/reservations/{ref}", token=tok)


def hist(tok, ref):
    r = call("GET", f"/reservations/{ref}/history", token=tok)
    return r.json.get("entries") if r.status == 200 and isinstance(r.json, dict) else None


def avail(date, party, rid="r_pol", explain=True):
    q = f"/availability?restaurant_id={rid}&date={date}&party_size={party}" + ("&explain=true" if explain else "")
    r = call("GET", q)
    return r, ({s["starts_at_local"][11:]: s for s in r.json["slots"]} if r.status == 200 else {})


def ch(field, frm, to):
    return {"field": field, "from": frm, "to": to}


def hist_ok(lid, entries, events, what):
    ok = entries is not None and [e.get("event") for e in entries] == events and \
        [e.get("seq") for e in entries] == list(range(1, len(entries) + 1)) and \
        all(RFC.match(e.get("at", "")) for e in entries)
    if ok:
        ats = [dt.datetime.fromisoformat(e["at"]) for e in entries]
        ok = all(ats[i] <= ats[i + 1] for i in range(len(ats) - 1))
    return check(lid, ok, f"{what}: events/seq/at {entries}")


def run():
    expect("S1-007", call("POST", "/_test/reset", FIX), 204, what="reset with manager_user_ids + seeds")
    ada, bob, mgr = login("ada@example.com", "correct horse"), login("bob@example.com", "battery staple"), \
        login("mgr@example.com", "manager pass")
    # ------------------------------------------------------------- explain
    for v in ("false", "1", "TRUE", "", "yes"):
        r = call("GET", f"/availability?restaurant_id=r_pol&date={THU1}&party_size=2&explain={v}")
        expect("S3-001", r, 422, "validation_failed", f"explain={v!r}")
    r, sm = avail(THU1, 2, explain=False)
    check("S3-002", r.status == 200 and all("explain" not in s for s in r.json["slots"]), "no explain fields without param")
    r, sm = avail(THU1, 2)
    s = sm.get("17:00", {})
    ex = s.get("explain")
    shape = isinstance(ex, list) and [e.get("table_id") for e in ex] == ["p_1", "p_2", "p_3"] and all(
        [x.get("rule") for x in e.get("rules", [])] == ["capacity", "no_overlap"] for e in ex)
    check("S3-003", shape, f"explain lists every table once in fixture order with both rules: {ex}")
    check("S3-006", shape and all(e.get("policy_version") == 0 for e in ex), "policy_version 0 before publications")
    # ------------------------------------------------------------- history on create
    K1 = k()
    r = book(ada, "p_2", f"{THU1}T19:00", 4, key=K1)
    ok = expect("S1-055", r, 201, what="create R1")
    R1 = r.json if ok else {}
    ref1 = R1.get("reference")
    check("S3-023", R1.get("revision") == 1 and R1.get("accepted_terms") == T0, f"R1 revision 1, terms policy 0: {R1}")
    e = hist(ada, ref1)
    hist_ok("S3-008", e, ["created"], "R1 created")
    check("S3-009", e and e[0]["changes"] == [ch("table_id", None, "p_2"), ch("starts_at_local", None, f"{THU1}T19:00"),
                                              ch("party_size", None, 4)], f"created changes: {e}")
    check("S3-013", e and e[0].get("revision") == 1 and e[0].get("accepted_terms") == T0, "created entry revision+terms")
    r = book(ada, "p_2", f"{THU1}T19:00", 4, key=K1)
    check("S3-012", r.status == 200 and r.json == R1 and len(hist(ada, ref1)) == 1, "replay records nothing")
    # seeded
    sa = get(ada, "SEEDA0001").json
    check("S3-024", sa.get("revision") == 1 and sa.get("accepted_terms") == T0, f"seeded rev 1 policy 0: {sa}")
    sc = hist(ada, "SEEDC0001")
    note("A-43", f"seeded cancelled history: {[(x['event'], x.get('revision'), x['changes']) for x in sc] if sc else sc}")
    # ------------------------------------------------------------- policy endpoint errors and validation
    good = dict(POL[1])
    expect("S3-015", call("POST", "/restaurants/r_pol/policies", good, key=k()), 401, "unauthenticated", "no token")
    expect("S3-015", call("POST", "/restaurants/r_pol/policies", good, token=bob, key=k()), 403, "forbidden", "non-manager")
    expect("S3-015", call("POST", "/restaurants/r_other/policies", good, token=mgr, key=k()), 403, "forbidden",
           "manager of another restaurant")
    expect("S3-015", call("POST", "/restaurants/r_nope/policies", good, token=mgr, key=k()), 404, "not_found", "unknown restaurant")
    expect("S3-015", call("POST", "/restaurants/r_pol/policies", good, token=mgr), 400, "missing_idempotency_key", "no key")
    expect("S3-015", call("POST", "/restaurants/r_pol/policies", good, token=mgr, key="x" * 256), 422, "validation_failed", "long key")
    bad = [
        ("missing effective_from", {k_: v for k_, v in good.items() if k_ != "effective_from"}),
        ("missing capacities", {k_: v for k_, v in good.items() if k_ != "capacities"}),
        ("bad date", dict(good, effective_from="2026-02-30")), ("date format", dict(good, effective_from="19-11-2026")),
        ("slot 0", dict(good, slot_minutes=0)), ("slot 1441", dict(good, slot_minutes=1441)),
        ("slot bool", dict(good, slot_minutes=True)), ("slot string", dict(good, slot_minutes="30")),
        ("slot fraction", dict(good, slot_minutes=30.5)), ("duration 1441", dict(good, reservation_duration_minutes=1441)),
        ("cutoff -1", dict(good, cancellation_cutoff_minutes=-1)), ("cutoff 10081", dict(good, cancellation_cutoff_minutes=10081)),
        ("dup weekday", dict(good, opening_hours=good["opening_hours"] * 2)),
        ("closes<=opens", dict(good, opening_hours=[{"weekday": "thu", "opens": "20:00", "closes": "19:00"}])),
        ("bad weekday", dict(good, opening_hours=[{"weekday": "xyz", "opens": "18:00", "closes": "19:00"}])),
        ("bad HH:MM", dict(good, opening_hours=[{"weekday": "thu", "opens": "18:60", "closes": "23:00"}])),
        ("caps missing table", dict(good, capacities={"p_1": 2, "p_2": 4})),
        ("caps extra table", dict(good, capacities={**good["capacities"], "p_9": 2})),
        ("caps 0", dict(good, capacities={**good["capacities"], "p_1": 0})),
        ("caps 101", dict(good, capacities={**good["capacities"], "p_1": 101})),
        ("caps string", dict(good, capacities={**good["capacities"], "p_1": "2"})),
        ("caps bool", dict(good, capacities={**good["capacities"], "p_1": True})),
        ("hours not list", dict(good, opening_hours="thu")),
    ]
    for what, b in bad:
        expect("S3-016", call("POST", "/restaurants/r_pol/policies", b, token=mgr, key=k()), 422, "validation_failed", what)
    r = call("GET", "/restaurants/r_pol/policies")
    check("S3-017", r.status == 200 and r.json == {"policies": []}, f"no version allocated by failures: {r!r}")
    # ------------------------------------------------------------- publish P1..P4 (publication order != date order)
    KP1 = k()
    pubs = {}
    for v in (1, 2, 3, 4):
        key = KP1 if v == 1 else k()
        r = call("POST", "/restaurants/r_pol/policies", dict(POL[v], unknown_field=1), token=mgr, key=key)
        ok = r.status == 201 and r.json.get("policy_version") == v and all(r.json.get(f) == POL[v][f] for f in POL[v])
        check("S3-017", ok, f"publish v{v}: {r!r}")
        pubs[v] = r.json
        if v == 1:
            rp = call("POST", "/restaurants/r_pol/policies", dict(POL[v], unknown_field=1), token=mgr, key=KP1)
            check("S3-015", rp.status == 200 and rp.json == r.json, "policy replay 200 identical, no new version")
            expect("S3-015", call("POST", "/restaurants/r_pol/policies", POL[2], token=mgr, key=KP1), 409,
                   "idempotency_key_reuse", "policy key reuse")
    r = call("GET", "/restaurants/r_pol/policies")
    check("S3-019", r.status == 200 and [p.get("policy_version") for p in r.json.get("policies", [])] == [1, 2, 3, 4] and
          r.json["policies"] == [pubs[v] for v in (1, 2, 3, 4)], f"list in publication order: {r!r}")
    expect("S3-019", call("GET", "/restaurants/r_nope/policies"), 404, "not_found", "unknown restaurant policies")
    r = call("GET", "/restaurants/r_pol")
    check("S3-020", r.status == 200 and r.json.get("slot_minutes") == 30 and r.json.get("opening_hours") == HOURS0 and
          [t["capacity"] for t in r.json["tables"]] == [2, 4, 4], "restaurant detail keeps fixture config")
    r = call("POST", "/restaurants/r_now/policies", {"effective_from": TODAY_IST, "slot_minutes": 15,
                                                     "reservation_duration_minutes": 15, "cancellation_cutoff_minutes": 120,
                                                     "opening_hours": NOW_HOURS, "capacities": {f"n_{i}": 4 for i in range(1, 5)}},
             token=mgr, key=k())
    check("S3-017", r.status == 201 and r.json.get("policy_version") == 1, f"versions independent per restaurant: {r!r}")
    # ------------------------------------------------------------- publication changes nothing existing
    g = get(ada, ref1).json
    check("S3-025", g.get("revision") == 1 and g.get("accepted_terms") == T0 and g.get("ends_at") == R1.get("ends_at")
          and len(hist(ada, ref1)) == 1, "existing booking untouched by publications")
    # ------------------------------------------------------------- selection via explain/availability
    sel = {OLD: (0, "17:00"), THU1: (4, "17:00"), THU2: (3, "18:00"), THU3: (3, "18:00"), THU4: (2, "18:00")}
    for date, (v, first) in sel.items():
        r, sm = avail(date, 2)
        slots = r.json["slots"] if r.status == 200 else []
        pv = {e["policy_version"] for s in slots for e in s.get("explain", [])}
        check("S3-021", slots and slots[0]["starts_at_local"][11:] == first and pv == {v},
              f"{date}: first slot {slots[0]['starts_at_local'] if slots else None}, policy_version {pv} (want {v}, {first})")
    r, sm = avail(THU4, 2)
    check("S3-022", [s for s in sm] == ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00"],
          f"THU4 grid under v2 (60-min duration, closes 22:00): {list(sm)}")
    r, sm = avail(THU1, 4)
    ex = {e["table_id"]: e for e in sm.get("18:00", {}).get("explain", [])}

    def rules(e):
        return [x["holds"] for x in e["rules"]] if e else None
    check("S3-004", rules(ex.get("p_1")) == [False, True] and rules(ex.get("p_2")) == [True, False] and
          rules(ex.get("p_3")) == [False, True] and sm["18:00"]["available_table_ids"] == [] and
          all(e["available"] is False for e in ex.values()),
          f"THU1 party 4 @18:00 under v4 (p_3 cap 3; p_2 booked 19:00): {ex}")
    book(bob, "p_1", f"{THU1}T19:00", 2)
    r, sm = avail(THU1, 5)
    e1 = [e for e in sm.get("19:00", {}).get("explain", []) if e["table_id"] == "p_1"]
    check("S3-004", e1 and rules(e1[0]) == [False, False] and e1[0]["available"] is False, f"table failing both: {e1}")
    r, sm = avail(THU1, 2)
    good_ids = all([e["table_id"] for e in s["explain"] if e["available"]] == s["available_table_ids"] and
                   all(e["available"] == all(x["holds"] for x in e["rules"]) for e in s["explain"]) for s in sm.values())
    check("S3-004", good_ids, "available == both rules hold, and equals available_table_ids in order")
    r, sm = avail("2026-11-11", 2)
    check("S3-005", r.status == 200 and r.json["slots"] == [], "closed day slots []")
    # ------------------------------------------------------------- bookings under selected policies
    r = book(ada, "p_1", f"{THU4}T18:00", 3)
    check("S3-022", r.status == 201 and r.json.get("accepted_terms") == terms(2) and
          r.json.get("ends_at") == f"{THU4}T19:00:00+01:00", f"THU4 v2: p_1 cap 3, 60-min duration {r!r}")
    expect("S3-022", book(ada, "p_1", f"{THU1}T21:00", 3), 422, "party_exceeds_capacity", "THU1 v4 p_1 cap 2")
    expect("S3-022", book(ada, "p_3", f"{THU2}T17:00", 2), 422, "outside_opening_hours", "THU2 v3 opens 18:00 (v1 would allow)")
    r = book(ada, "p_3", f"{THU2}T18:30", 2)
    check("S3-022", r.status == 201 and r.json.get("accepted_terms") == terms(3), f"THU2 18:30 on v3 grid (v1 grid 60) {r!r}")
    r = book(ada, None, f"{THU6}T20:00", 7, tids=["p_1", "p_2"])
    check("S3-047", r.status == 201 and r.json.get("accepted_terms", {}).get("policy_version") == 2,
          f"pair capacity = v2 caps 3+4 = 7 (fixture sum 6) {r!r}")
    # ------------------------------------------------------------- amendments, revisions, history, terms
    r = call("PATCH", f"/reservations/{ref1}", {"party_size": 4}, token=ada)
    check("S3-028", r.status == 200 and r.json.get("revision") == 1 and r.json.get("accepted_terms") == T0 and
          len(hist(ada, ref1)) == 1, f"no-op PATCH keeps revision/terms, no history {r!r}")
    r = call("PATCH", f"/reservations/{ref1}", {"party_size": 3}, token=ada)
    check("S3-027", r.status == 200 and r.json.get("revision") == 2 and r.json.get("accepted_terms") == terms(4),
          f"real amendment adopts THU1 policy v4, revision 2 {r!r}")
    e = hist(ada, ref1)
    check("S3-010", e and len(e) == 2 and e[1]["event"] == "changed" and e[1]["changes"] == [ch("party_size", 4, 3)],
          f"changed entry names only party_size: {e and e[-1]}")
    check("S3-013", e and e[1].get("revision") == 2 and e[1].get("accepted_terms") == terms(4) and
          e[0].get("accepted_terms") == T0, "entries carry resulting revision/terms; old entry keeps old terms")
    r = call("PATCH", f"/reservations/{ref1}", {"starts_at_local": f"{THU1}T20:00", "table_id": "p_3", "unknown": 1}, token=ada)
    e = hist(ada, ref1)
    check("S3-010", r.status == 200 and r.json.get("revision") == 3 and e and e[-1]["changes"] ==
          [ch("table_id", "p_2", "p_3"), ch("starts_at_local", f"{THU1}T19:00", f"{THU1}T20:00")],
          f"two fields in order table_id, starts_at_local: {e and e[-1]}")
    for bad_er in (0, -1, True, "3", 3.5, None):
        expect("S3-030", call("PATCH", f"/reservations/{ref1}", {"party_size": 2, "expected_revision": bad_er}, token=ada),
               422, "validation_failed", f"expected_revision={bad_er!r}")
    expect("S3-030", call("PATCH", f"/reservations/{ref1}", {"party_size": 2, "expected_revision": 99}, token=ada),
           409, "stale_revision", "stale expected_revision")
    expect("S3-030", call("PATCH", f"/reservations/{ref1}", {"party_size": 99, "expected_revision": 2}, token=ada),
           409, "stale_revision", "stale before validation")
    r = call("PATCH", f"/reservations/{ref1}", {"party_size": 2, "expected_revision": 3}, token=ada)
    check("S3-030", r.status == 200 and r.json.get("revision") == 4, f"matching expected_revision works {r!r}")
    nh = len(hist(ada, ref1))
    r = call("PATCH", f"/reservations/{ref1}", {"party_size": 9}, token=ada)
    g = get(ada, ref1).json
    check("S3-029", r.status == 422 and g.get("revision") == 4 and len(hist(ada, ref1)) == nh and g.get("party_size") == 2,
          "failed amendment changes nothing")
    r = call("PATCH", f"/reservations/{ref1}", {"starts_at_local": f"{THU2}T20:00"}, token=ada)
    check("S3-027", r.status == 200 and r.json.get("revision") == 5 and r.json.get("accepted_terms") == terms(3) and
          r.json.get("ends_at") == f"{THU2}T21:30:00+01:00", f"moving to THU2 adopts v3 terms and end time {r!r}")
    r = call("POST", f"/reservations/{ref1}/cancel", token=ada)
    e = hist(ada, ref1)
    check("S3-026", r.status == 200 and r.json.get("revision") == 6 and e and e[-1]["event"] == "cancelled" and
          e[-1]["changes"] == [] and e[-1].get("revision") == 6, f"cancel revision+1, cancelled entry {r!r}")
    r = call("POST", f"/reservations/{ref1}/cancel", token=ada)
    check("S3-026", r.status == 200 and r.json.get("revision") == 6 and len(hist(ada, ref1)) == len(e), "repeat cancel no change")
    hist_ok("S3-008", hist(ada, ref1), ["created", "changed", "changed", "changed", "changed", "cancelled"], "R1 full history")
    expect("S3-029", call("PATCH", f"/reservations/{ref1}", {"party_size": 3, "expected_revision": 1}, token=ada),
           409, "stale_revision", "A-29: stale before cancelled")
    expect("S1-077", call("PATCH", f"/reservations/{ref1}", {"party_size": 3}, token=ada), 409, "reservation_cancelled",
           "patch cancelled")
    d = call("GET", f"/reservations/{ref1}/decision", token=ada)
    check("S3-032", d.status == 200 and d.json == {"reference": ref1, "revision": 6, "accepted_terms": terms(3)},
          f"decision after cancel {d!r}")
    for tok, what in ((bob, "other user"), (None, "no token"), (mgr, "manager")):
        expect("S3-007", call("GET", f"/reservations/{ref1}/history", token=tok), 404, "not_found", f"history {what}")
        expect("S3-032", call("GET", f"/reservations/{ref1}/decision", token=tok), 404, "not_found", f"decision {what}")
    expect("S3-007", call("GET", "/reservations/NOPE0000/history", token=ada), 404, "not_found", "unknown history")
    expect("S3-033", call("GET", f"/reservations/{ref1}", token=mgr), 404, "not_found", "manager cannot read diner booking")
    r = book(ada, "p_2", f"{THU1}T19:00", 4, key=K1)
    check("S3-024", r.status == 200 and r.json == R1, "old key replays original revision 1 and policy-0 terms")
    # ------------------------------------------------------------- pair history
    r = book(ada, None, f"{THU3}T19:00", 5, tids=["p_2", "p_1"])
    P = r.json if r.status == 201 else {}
    pref = P.get("reference")
    e = hist(ada, pref) if pref else None
    check("S3-047", e and e[0]["changes"] == [ch("table_ids", None, ["p_1", "p_2"]), ch("starts_at_local", None, f"{THU3}T19:00"),
                                             ch("party_size", None, 5)], f"pair created uses table_ids: {e}")
    if pref:
        r = call("PATCH", f"/reservations/{pref}", {"table_ids": ["p_2", "p_1"]}, token=ada)
        check("S3-047", r.status == 200 and r.json.get("revision") == 1 and len(hist(ada, pref)) == 1, "reversed pair is a no-op")
        r = call("PATCH", f"/reservations/{pref}", {"table_ids": ["p_3"], "party_size": 4}, token=ada)
        e = hist(ada, pref)
        check("S3-047", r.status == 200 and e[-1]["changes"] == [ch("table_ids", ["p_1", "p_2"], ["p_3"]), ch("party_size", 5, 4)],
              f"pair -> single uses table_ids lists: {e[-1] if e else e}")
        r = call("PATCH", f"/reservations/{pref}", {"table_id": "p_2"}, token=ada)
        e = hist(ada, pref)
        check("S3-047", r.status == 200 and e[-1]["changes"] == [ch("table_id", "p_3", "p_2")], f"single->single table_id: {e[-1]}")
    # ------------------------------------------------------------- accepted cutoff (r_now, IST)
    r = call("PATCH", "/reservations/SEEDN0001", {"party_size": 3}, token=ada)
    check("S3-027", r.status == 200 and r.json.get("accepted_terms", {}).get("cancellation_cutoff_minutes") == 120,
          f"old accepted cutoff 0 allows the amendment; new terms cutoff 120: {r!r}")
    expect("S3-026", call("POST", "/reservations/SEEDN0001/cancel", token=ada), 409, "cutoff_passed",
           "after adopting cutoff-120 terms, cancel near booking refused")
    r = call("POST", "/reservations/SEEDN0002/cancel", token=ada)
    check("S3-026", r.status == 200 and r.json.get("status") == "cancelled", f"accepted cutoff 0 wins over current 120: {r!r}")
    C = book(ada, "n_3", NEAR75, 2, rid="r_now").json
    cref = C.get("reference")
    expect("S3-026", call("POST", f"/reservations/{cref}/cancel", token=ada), 409, "cutoff_passed", "C cutoff 120")
    r = call("POST", "/restaurants/r_now/policies", {"effective_from": TODAY_IST, "slot_minutes": 15,
                                                     "reservation_duration_minutes": 15, "cancellation_cutoff_minutes": 0,
                                                     "opening_hours": NOW_HOURS, "capacities": {f"n_{i}": 4 for i in range(1, 5)}},
             token=mgr, key=k())
    check("S3-021", r.status == 201 and r.json.get("policy_version") == 2, "same-date policy v2 supersedes")
    expect("S3-026", call("POST", f"/reservations/{cref}/cancel", token=ada), 409, "cutoff_passed", "C keeps accepted cutoff 120")
    expect("S3-027", call("PATCH", f"/reservations/{cref}", {"party_size": 3}, token=ada), 409, "cutoff_passed", "old accepted cutoff")
    expect("S3-030", call("PATCH", f"/reservations/{cref}", {"party_size": 3, "expected_revision": 7}, token=ada), 409,
           "stale_revision", "stale before cutoff")
    expect("S3-035", call("POST", "/series", {"anchor_reference": cref, "count": 2, "interval_weeks": 1}, token=ada, key=k()),
           409, "cutoff_passed", "series anchor within accepted cutoff")
    D = book(ada, "n_4", NEAR75, 2, rid="r_now").json
    r = call("POST", f"/reservations/{D.get('reference')}/cancel", token=ada)
    check("S3-026", r.status == 200, f"booking under same-date v2 (cutoff 0) cancellable: {r!r}")
    # ------------------------------------------------------------- series
    KA0 = k()
    A0 = book(ada, "p_3", f"{THU1}T21:00", 2, key=KA0).json
    a0 = A0.get("reference")
    KS = k()
    sb = {"anchor_reference": a0, "count": 4, "interval_weeks": 1, "foo": "bar"}
    r = call("POST", "/series", sb, token=ada, key=KS)
    ok = expect("S3-040", r, 201, what="adopt series")
    S = r.json if ok else {}
    occ = S.get("occurrences", [])
    check("S3-040", ok and S.get("revision") == 1 and S.get("interval_weeks") == 1 and isinstance(S.get("series_id"), str) and
          len(S["series_id"]) <= 64 and [o.get("index") for o in occ] == [0, 1, 2, 3] and occ[0].get("reference") == a0 and
          all(o.get("exception") is False for o in occ) and len({o.get("reference") for o in occ}) == 4, f"series shape {S}")
    if len(occ) == 4:
        check("S3-036", occ[0]["reservation"] == get(ada, a0).json and occ[0]["reservation"].get("revision") == 1 and
              occ[0]["reservation"] == A0 and len(hist(ada, a0)) == 1, "occurrence 0 is the unchanged anchor")
        check("S3-037", [o["reservation"]["starts_at_local"] for o in occ] == [f"{d}T21:00" for d in (THU1, THU2, THU3, THU4)] and
              all(o["reservation"].get("table_ids") == ["p_3"] and o["reservation"]["party_size"] == 2 for o in occ),
              "dates +7 days, same local time, table and party")
        check("S3-038", [o["reservation"]["accepted_terms"]["policy_version"] for o in occ] == [4, 3, 3, 2] and
              occ[3]["reservation"]["ends_at"] == f"{THU4}T22:00:00+01:00", "each occurrence selects its own date's policy")
        lst = {x["reference"] for x in call("GET", "/reservations", token=ada).json["reservations"]}
        h1 = hist(ada, occ[1]["reference"])
        check("S3-041", all(o["reference"] in lst for o in occ) and h1 and [x["event"] for x in h1] == ["created"] and
              occ[1]["reservation"].get("revision") == 1, "occurrences are ordinary listed reservations with history")
        r2, sm = avail(THU2, 2)
        check("S3-041", "p_3" not in sm["21:00"]["available_table_ids"], "occurrences occupy tables")
        r = call("POST", "/reservations", {"restaurant_id": "r_pol", "table_id": "p_3", "starts_at_local": f"{THU1}T21:00",
                                           "party_size": 2}, token=ada, key=KA0)
        check("S3-036", r.status == 200 and r.json == A0, "anchor's original idempotent response unchanged")
        sid = S["series_id"]
        rs = call("POST", "/series", sb, token=ada, key=KS)
        check("S3-045", rs.status == 200 and rs.json == S, "series replay 200 identical")
        expect("S3-034", call("POST", "/series", dict(sb, count=3), token=ada, key=KS), 409, "idempotency_key_reuse", "series key reuse")
        gs = call("GET", f"/series/{sid}", token=ada)
        check("S3-042", gs.status == 200 and gs.json == S, f"GET series equals creation response before changes {gs!r}")
        expect("S3-042", call("GET", f"/series/{sid}", token=bob), 404, "not_found", "series other user")
        expect("S3-042", call("GET", f"/series/{sid}"), 404, "not_found", "series no token")
        expect("S3-042", call("GET", "/series/nope", token=ada), 404, "not_found", "unknown series")
        o1, o2, o3 = occ[1]["reference"], occ[2]["reference"], occ[3]["reference"]
        r = call("PATCH", f"/reservations/{o1}", {"party_size": 3}, token=ada)
        gs = call("GET", f"/series/{sid}", token=ada).json
        check("S3-043", r.status == 200 and gs["revision"] == 2 and gs["occurrences"][1]["exception"] is True and
              gs["occurrences"][1]["reservation"]["party_size"] == 3, f"real PATCH -> exception, series rev 2: {gs.get('revision')}")
        call("PATCH", f"/reservations/{o2}", {"party_size": 2}, token=ada)
        call("PATCH", f"/reservations/{o2}", {"party_size": 99}, token=ada)
        gs = call("GET", f"/series/{sid}", token=ada).json
        check("S3-043", gs["revision"] == 2 and gs["occurrences"][2]["exception"] is False, "no-op and failed PATCH change nothing")
        call("POST", f"/reservations/{o3}/cancel", token=ada)
        call("POST", f"/reservations/{o3}/cancel", token=ada)
        gs = call("GET", f"/series/{sid}", token=ada).json
        check("S3-044", gs["revision"] == 3 and gs["occurrences"][3]["exception"] is False and
              gs["occurrences"][3]["reservation"]["status"] == "cancelled", f"cancel: rev 3 once, kept, no exception {gs['revision']}")
        call("POST", f"/reservations/{a0}/cancel", token=ada)
        gs = call("GET", f"/series/{sid}", token=ada).json
        check("S3-044", gs["revision"] == 4 and gs["occurrences"][1]["reservation"]["status"] == "confirmed" and
              gs["occurrences"][2]["reservation"]["status"] == "confirmed", "anchor cancel does not cancel siblings")
        rs = call("POST", "/series", sb, token=ada, key=KS)
        check("S3-045", rs.status == 200 and rs.json == S and call("GET", f"/series/{sid}", token=ada).json["revision"] == 4,
              "replay after changes returns original, changes no counter")
        expect("S3-035", call("POST", "/series", {"anchor_reference": o2, "count": 2, "interval_weeks": 1}, token=ada, key=k()),
               409, "already_in_series", "occurrence already in a series")
        expect("S3-035", call("POST", "/series", {"anchor_reference": a0, "count": 2, "interval_weeks": 1}, token=ada, key=k()),
               409, "reservation_cancelled", "cancelled anchor")
    expect("S3-034", call("POST", "/series", sb, key=k()), 401, "unauthenticated", "series no token")
    expect("S3-034", call("POST", "/series", sb, token=ada), 400, "missing_idempotency_key", "series no key")
    B0 = book(ada, "p_1", f"{THU1}T21:30", 2).json
    b0 = B0.get("reference")
    for what, b in [("count 1", {"count": 1}), ("count 13", {"count": 13}), ("count bool", {"count": True}),
                    ("count string", {"count": "4"}), ("count fraction", {"count": 2.5}), ("interval 0", {"interval_weeks": 0}),
                    ("interval 5", {"interval_weeks": 5}), ("interval bool", {"interval_weeks": True}),
                    ("anchor missing", {"anchor_reference": None}), ("anchor int", {"anchor_reference": 5})]:
        body = {"anchor_reference": b0, "count": 4, "interval_weeks": 1, **b}
        if body["anchor_reference"] is None:
            del body["anchor_reference"]
        expect("S3-034", call("POST", "/series", body, token=ada, key=k()), 422, "validation_failed", what)
    expect("S3-035", call("POST", "/series", {"anchor_reference": "NOPE0000", "count": 2, "interval_weeks": 1}, token=ada,
                          key=k()), 404, "not_found", "unknown anchor")
    bobres = book(bob, "o_1", f"{THU1}T19:00", 2, rid="r_other").json
    expect("S3-035", call("POST", "/series", {"anchor_reference": bobres.get("reference"), "count": 2, "interval_weeks": 1},
                          token=ada, key=k()), 404, "not_found", "another owner's anchor")
    # all-or-nothing + index order
    book(bob, "p_1", f"{THU3}T21:30", 2)
    before = len(call("GET", "/reservations", token=ada).json["reservations"])
    KSB = k()
    r = call("POST", "/series", {"anchor_reference": b0, "count": 4, "interval_weeks": 1}, token=ada, key=KSB)
    after = len(call("GET", "/reservations", token=ada).json["reservations"])
    expect("S3-039", r, 409, "table_unavailable", "occ2 conflict (index order) beats occ3 outside hours")
    check("S3-039", after == before and get(ada, b0).json == B0 and len(hist(ada, b0)) == 1, "failed adoption leaves nothing")
    r = call("POST", "/series", {"anchor_reference": b0, "count": 2, "interval_weeks": 1}, token=ada, key=KSB)
    check("S3-039", r.status == 201, f"failed adoption's key is reusable {r!r}")
    B1 = book(ada, "p_2", f"{THU1}T21:30", 2).json
    r = call("POST", "/series", {"anchor_reference": B1.get("reference"), "count": 4, "interval_weeks": 1}, token=ada, key=k())
    expect("S3-038", r, 422, "outside_opening_hours", "occ3 under v2 ends after 22:00")
    # DST
    N1 = book(ada, "g_1", "2027-03-21T02:30", 2, rid="r_night").json
    r = call("POST", "/series", {"anchor_reference": N1.get("reference"), "count": 2, "interval_weeks": 1}, token=ada, key=k())
    expect("S3-038", r, 422, "invalid_local_time", "occ1 in spring-forward gap rejects adoption")
    N2 = book(ada, "g_1", "2027-10-24T02:30", 2, rid="r_night").json
    r = call("POST", "/series", {"anchor_reference": N2.get("reference"), "count": 2, "interval_weeks": 1}, token=ada, key=k())
    check("S3-038", r.status == 201 and r.json["occurrences"][1]["reservation"]["starts_at"] == "2027-10-31T02:30:00+02:00",
          f"repeated time resolves to first occurrence {r!r}")
    # pair series
    PA = book(ada, None, f"{THU5}T18:00", 6, tids=["p_1", "p_2"]).json
    r = call("POST", "/series", {"anchor_reference": PA.get("reference"), "count": 2, "interval_weeks": 1}, token=ada, key=k())
    check("S3-037", r.status == 201 and r.json["occurrences"][1]["reservation"].get("table_ids") == ["p_1", "p_2"] and
          r.json["occurrences"][1]["reservation"]["starts_at_local"] == f"{THU6}T18:00", f"pair series {r!r}")
    # ------------------------------------------------------------- moves under policies
    M1 = book(ada, "p_1", f"{THU3}T18:00", 2).json
    M2 = book(ada, "p_2", f"{THU3}T21:30", 2).json
    KM = k()
    mv = {"moves": [{"reference": M1["reference"], "starts_at_local": f"{THU4}T19:00"}, {"reference": M2["reference"]}]}
    r = call("POST", "/reservation-moves", mv, token=ada, key=KM)
    ok = r.status == 201
    check("S3-048", ok and r.json["reservations"][0]["accepted_terms"] == terms(2) and r.json["reservations"][0]["revision"] == 2
          and r.json["reservations"][0]["ends_at"] == f"{THU4}T20:00:00+01:00" and r.json["reservations"][1]["revision"] == 1,
          f"moved booking adopts v2, no-op keeps revision {r!r}")
    e1, e2 = hist(ada, M1["reference"]), hist(ada, M2["reference"])
    check("S3-049", e1 and [x["event"] for x in e1] == ["created", "changed"] and
          e1[-1]["changes"] == [ch("starts_at_local", f"{THU3}T18:00", f"{THU4}T19:00")] and len(e2) == 1,
          "one changed entry per changed booking, none for no-op")
    r = call("POST", "/reservation-moves", mv, token=ada, key=KM)
    check("S3-050", r.status == 200 and get(ada, M1["reference"]).json["revision"] == 2 and len(hist(ada, M1["reference"])) == 2,
          "moves replay changes nothing")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M2["reference"], "party_size": 3},
                                                       {"reference": M1["reference"], "party_size": 3, "expected_revision": 1}]},
             token=ada, key=k())
    expect("S3-048", r, 409, "stale_revision", "per-move stale expected_revision")
    check("S3-050", get(ada, M2["reference"]).json["revision"] == 1 and len(hist(ada, M2["reference"])) == 1,
          "failed batch changes no revision/history")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1["reference"], "party_size": 3, "expected_revision": "2"}]},
             token=ada, key=k())
    expect("S3-048", r, 422, "validation_failed", "per-move invalid expected_revision")
    if len(occ) == 4:
        r = call("POST", "/reservation-moves", {"moves": [{"reference": occ[1]["reference"], "party_size": 2},
                                                           {"reference": occ[2]["reference"], "party_size": 3}]}, token=ada, key=k())
        gs = call("GET", f"/series/{S['series_id']}", token=ada).json
        check("S3-049", r.status == 201 and gs["revision"] == 5 and gs["occurrences"][2]["exception"] is True and
              gs["occurrences"][1]["exception"] is True, f"batch: series revision +1 once, changed occurrences exceptions {gs['revision']}")
    # ------------------------------------------------------------- expected_revision race
    R5 = book(ada, "p_2", f"{THU2}T18:00", 2).json
    r5 = R5["reference"]
    bar = threading.Barrier(10)

    def w(_):
        bar.wait()
        return call("PATCH", f"/reservations/{r5}", {"party_size": 3, "expected_revision": 1}, token=ada)
    with ThreadPoolExecutor(10) as ex_:
        rs = list(ex_.map(w, range(10)))
    sts = sorted(x.status for x in rs)
    check("S3-031", sts.count(200) == 1 and sts.count(409) == 9 and all(x.code == "stale_revision" for x in rs if x.status == 409)
          and get(ada, r5).json["revision"] == 2 and len(hist(ada, r5)) == 2, f"concurrent same expected_revision: {sts}")
    # ------------------------------------------------------------- export / import round trip
    exp = call("GET", "/_test/export")
    snap = {"pol": call("GET", "/restaurants/r_pol/policies").json, "hist": hist(ada, ref1),
            "dec": call("GET", f"/reservations/{ref1}/decision", token=ada).json,
            "series": call("GET", f"/series/{S.get('series_id')}", token=ada).json if S else None,
            "list": call("GET", "/reservations", token=ada).json}
    call("POST", "/_test/reset", FIX)
    r = call("POST", "/_test/import", exp.json)
    expect("S3-051", r, 204, what="stage-3 import")
    after = {"pol": call("GET", "/restaurants/r_pol/policies").json, "hist": hist(ada, ref1),
             "dec": call("GET", f"/reservations/{ref1}/decision", token=ada).json,
             "series": call("GET", f"/series/{S.get('series_id')}", token=ada).json if S else None,
             "list": call("GET", "/reservations", token=ada).json}
    check("S3-051", after == snap, "policies, history, decision, series, reservations round-trip")
    if S:
        rs = call("POST", "/series", sb, token=ada, key=KS)
        check("S3-051", rs.status == 200 and rs.json == S, "series receipt survives import")
    r = call("POST", "/restaurants/r_pol/policies", dict(POL[1], unknown_field=1), token=mgr, key=KP1)
    check("S3-051", r.status == 200 and r.json.get("policy_version") == 1, "policy receipt survives import")
    r = call("POST", "/restaurants/r_pol/policies", dict(POL[1], effective_from="2027-01-07"), token=mgr, key=k())
    check("S3-051", r.status == 201 and r.json.get("policy_version") == 5, "version counter continues after import")
    if BASE2:
        r = call("POST", "/_test/import", exp.json, base=BASE2)
        expect("S3-051", r, 204, what="import into fresh instance")
        r = call("GET", f"/reservations/{ref1}/history", token=ada, base=BASE2)
        check("S3-051", r.status == 200 and r.json.get("entries") == snap["hist"], "fresh instance history")


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
