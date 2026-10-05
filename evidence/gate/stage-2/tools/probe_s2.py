"""Gate's independent black-box probe for tablekeeper stage 2 API (combined tables), from spec stage-2.md + ledger only.
Stdlib only. Usage: py -3.12 probe_s2.py http://127.0.0.1:PORT [http://127.0.0.1:FRESH_PORT]
PASS/FAIL lines tagged with ledger ids; NOTE lines record readings of Coordinator decisions (A-20..A-23)."""
import http.client
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse

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
        return f"<{self.status} {self.raw[:240]!r}>"


def call(method, path, body=None, token=None, key=None, raw=None, base=None):
    b = base or BASE
    h = {}
    if body is not None or raw is not None:
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    c = http.client.HTTPConnection(b.hostname, b.port, timeout=15)
    c.request(method, path, body=data, headers=h)
    resp = c.getresponse()
    out = R(resp.status, resp.read())
    c.close()
    if out.status >= 500:
        with LOCK:
            FIVEXX.append((method, path, out.status))
    return out


def check(lid, cond, detail=""):
    RESULTS.append(("PASS" if cond else "FAIL", lid, detail))
    print("PASS" if cond else "FAIL", lid, detail[:160] if cond else detail[:400], flush=True)
    return cond


def note(lid, detail):
    RESULTS.append(("NOTE", lid, detail))
    print("NOTE", lid, detail, flush=True)


def expect(lid, r, status, code=None, what=""):
    return check(lid, r.status == status and (code is None or r.code == code),
                 f"{what}: expected {status} {code or ''} got {r!r}")


KN = [0]


def k():
    KN[0] += 1
    return f"g2-{KN[0]}-{time.time_ns()}"


THU = "2026-11-12"   # Thursday, Berlin winter time
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FIX = {
    "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"},
              {"id": "u_bob", "email": "bob@example.com", "password": "battery staple", "display_name": "Bob"}],
    "restaurants": [
        {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
         "opening_hours": [{"weekday": d, "opens": "17:00", "closes": "23:00"} for d in ALL],
         "tables": [{"id": "t_1", "label": "Window 1", "capacity": 2}, {"id": "t_2", "label": "Booth 2", "capacity": 4},
                    {"id": "t_3", "label": "Garden 3", "capacity": 4}, {"id": "t_4", "label": "Bar 4", "capacity": 2}],
         "combinable": [["t_1", "t_2"], ["t_3", "t_2"]]},
        {"id": "r_other", "name": "Other", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
         "opening_hours": [{"weekday": "thu", "opens": "17:00", "closes": "23:00"}],
         "tables": [{"id": "o_1", "label": "O1", "capacity": 4}]},
    ],
    "reservations": [
        {"id": "seed_pair", "reference": "SEEDPAIR1", "user_id": "u_bob", "restaurant_id": "r_anker",
         "table_ids": ["t_1", "t_2"], "starts_at_local": "2026-11-19T19:00", "party_size": 5},
        {"id": "seed_cx", "reference": "SEEDCANC1", "user_id": "u_bob", "restaurant_id": "r_anker",
         "table_id": "t_3", "starts_at_local": "2026-11-19T19:00", "party_size": 2, "status": "cancelled"},
        {"id": "seed_one", "reference": "SEEDONE01", "user_id": "u_bob", "restaurant_id": "r_anker",
         "table_ids": ["t_4"], "starts_at_local": "2026-11-19T19:00", "party_size": 2},
    ],
}


def login(e, p):
    r = call("POST", "/auth/login", {"email": e, "password": p})
    return r.json["token"] if r.status == 200 else None


def create(tok, body, key=None):
    return call("POST", "/reservations", body, token=tok, key=key or k())


def body(tids=None, tid=None, start=f"{THU}T19:00", party=2, rid="r_anker"):
    b = {"restaurant_id": rid, "starts_at_local": start, "party_size": party}
    if tids is not None:
        b["table_ids"] = tids
    if tid is not None:
        b["table_id"] = tid
    return b


def avail(date, party, rid="r_anker"):
    r = call("GET", f"/availability?restaurant_id={rid}&date={date}&party_size={party}")
    return r, ({s["starts_at_local"][11:]: s for s in r.json["slots"]} if r.status == 200 else {})


def shape_ok(x, tids):
    if x.get("table_ids") != tids:
        return False
    if len(tids) == 1:
        return x.get("table_id") == tids[0]
    return "table_id" not in x


def run():
    expect("S1-007", call("POST", "/_test/reset", FIX), 204, what="reset with combinable + seeded table_ids/status")
    ada, bob = login("ada@example.com", "correct horse"), login("bob@example.com", "battery staple")
    r = call("GET", "/restaurants/r_anker")
    note("S2-030", f"restaurant detail combinable -> {r.json.get('combinable') if r.status == 200 else r}")
    # ------------------------------------------------ availability options
    r, sm = avail(THU, 2)
    s = sm.get("19:00", {})
    check("S2-033", s.get("available_table_ids") == ["t_1", "t_2", "t_3", "t_4"] and s.get("available_options") == [
        {"table_ids": ["t_1"], "capacity": 2}, {"table_ids": ["t_2"], "capacity": 4},
        {"table_ids": ["t_3"], "capacity": 4}, {"table_ids": ["t_4"], "capacity": 2},
        {"table_ids": ["t_1", "t_2"], "capacity": 6}, {"table_ids": ["t_3", "t_2"], "capacity": 8}],
        f"party 2 options {s}")
    r, sm = avail(THU, 5)
    s = sm.get("19:00", {})
    check("S2-033", s.get("available_table_ids") == [] and s.get("available_options") == [
        {"table_ids": ["t_1", "t_2"], "capacity": 6}, {"table_ids": ["t_3", "t_2"], "capacity": 8}],
        f"party 5 options (pairs only, combinable order) {s}")
    r, sm = avail(THU, 9)
    check("S2-033", sm.get("19:00", {}).get("available_options") == [] and len(sm) > 0, "party 9: options empty, slot present")
    # seeded: pair occupies both members, cancelled seed occupies nothing, table_ids single seed
    r, sm = avail("2026-11-19", 2)
    s = sm.get("19:00", {})
    check("S2-032", s.get("available_table_ids") == ["t_3"] and s.get("available_options") == [
        {"table_ids": ["t_3"], "capacity": 4}], f"seeded pair+single block, cancelled seed frees t_3: {s}")
    bob_list = call("GET", "/reservations", token=bob).json["reservations"]
    by = {x["reference"]: x for x in bob_list}
    check("S2-032", by.get("SEEDCANC1", {}).get("status") == "cancelled" and by.get("SEEDPAIR1", {}).get("status") ==
          "confirmed", "seeded statuses")
    check("S2-035", shape_ok(by.get("SEEDPAIR1", {}), ["t_1", "t_2"]) and shape_ok(by.get("SEEDONE01", {}), ["t_4"])
          and shape_ok(by.get("SEEDCANC1", {}), ["t_3"]), f"seeded shapes {list(by.values())[:3]}")
    # ------------------------------------------------ create pair
    KP = k()
    bp = body(["t_2", "t_1"], party=5)
    r = create(ada, bp, KP)
    ok = expect("S2-034", r, 201, what="create pair given in reverse order")
    pair = r.json if ok else {}
    check("S2-035", shape_ok(pair, ["t_1", "t_2"]), f"pair response table_ids in combinable order, no table_id: {pair}")
    check("S2-022/A-22", pair.get("party_size") == 5 and pair.get("status") == "confirmed", "pair booking fields")
    r = create(ada, bp, KP)
    check("S1-039", r.status == 200 and r.json == pair, "pair replay 200 identical")
    r, sm = avail(THU, 2)
    s = sm.get("19:00", {})
    check("S2-037", s.get("available_table_ids") == ["t_3", "t_4"] and s.get("available_options") == [
        {"table_ids": ["t_3"], "capacity": 4}, {"table_ids": ["t_4"], "capacity": 2}],
        f"pair occupies both members and every pair containing them: {s}")
    expect("S2-037", create(ada, body(tid="t_1", start=f"{THU}T19:30")), 409, "table_unavailable", "single on member")
    expect("S2-037", create(ada, body(["t_3", "t_2"], start=f"{THU}T20:00", party=5)), 409, "table_unavailable",
           "other pair sharing t_2, overlapping")
    expect("S2-037", create(ada, body(["t_3", "t_2"], start=f"{THU}T20:30", party=5)), 201, what="pair back-to-back")
    # ------------------------------------------------ validation (A-20)
    cases = [
        ("S2-036", body(["t_1", "t_3"], start=f"{THU}T17:00"), 422, "combination_not_allowed", "undeclared pair"),
        ("S2-036", body(["t_1", "t_2", "t_3"], start=f"{THU}T17:00", party=2), 422, "combination_not_allowed", "3 tables"),
        ("S2-036", body(["t_1", "t_1"], start=f"{THU}T17:00"), 422, "validation_failed", "duplicate id"),
        ("S2-036", body([], start=f"{THU}T17:00"), 422, "validation_failed", "empty set"),
        ("S2-034", body(["t_1"], tid="t_1", start=f"{THU}T17:00"), 422, "validation_failed", "both table_id and table_ids"),
        ("S2-034", body(start=f"{THU}T17:00"), 422, "validation_failed", "neither"),
        ("S2-036", body("t_1", start=f"{THU}T17:00"), 400, "malformed_request", "table_ids not an array"),
        ("S2-036", body([1, 2], start=f"{THU}T17:00"), 400, "malformed_request", "non-string members"),
        ("S2-036", body(["t_1", "t_nope"], start=f"{THU}T17:00"), 404, "not_found", "unknown member"),
        ("S2-036", body(["t_1", "o_1"], start=f"{THU}T17:00"), 404, "not_found", "member of another restaurant"),
        ("S2-038", body(["t_1", "t_2"], start=f"{THU}T17:00", party=7), 422, "party_exceeds_capacity", "party > sum"),
        ("S1-059", body(["t_1", "t_2"], start=f"{THU}T17:15", party=6), 422, "not_on_slot_grid", "pair off grid"),
    ]
    for lid, b, st, code, what in cases:
        expect(lid, create(ada, b), st, code, what)
    r = create(ada, body(["t_1", "t_2"], start=f"{THU}T17:00", party=6))
    expect("S2-031", r, 201, what="party == summed capacity accepted")
    P6 = r.json.get("reference") if r.status == 201 else None
    r = create(ada, body(["t_4"], start=f"{THU}T17:00"))
    ok = expect("S2-034", r, 201, what="table_ids with one member")
    check("S2-035", ok and shape_ok(r.json, ["t_4"]), f"single via table_ids carries table_id too: {r.json}")
    S4 = r.json.get("reference") if ok else None
    for b, what in [(body(["t_nope", "t_1", "t_2"], start=f"{THU}T17:00"), "3 tables incl unknown"),
                    (body(["t_1", "t_1", "t_nope"], start=f"{THU}T17:00"), "dup incl unknown"),
                    (body(["t_1", "t_3"], start=f"{THU}T17:15", party=9), "undeclared pair off grid, party too big")]:
        r = create(ada, b)
        note("A-20", f"{what} -> {r.status} {r.code}")
    # ------------------------------------------------ read / patch / cancel shapes
    if P6:
        g = call("GET", f"/reservations/{P6}", token=ada)
        check("S2-035", g.status == 200 and shape_ok(g.json, ["t_1", "t_2"]), f"GET pair shape {g!r}")
        lst = call("GET", "/reservations", token=ada).json["reservations"]
        check("S2-035", all(shape_ok(x, x["table_ids"]) and isinstance(x["table_ids"], list) for x in lst),
              "list entries carry table_ids (+table_id iff single)")
        r = call("PATCH", f"/reservations/{P6}", {"table_ids": ["t_3", "t_1"]}, token=ada)
        expect("S2-039", r, 422, "combination_not_allowed", "patch to undeclared pair")
        r = call("PATCH", f"/reservations/{P6}", {"table_ids": ["t_1"], "table_id": "t_1"}, token=ada)
        expect("S2-039", r, 422, "validation_failed", "patch both fields")
        r = call("PATCH", f"/reservations/{P6}", {"table_ids": ["t_2"], "party_size": 4}, token=ada)
        check("S2-039", r.status == 200 and shape_ok(r.json, ["t_2"]) and r.json["reference"] == P6,
              f"patch pair -> single {r!r}")
        r2, sm = avail(THU, 2)
        check("S2-039", "t_1" in sm["17:00"]["available_table_ids"] and "t_2" not in sm["17:00"]["available_table_ids"],
              "patch released t_1 and kept t_2")
        r = call("PATCH", f"/reservations/{P6}", {"table_ids": ["t_2", "t_3"], "party_size": 7}, token=ada)
        check("S2-039", r.status == 200 and shape_ok(r.json, ["t_3", "t_2"]), f"patch single -> pair (reverse order) {r!r}")
        r = call("PATCH", f"/reservations/{P6}", {"party_size": 9}, token=ada)
        expect("S2-038", r, 422, "party_exceeds_capacity", "patch party above pair sum")
        r = call("POST", f"/reservations/{P6}/cancel", token=ada)
        check("S2-039", r.status == 200 and r.json["status"] == "cancelled" and shape_ok(r.json, ["t_3", "t_2"]),
              f"cancel pair {r!r}")
        r2, sm = avail(THU, 2)
        check("S2-039", "t_2" in sm["17:00"]["available_table_ids"] and "t_3" in sm["17:00"]["available_table_ids"],
              "cancel frees every member")
    # ------------------------------------------------ moves with table_ids
    D = "2026-11-26"
    A = create(ada, body(["t_1", "t_2"], start=f"{D}T21:00", party=5)).json
    B = create(ada, body(tid="t_3", start=f"{D}T21:00", party=2)).json
    KM = k()
    mv = {"moves": [{"reference": A["reference"], "table_ids": ["t_3", "t_2"]},
                    {"reference": B["reference"], "table_ids": ["t_1"]}]}
    r = call("POST", "/reservation-moves", mv, token=ada, key=KM)
    ok = r.status == 201 and shape_ok(r.json["reservations"][0], ["t_3", "t_2"]) and \
        shape_ok(r.json["reservations"][1], ["t_1"])
    check("S2-040", ok, f"moves swap pair<->single via table_ids {r!r}")
    r = call("POST", "/reservation-moves", mv, token=ada, key=KM)
    check("S1-104", r.status == 200, "moves replay")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": A["reference"], "table_ids": ["t_1", "t_2"]}]},
             token=ada, key=k())
    expect("S2-040", r, 409, "table_unavailable", "move pair onto member held by unlisted B")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": A["reference"], "table_ids": ["t_1", "t_3"]}]},
             token=ada, key=k())
    expect("S2-040", r, 422, "combination_not_allowed", "move to undeclared pair")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": B["reference"], "table_ids": ["t_4"]},
                                                       {"reference": A["reference"], "table_ids": ["t_1", "t_2"]}]},
             token=ada, key=k())
    expect("S2-040", r, 201, what="chain: B frees t_1, A takes t_1+t_2")
    # ------------------------------------------------ concurrency on pairs vs singles
    D2 = "2026-12-03"
    fns = [(lambda: create(ada, body(["t_1", "t_2"], start=f"{D2}T19:00", party=5))) for _ in range(10)]
    fns += [(lambda: create(bob, body(tid="t_1", start=f"{D2}T19:00"))) for _ in range(10)]
    fns += [(lambda: create(bob, body(tid="t_2", start=f"{D2}T19:30"))) for _ in range(10)]
    bar = threading.Barrier(len(fns))

    def w(f):
        bar.wait()
        return f()
    with ThreadPoolExecutor(len(fns)) as ex:
        rs = list(ex.map(w, fns))
    wins = [i for i, x in enumerate(rs) if x.status == 201]
    pair_w = [i for i in wins if i < 10]
    t1_w = [i for i in wins if 10 <= i < 20]
    t2_w = [i for i in wins if i >= 20]
    others = [x.status for x in rs if x.status not in (201, 409)]
    consistent = (len(pair_w) == 1 and not t1_w and not t2_w) or (not pair_w and len(t1_w) <= 1 and len(t2_w) <= 1
                                                                 and (t1_w or t2_w))
    check("S2-041", consistent and not others, f"pair vs single race wins pair={len(pair_w)} t1={len(t1_w)} "
          f"t2={len(t2_w)} other={others}")
    occ = {}
    for tok in (ada, bob):
        for x in call("GET", "/reservations", token=tok).json["reservations"]:
            if x["status"] == "confirmed" and x["starts_at_local"].startswith(D2):
                for t in x["table_ids"]:
                    occ.setdefault(t, []).append((x["starts_at"], x["ends_at"]))
    clash = any(len(v) > 1 and sorted(v)[0][1] > sorted(v)[1][0] for v in occ.values())
    check("S2-041", not clash and sum(len(v) for v in occ.values()) == (2 if pair_w else len(t1_w) + len(t2_w)),
          f"state matches the winners, no table double-booked: {occ}")
    # ------------------------------------------------ export / import round trip with pairs
    e = call("GET", "/_test/export")
    check("S2-042", e.status == 200 and e.json.get("format_version") == 1, "export")
    ada_before = call("GET", "/reservations", token=ada).json
    r = call("POST", "/_test/reset", FIX)
    r = call("POST", "/_test/import", e.json)
    expect("S2-042", r, 204, what="import stage-2 export")
    check("S2-042", call("GET", "/reservations", token=ada).json == ada_before, "pair bookings round-trip")
    r = create(ada, bp, KP)
    check("S2-042", r.status == 200 and r.json == pair, "pair receipt replays after import")
    r, sm = avail(THU, 2)
    check("S2-042", "t_1" not in sm["19:00"]["available_table_ids"], "imported pair still occupies")
    if BASE2:
        r = call("POST", "/_test/import", e.json, base=BASE2)
        expect("S2-042", r, 204, what="import into fresh instance")
        r = call("POST", "/reservations", bp, token=ada, key=KP, base=BASE2)
        check("S2-042", r.status == 200 and r.json == pair, "fresh instance: pair replay")


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
