"""Gate's independent black-box probe for tablekeeper stage 1.

Derived from spec stage-1.md and ledger fe058da only. Stdlib only.
Usage: py -3.12 probe_s1.py http://127.0.0.1:PORT [http://127.0.0.1:PORT2]
The optional second URL is a FRESH container used for the cross-container import check.
Prints PASS/FAIL/NOTE lines tagged with ledger ids; exits 1 on any FAIL.
NOTE lines record readings of Coordinator ambiguity decisions (A-xx) that the spec leaves open.
"""
import datetime as dt
import http.client
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse

BASE = urlparse(sys.argv[1])
BASE2 = urlparse(sys.argv[2]) if len(sys.argv) > 2 else None
RESULTS = []
LAT = []
FIVEXX = []
CT_BAD = []
LOCK = threading.Lock()
RFC3339 = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")
REF = re.compile(r"^[A-Z0-9]{6,12}$")


class R:
    def __init__(self, status, headers, raw, elapsed):
        self.status, self.headers, self.raw, self.elapsed = status, headers, raw, elapsed
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


def call(method, path, body=None, token=None, key=None, raw=None, headers=None, base=None):
    b = base or BASE
    h = dict(headers or {})
    if body is not None or raw is not None:
        h.setdefault("Content-Type", "application/json")
    if token:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    c = http.client.HTTPConnection(b.hostname, b.port, timeout=15)
    t0 = time.monotonic()
    c.request(method, path, body=data, headers=h)
    resp = c.getresponse()
    out = R(resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read(), time.monotonic() - t0)
    c.close()
    with LOCK:
        LAT.append((out.elapsed, method, path))
        if out.status >= 500:
            FIVEXX.append((method, path, out.status, out.raw[:200]))
        if out.status != 204:
            ct = out.headers.get("content-type", "")
            if not (ct.lower().replace(" ", "").startswith("application/json") and "charset=utf-8" in ct.lower()):
                CT_BAD.append((method, path, out.status, ct))
            if out.status >= 400:
                e = (out.json or {}).get("error") if isinstance(out.json, dict) else None
                if not (isinstance(e, dict) and isinstance(e.get("code"), str) and isinstance(e.get("message"), str)):
                    CT_BAD.append((method, path, out.status, "error-body:" + repr(out.raw[:120])))
    return out


def check(lid, cond, detail=""):
    RESULTS.append(("PASS" if cond else "FAIL", lid, detail))
    print(("PASS" if cond else "FAIL"), lid, detail if not cond else detail[:120], flush=True)
    return cond


def note(lid, detail):
    RESULTS.append(("NOTE", lid, detail))
    print("NOTE", lid, detail, flush=True)


def expect(lid, r, status, code=None, what=""):
    ok = r.status == status and (code is None or r.code == code)
    return check(lid, ok, f"{what}: expected {status} {code or ''} got {r.status} {r.code} {r.raw[:200]!r}")


def proj(d, keys):
    return {k_: d.get(k_) for k_ in keys} if isinstance(d, dict) else d


def parse_ts(s):
    return dt.datetime.fromisoformat(s)


# ---------------------------------------------------------------- fixture
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
now_ist = dt.datetime.now(IST)
near = now_ist + dt.timedelta(minutes=40)
near = near.replace(second=0, microsecond=0)
near = near + dt.timedelta(minutes=(15 - near.minute % 15) % 15)
if near.hour == 23 and near.minute >= 30:
    near = (near + dt.timedelta(days=1)).replace(hour=0, minute=0)
NEAR = near.strftime("%Y-%m-%dT%H:%M")
FAR = (now_ist + dt.timedelta(days=3)).strftime("%Y-%m-%dT12:00")
ALLDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
LONG_RID = "r_" + "x" * 62  # 64 chars
FIXTURE = {
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"},
        {"id": "u_bob", "email": "bob@example.com", "password": "battery staple", "display_name": "Bob"},
    ],
    "restaurants": [
        {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
         "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"},
                           {"weekday": "fri", "opens": "18:00", "closes": "23:30"}],
         "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}]},
        {"id": "r_night", "name": "Nacht", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
         "opening_hours": [{"weekday": "sun", "opens": "00:00", "closes": "06:00"}],
         "tables": [{"id": "n_1", "label": "N1", "capacity": 4}, {"id": "n_2", "label": "N2", "capacity": 4}]},
        {"id": "r_ny", "name": "NY", "timezone": "America/New_York", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
         "opening_hours": [{"weekday": "sun", "opens": "00:00", "closes": "06:00"}],
         "tables": [{"id": "y_1", "label": "Y1", "capacity": 4}]},
        {"id": "r_ist", "name": "Kolkata", "timezone": "Asia/Kolkata", "slot_minutes": 15,
         "reservation_duration_minutes": 15, "cancellation_cutoff_minutes": 120,
         "opening_hours": [{"weekday": d, "opens": "00:00", "closes": "23:45"} for d in ALLDAYS],
         "tables": [{"id": "i_1", "label": "I1", "capacity": 4}, {"id": "i_2", "label": "I2", "capacity": 4},
                    {"id": "i_3", "label": "I3", "capacity": 4}]},
        {"id": "r_big", "name": "Big", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
         "opening_hours": [{"weekday": d, "opens": "10:00", "closes": "22:00"} for d in ALLDAYS],
         "tables": [{"id": f"b_{i}", "label": f"B{i}", "capacity": 4} for i in range(1, 13)]},
        {"id": LONG_RID, "name": "Long", "timezone": "Europe/Berlin", "slot_minutes": 60,
         "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 0,
         "opening_hours": [{"weekday": "thu", "opens": "12:00", "closes": "14:00"}],
         "tables": [{"id": "T" * 64, "label": "L", "capacity": 2}]},
    ],
    "reservations": [
        {"id": "res_seed_near", "reference": "SEEDNEAR1", "user_id": "u_ada", "restaurant_id": "r_ist",
         "table_id": "i_1", "starts_at_local": NEAR, "party_size": 2},
        {"id": "res_seed_far", "reference": "SEEDFAR01", "user_id": "u_ada", "restaurant_id": "r_ist",
         "table_id": "i_2", "starts_at_local": FAR, "party_size": 2},
        {"id": "res_seed_bob", "reference": "SEEDBOB01", "user_id": "u_bob", "restaurant_id": "r_anker",
         "table_id": "t_2", "starts_at_local": "2026-10-15T21:30", "party_size": 3},
    ],
}

KEYN = [0]


def k():
    KEYN[0] += 1
    return f"gate-key-{KEYN[0]}-{time.time_ns()}"


def login(email, pw):
    r = call("POST", "/auth/login", {"email": email, "password": pw})
    return r.json.get("token") if r.status == 200 else None


def create(tok, rid, tid, start, party, key=None):
    return call("POST", "/reservations", {"restaurant_id": rid, "table_id": tid, "starts_at_local": start,
                                          "party_size": party}, token=tok, key=key or k())


def get_res(tok, ref):
    return call("GET", f"/reservations/{quote(ref, safe='')}", token=tok)


def avail(rid, date, party):
    return call("GET", f"/availability?restaurant_id={quote(rid, safe='')}&date={date}&party_size={party}")


def slotmap(r):
    return {s["starts_at_local"]: s for s in r.json["slots"]}


def run():
    # ----------------------------------------------------------- health / reset
    r = call("GET", "/health")
    check("S1-004", r.status == 200 and r.json == {"status": "ok"}, repr(r))
    r = call("POST", "/_test/reset", FIXTURE)
    if not expect("S1-007", r, 204, what="reset"):
        return
    check("S1-007", r.raw == b"", "reset 204 has empty body")
    r = call("GET", "/nope/route")
    expect("S1-026", r, 404, "not_found", "unknown route")

    # ----------------------------------------------------------- restaurants
    r = call("GET", "/restaurants")
    check("S1-047", r.status == 200 and [x["id"] for x in r.json["restaurants"]] ==
          [x["id"] for x in FIXTURE["restaurants"]] and proj(r.json["restaurants"][0], ["id", "name", "timezone"]) ==
          {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin"}, repr(r)[:300])
    r = call("GET", "/restaurants/r_anker")
    fx = FIXTURE["restaurants"][0]
    ok = r.status == 200 and all(r.json.get(f) == fx[f] for f in
                                 ["id", "name", "timezone", "slot_minutes", "reservation_duration_minutes",
                                  "cancellation_cutoff_minutes"]) and         [proj(t, ["id", "label", "capacity"]) for t in r.json.get("tables", [])] == fx["tables"] and         [proj(o, ["weekday", "opens", "closes"]) for o in r.json.get("opening_hours", [])] == fx["opening_hours"]
    check("S1-048", ok, repr(r)[:300])
    expect("S1-048", call("GET", "/restaurants/r_nope"), 404, "not_found", "unknown restaurant")
    r = call("GET", "/restaurants/" + LONG_RID)
    check("S1-012", r.status == 200 and r.json["id"] == LONG_RID, "64-char restaurant id " + repr(r)[:100])

    # ----------------------------------------------------------- auth
    r = call("POST", "/auth/signup", {"email": "cy@example.com", "password": "12345678", "display_name": "Cy"})
    check("S1-027", r.status == 201 and set(r.json) >= {"user_id", "display_name", "token"} and
          r.json["display_name"] == "Cy", repr(r))
    cy_tok, cy_id = r.json["token"], r.json["user_id"]
    check("S1-012", isinstance(cy_id, str) and len(cy_id) <= 64, "user_id <= 64")
    check("S1-027", call("GET", "/reservations", token=cy_tok).status == 200, "signup token works")
    expect("S1-029", call("POST", "/auth/signup", {"email": "ada@example.com", "password": "12345678",
                                                    "display_name": "X"}), 409, "email_taken", "dup seeded email")
    r = call("POST", "/auth/signup", {"email": "ADA@example.com", "password": "12345678", "display_name": "X"})
    note("A-10", f"case-variant duplicate signup -> {r.status} {r.code}")
    expect("S1-030", call("POST", "/auth/signup", {"email": "d@example.com", "password": "1234567",
                                                    "display_name": "D"}), 422, "validation_failed", "7-char pw")
    for bad in ["noat", "a@", "@b.com", "a@b@c.com", "a b@c.com", ""]:
        expect("S1-031", call("POST", "/auth/signup", {"email": bad, "password": "12345678", "display_name": "D"}),
               422, "validation_failed", f"email {bad!r}")
    expect("S1-033", call("POST", "/auth/signup", {"email": 5, "password": "12345678", "display_name": "D"}),
           400, "malformed_request", "email wrong type")
    expect("S1-033", call("POST", "/auth/signup", {"password": "12345678", "display_name": "D"}),
           422, "validation_failed", "email missing")
    expect("S1-033", call("POST", "/auth/login", {"email": "ada@example.com"}), 422, "validation_failed",
           "login pw missing")
    expect("S1-020", call("POST", "/auth/login", raw=b"{nope"), 400, "malformed_request", "login bad json")
    r = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
    check("S1-014", r.status == 200 and r.json["user_id"] == "u_ada" and r.json["display_name"] == "Ada", repr(r))
    ada = r.json["token"]
    ada2 = login("ada@example.com", "correct horse")
    bob = login("bob@example.com", "battery staple")
    check("S1-035", ada2 and ada2 != ada and call("GET", "/reservations", token=ada).status == 200 and
          call("GET", "/reservations", token=ada2).status == 200, "two tokens both valid")
    expect("S1-032", call("POST", "/auth/login", {"email": "ada@example.com", "password": "wrong pass"}),
           401, "unauthenticated", "wrong pw")
    expect("S1-032", call("POST", "/auth/login", {"email": "zz@example.com", "password": "correct horse"}),
           401, "unauthenticated", "unknown email")
    for h in [{}, {"Authorization": "Bearer"}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"},
              {"Authorization": ada}]:
        expect("S1-034", call("GET", "/reservations", headers=h), 401, "unauthenticated", f"auth hdr {h}")

    # ----------------------------------------------------------- availability
    r = avail("r_anker", "2026-10-15", 2)
    sm = slotmap(r) if r.status == 200 else {}
    exp_slots = [f"2026-10-15T{h:02d}:{m:02d}" for h in range(18, 22) for m in (0, 30)]
    check("S1-051", r.status == 200 and [s["starts_at_local"] for s in r.json["slots"]] == exp_slots,
          repr(r)[:400])
    check("S1-050", r.status == 200 and r.json.get("restaurant_id") == "r_anker" and r.json.get("date") ==
          "2026-10-15" and r.json.get("timezone") == "Europe/Berlin" and
          sm.get("2026-10-15T18:00", {}).get("starts_at") == "2026-10-15T18:00:00+02:00", repr(r)[:300])
    check("S1-052", sm.get("2026-10-15T20:00", {}).get("available_table_ids") == ["t_1", "t_2"] and
          sm.get("2026-10-15T20:30", {}).get("available_table_ids") == ["t_1"], "seeded bob t_2 21:30 blocks 20:30+")
    r = avail("r_anker", "2026-10-15", 5)
    check("S1-052", r.status == 200 and len(r.json["slots"]) == 8 and
          all(s["available_table_ids"] == [] for s in r.json["slots"]), "party 5: slots present, empty lists")
    r = avail("r_anker", "2026-10-16", 2)
    check("S1-051", r.status == 200 and len(r.json["slots"]) == 9 and r.json["slots"][-1]["starts_at_local"] ==
          "2026-10-16T22:00", "fri closes 23:30 -> last slot 22:00")
    r = avail("r_anker", "2026-10-14", 2)
    check("S1-053", r.status == 200 and r.json["slots"] == [], "closed wed")
    r = avail("r_anker", "2026-12-03", 2)
    check("S1-084", r.status == 200 and r.json["slots"][0]["starts_at"] == "2026-12-03T18:00:00+01:00",
          "winter offset")
    for q in ["date=2026-10-15&party_size=2", "restaurant_id=r_anker&party_size=2", "restaurant_id=r_anker&date=2026-10-15"]:
        expect("S1-049", call("GET", "/availability?" + q), 422, "validation_failed", "missing param " + q)
    for ps in ["4.0", "+4", "1e9", "0", "-1", "abc", "", "%204"]:
        expect("S1-024", call("GET", f"/availability?restaurant_id=r_anker&date=2026-10-15&party_size={ps}"),
               422, "validation_failed", f"party_size={ps!r}")
    for d in ["2026-02-30", "2026-13-01", "20261015", "2026-10-15T00:00", "x"]:
        expect("S1-049", call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=2"),
               422, "validation_failed", f"date={d!r}")
    expect("S1-049", avail("r_nope", "2026-10-15", 2), 404, "not_found", "unknown restaurant")
    r = call("GET", "/availability?restaurant_id=r_nope&date=2026-10-15&party_size=x")
    note("A-11", f"unknown restaurant + bad party_size -> {r.status} {r.code}")
    r = call("GET", "/availability?restaurant_id=r_anker&date=2026-10-15&party_size=2&foo=bar")
    check("S1-011", r.status == 200, "unknown query param ignored")
    r = avail("r_anker", "2026-10-15", "0002")
    note("S1-024", f"party_size=0002 -> {r.status}")

    # ----------------------------------------------------------- create + validation
    K1 = k()
    body1 = {"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": "2026-10-15T18:00", "party_size": 4}
    r1 = call("POST", "/reservations", body1, token=ada, key=K1)
    ok = expect("S1-055", r1, 201, what="create")
    res1 = r1.json if ok else {}
    exp_fields = {"reservation_id", "reference", "restaurant_id", "table_id", "party_size", "status",
                  "starts_at_local", "starts_at", "ends_at", "created_at"}
    check("S1-055", set(res1) >= exp_fields and res1.get("status") == "confirmed" and res1.get("party_size") == 4 and
          res1.get("table_id") == "t_2" and res1.get("starts_at_local") == "2026-10-15T18:00", repr(res1))
    check("S1-056", res1.get("starts_at") == "2026-10-15T18:00:00+02:00" and
          res1.get("ends_at") == "2026-10-15T19:30:00+02:00", repr(res1))
    check("S1-010", all(RFC3339.match(res1.get(f, "")) for f in ["starts_at", "ends_at", "created_at"]), repr(res1))
    check("S1-057", bool(REF.match(res1.get("reference", ""))), res1.get("reference", ""))
    check("S1-012", len(res1.get("reservation_id", "x" * 65)) <= 64, "reservation_id <= 64")
    REF1 = res1.get("reference")

    # idempotency: replay with different key order / whitespace
    rawb = b'{ "party_size" : 4 ,"starts_at_local":"2026-10-15T18:00",  "table_id":"t_2","restaurant_id":"r_anker"}'
    r = call("POST", "/reservations", raw=rawb, token=ada, key=K1)
    check("S1-039", r.status == 200 and r.json == res1, "replay reordered body -> 200 identical " + repr(r)[:200])
    r = call("POST", "/reservations", body1, token=ada2, key=K1)
    check("S1-046", r.status == 200 and r.json == res1, "replay via other token of same user " + repr(r)[:200])
    r = call("POST", "/reservations", dict(body1, party_size="nope"), token=ada, key=K1)
    expect("S1-040", r, 409, "idempotency_key_reuse", "same key, different (invalid) body")
    r = call("POST", "/reservations", dict(body1, starts_at_local="2026-10-15T20:00", table_id="t_1", party_size=2),
             token=ada, key=K1)
    expect("S1-040", r, 409, "idempotency_key_reuse", "same key, different valid body")
    r = call("POST", "/reservations", dict(body1, table_id="t_1", party_size=2, starts_at_local="2026-10-16T18:00"),
             token=bob, key=K1)
    expect("S1-041", r, 201, what="other user same key")
    BOBREF_A = r.json.get("reference") if r.status == 201 else None
    expect("S1-058", create(ada, "r_anker", "t_2", "2026-10-15T19:00", 2), 409, "table_unavailable", "overlap 19:00")
    rb2b = create(ada, "r_anker", "t_2", "2026-10-15T19:30", 2)
    expect("S1-058", rb2b, 201, what="back-to-back 19:30 after 18:00+90")
    # failed first use leaves key unused
    KF = k()
    expect("S1-061", create(ada, "r_anker", "t_1", "2026-10-15T18:00", 3, key=KF), 422, "party_exceeds_capacity",
           "party 3 on cap-2 table")
    r = create(ada, "r_anker", "t_1", "2026-10-15T18:00", 2, key=KF)
    expect("S1-043", r, 201, what="key reused after 4xx -> first use (party == capacity accepted)")
    P1 = r.json.get("reference") if r.status == 201 else None
    # validation codes
    cases = [
        ("S1-059", "t_1", "2026-10-15T20:15", 1, 422, "not_on_slot_grid"),
        ("S1-060", "t_1", "2026-10-15T17:30", 1, 422, "outside_opening_hours"),
        ("S1-060", "t_1", "2026-10-15T22:00", 1, 422, "outside_opening_hours"),
        ("S1-060", "t_1", "2026-10-14T19:00", 1, 422, "outside_opening_hours"),
        ("S1-060", "t_1", "2026-10-15T23:00", 1, 422, "outside_opening_hours"),
        ("S1-062", "t_1", "2026-10-15T20:00", 0, 422, "validation_failed"),
        ("S1-062", "t_1", "2026-10-15T20:00", -1, 422, "validation_failed"),
        ("S1-022", "t_1", "2026-10-15T20:00", "2", 422, "validation_failed"),
        ("S1-022", "t_1", "2026-10-15T20:00", True, 422, "validation_failed"),
        ("S1-022", "t_1", "2026-10-15T20:00", 2.5, 422, "validation_failed"),
        ("S1-022", "t_1", "2026-10-15T20:00", None, 422, "validation_failed"),
        ("S1-023", "t_1", "2026-10-15T20:00:00", 1, 422, "validation_failed"),
        ("S1-023", "t_1", "2026-10-15T20:00Z", 1, 422, "validation_failed"),
        ("S1-023", "t_1", "2026-10-15T20:00+02:00", 1, 422, "validation_failed"),
        ("S1-023", "t_1", "2026-10-15 20:00", 1, 422, "validation_failed"),
        ("S1-023", "t_1", "2026-02-30T20:00", 1, 422, "validation_failed"),
        ("S1-023", "t_1", "2026-10-15T25:00", 1, 422, "validation_failed"),
        ("S1-023", "t_1", "2026-10-15T9:00", 1, 422, "validation_failed"),
        ("S1-023", "t_1", 202610152000, 1, 400, "malformed_request"),
        ("S1-064", "t_nope", "2026-10-15T20:00", 1, 404, "not_found"),
        ("S1-064", "n_1", "2026-10-15T20:00", 1, 404, "not_found"),
        ("S1-065", 5, "2026-10-15T20:00", 1, 400, "malformed_request"),
    ]
    for lid, tid, st, ps, status, code in cases:
        expect(lid, create(ada, "r_anker", tid, st, ps), status, code, f"create {tid} {st} {ps!r}")
    expect("S1-064", create(ada, "r_nope", "t_1", "2026-10-15T20:00", 1), 404, "not_found", "unknown restaurant")
    expect("S1-065", call("POST", "/reservations", {"restaurant_id": "r_anker", "starts_at_local": "2026-10-15T20:00",
                                                   "party_size": 1}, token=ada, key=k()), 422, "validation_failed",
           "missing table_id")
    expect("S1-065", call("POST", "/reservations", {"restaurant_id": 7, "table_id": "t_1",
                                                   "starts_at_local": "2026-10-15T20:00", "party_size": 1},
                          token=ada, key=k()), 400, "malformed_request", "restaurant_id wrong type")
    expect("S1-020", call("POST", "/reservations", raw=b"{bad", token=ada, key=k()), 400, "malformed_request", "bad json")
    expect("S1-020", call("POST", "/reservations", raw=b"[1,2]", token=ada, key=k()), 400, "malformed_request",
           "array body")
    expect("S1-037", call("POST", "/reservations", body1, token=ada), 400, "missing_idempotency_key", "no key")
    expect("S1-037", call("POST", "/reservations", body1, token=ada, key=""), 400, "missing_idempotency_key", "empty")
    expect("S1-025", call("POST", "/reservations", body1, token=ada, key="k" * 256), 422, "validation_failed", "256")
    r = create(ada, "r_anker", "t_1", "2026-10-16T21:30", 1, key="z" * 255)
    expect("S1-025", r, 201, what="255-char key accepted")
    expect("S1-034", call("POST", "/reservations", body1, key=k()), 401, "unauthenticated", "create no auth")
    r = call("POST", "/reservations", body1)
    note("A-01", f"no auth + no key -> {r.status} {r.code}")
    r = call("POST", "/reservations", raw=b"{bad", token=ada)
    note("A-01", f"bad json + no key -> {r.status} {r.code}")
    r = call("POST", "/reservations", dict(body1, extra_field={"x": 1}, starts_at_local="2026-10-16T18:00",
                                           table_id="t_2"), token=ada, key=k())
    check("S1-011", r.status == 201, "unknown body field ignored " + repr(r)[:150])
    # past booking allowed, cutoff still applies
    r = create(ada, "r_ist", "i_3", "2026-01-05T12:00", 2)
    expect("S1-018", r, 201, what="past booking allowed")
    PAST = r.json.get("reference") if r.status == 201 else None
    check("S1-084", r.status == 201 and r.json["starts_at"] == "2026-01-05T12:00:00+05:30", "IST offset +05:30")
    if PAST:
        expect("S1-072", call("POST", f"/reservations/{PAST}/cancel", token=ada), 409, "cutoff_passed", "cancel past")
    # long fixture ids
    r = create(ada, LONG_RID, "T" * 64, "2026-10-15T12:00", 2)
    expect("S1-012", r, 201, what="64-char restaurant/table ids in body")

    # ----------------------------------------------------------- read / cancel / patch
    r = call("GET", "/reservations", token=ada)
    lst = r.json.get("reservations", []) if r.status == 200 else []
    starts = [parse_ts(x["starts_at"]) for x in lst]
    check("S1-068", r.status == 200 and starts == sorted(starts, reverse=True) and
          all(set(x) >= exp_fields for x in lst), "ordered desc, full shape")
    check("S1-015", any(x["reference"] == "SEEDNEAR1" and x["reservation_id"] == "res_seed_near" for x in lst),
          "seeded reservation listed with fixture id/reference")
    check("S1-068", not any(x["reference"] == "SEEDBOB01" for x in lst), "no other user's bookings")
    r = call("GET", "/reservations", token=cy_tok)
    check("S1-068", r.status == 200 and r.json == {"reservations": []}, "empty list " + repr(r)[:100])
    expect("S1-069", get_res(ada, "SEEDBOB01"), 404, "not_found", "other's ref")
    expect("S1-069", get_res(ada, "NOPE000"), 404, "not_found", "unknown ref")
    r = get_res(ada, REF1)
    check("S1-069", r.status == 200 and r.json == res1, "get own")
    expect("S1-073", call("POST", "/reservations/SEEDBOB01/cancel", token=ada), 404, "not_found", "cancel other's")
    expect("S1-078", call("PATCH", "/reservations/SEEDBOB01", {"party_size": 1}, token=ada), 404, "not_found",
           "patch other's")
    expect("S1-034", call("POST", f"/reservations/{REF1}/cancel"), 401, "unauthenticated", "cancel no auth")
    # cutoff (seeded near)
    expect("S1-072", call("POST", "/reservations/SEEDNEAR1/cancel", token=ada), 409, "cutoff_passed", "cancel near")
    expect("S1-076", call("PATCH", "/reservations/SEEDNEAR1", {"party_size": 3}, token=ada), 409, "cutoff_passed",
           "patch near")
    expect("S1-076", call("PATCH", "/reservations/SEEDNEAR1", {"starts_at_local": FAR}, token=ada), 409,
           "cutoff_passed", "patch near to far")
    r = get_res(ada, "SEEDNEAR1")
    check("S1-072", r.status == 200 and r.json["status"] == "confirmed" and r.json["party_size"] == 2,
          "near unchanged")
    # PATCH P1 (t_1 18:00 p2)
    if P1:
        before = get_res(ada, P1).json
        r = call("PATCH", f"/reservations/{P1}", {"starts_at_local": "2026-10-15T18:30"}, token=ada)
        check("S1-079", r.status == 200 and r.json["starts_at_local"] == "2026-10-15T18:30" and
              r.json["ends_at"] == "2026-10-15T20:00:00+02:00" and r.json["reference"] == P1 and
              r.json["reservation_id"] == before["reservation_id"] and r.json["table_id"] == "t_1" and
              r.json["party_size"] == 2 and r.json["created_at"] == before["created_at"],
              "patch overlapping own interval " + repr(r)[:200])
        after = r.json
        expect("S1-075", call("PATCH", f"/reservations/{P1}", {"party_size": 3}, token=ada), 422,
               "party_exceeds_capacity", "patch party")
        expect("S1-075", call("PATCH", f"/reservations/{P1}", {"table_id": "t_2"}, token=ada), 409,
               "table_unavailable", "patch onto ada's t_2 18:00")
        expect("S1-075", call("PATCH", f"/reservations/{P1}", {"starts_at_local": "2026-10-15T18:15"}, token=ada),
               422, "not_on_slot_grid", "patch grid")
        expect("S1-075", call("PATCH", f"/reservations/{P1}", {"starts_at_local": "x"}, token=ada), 422,
               "validation_failed", "patch bad start")
        expect("S1-075", call("PATCH", f"/reservations/{P1}", {"starts_at_local": 5}, token=ada), 400,
               "malformed_request", "patch start wrong type")
        expect("S1-075", call("PATCH", f"/reservations/{P1}", {"party_size": "2"}, token=ada), 422,
               "validation_failed", "patch party string")
        expect("S1-075", call("PATCH", f"/reservations/{P1}", {"table_id": "n_1"}, token=ada), 404,
               "not_found", "patch table of other restaurant")
        expect("S1-020", call("PATCH", f"/reservations/{P1}", raw=b"{x", token=ada), 400, "malformed_request",
               "patch bad json")
        r = get_res(ada, P1)
        check("S1-079", r.status == 200 and r.json == after, "failed patches left booking unchanged")
        sm = slotmap(avail("r_anker", "2026-10-15", 2))
        check("S1-079", "t_1" not in sm["2026-10-15T18:30"]["available_table_ids"] and
              "t_1" in sm["2026-10-15T20:00"]["available_table_ids"], "occupancy follows patched booking")
        r = call("PATCH", f"/reservations/{P1}", {}, token=ada)
        check("S1-074", r.status == 200 and r.json == after, "empty patch 200 unchanged")
    # cancel REF1 then replay K1
    r = call("POST", f"/reservations/{REF1}/cancel", token=ada)
    check("S1-070", r.status == 200 and r.json.get("status") == "cancelled" and r.json.get("reference") == REF1 and
          r.json.get("reservation_id") == res1.get("reservation_id"), repr(r)[:200])
    sm = slotmap(avail("r_anker", "2026-10-15", 4))
    check("S1-054", "t_2" in sm["2026-10-15T18:00"]["available_table_ids"], "cancel frees slot")
    r = call("POST", f"/reservations/{REF1}/cancel", token=ada)
    check("S1-071", r.status == 200 and r.json.get("status") == "cancelled", "cancel twice")
    r = call("POST", "/reservations", body1, token=ada, key=K1)
    check("S1-044", r.status == 200 and r.json == res1, "replay after cancel returns original")
    sm = slotmap(avail("r_anker", "2026-10-15", 4))
    check("S1-044", "t_2" in sm["2026-10-15T18:00"]["available_table_ids"], "replay did not re-book")
    expect("S1-077", call("PATCH", f"/reservations/{REF1}", {"party_size": 2}, token=ada), 409,
           "reservation_cancelled", "patch cancelled")
    # different path same key same body is not a replay
    KP = k()
    dual = {"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": "2026-10-22T18:00", "party_size": 2}
    rr = call("POST", "/reservations", dual, token=ada, key=KP)
    expect("S1-042", rr, 201, what="dual body on /reservations")
    if rr.status == 201:
        dual["moves"] = [{"reference": rr.json["reference"]}]
        rr2 = call("POST", "/reservations", dual, token=ada, key=k())
        expect("S1-058", rr2, 409, "table_unavailable", "same slot again")
        r = call("POST", "/reservation-moves", dual, token=ada, key=KP)
        note("S1-042", f"same key on moves path after /reservations use (body differs by moves field) -> {r.status}")
        KD = k()
        d2 = {"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": "2026-10-29T18:00", "party_size": 2,
              "moves": [{"reference": rr.json["reference"]}]}
        a = call("POST", "/reservation-moves", d2, token=ada, key=KD)
        b = call("POST", "/reservations", d2, token=ada, key=KD)
        check("S1-042", a.status == 201 and b.status == 201 and "reservations" in a.json and "reference" in b.json,
              f"identical body+key on two paths -> {a.status} / {b.status} {b.raw[:120]!r}")

    # ----------------------------------------------------------- DST
    r = avail("r_night", "2026-03-29", 2)
    got = [s["starts_at_local"][11:] for s in r.json["slots"]] if r.status == 200 else None
    check("S1-081", got == ["00:00", "00:30", "01:00", "01:30", "03:00", "03:30", "04:00", "04:30"],
          f"berlin spring slots {got}")
    sm = slotmap(r) if r.status == 200 else {}
    check("S1-084", sm.get("2026-03-29T01:30", {}).get("starts_at") == "2026-03-29T01:30:00+01:00" and
          sm.get("2026-03-29T03:00", {}).get("starts_at") == "2026-03-29T03:00:00+02:00", "spring offsets")
    expect("S1-081", create(ada, "r_night", "n_1", "2026-03-29T02:30", 2), 422, "invalid_local_time", "berlin gap")
    expect("S1-081", create(ada, "r_night", "n_1", "2026-03-29T02:00", 2), 422, "invalid_local_time", "berlin gap 2")
    r = create(ada, "r_night", "n_1", "2026-03-29T01:30", 2)
    check("S1-083", r.status == 201 and r.json["ends_at"] == "2026-03-29T04:00:00+02:00", "spring 01:30+90 " + repr(r)[:200])
    r = avail("r_night", "2026-10-25", 2)
    got = [s["starts_at_local"][11:] for s in r.json["slots"]] if r.status == 200 else None
    check("S1-082", got == ["00:00", "00:30", "01:00", "01:30", "02:00", "02:30", "03:00", "03:30", "04:00", "04:30"],
          f"berlin fall slots {got}")
    sm = slotmap(r) if r.status == 200 else {}
    check("S1-082", sm.get("2026-10-25T02:30", {}).get("starts_at") == "2026-10-25T02:30:00+02:00" and
          sm.get("2026-10-25T03:00", {}).get("starts_at") == "2026-10-25T03:00:00+01:00", "fall offsets first occurrence")
    r = create(ada, "r_night", "n_1", "2026-10-25T01:30", 2)
    check("S1-083", r.status == 201 and r.json["starts_at"] == "2026-10-25T01:30:00+02:00" and
          r.json["ends_at"] == "2026-10-25T02:00:00+01:00", "fall 01:30+90 ends 02:00+01:00 " + repr(r)[:200])
    r = create(ada, "r_night", "n_1", "2026-10-25T02:30", 2)
    expect("S1-083", r, 409, "table_unavailable", "02:30(+02) overlaps 01:30(+02)+90 absolute")
    r = create(ada, "r_night", "n_2", "2026-10-25T02:30", 2)
    check("S1-082", r.status == 201 and r.json["starts_at"] == "2026-10-25T02:30:00+02:00" and
          r.json["ends_at"] == "2026-10-25T03:00:00+01:00", "02:30 first occurrence " + repr(r)[:200])
    r = create(ada, "r_night", "n_2", "2026-10-25T03:00", 2)
    expect("S1-083", r, 201, what="03:00(+01) back-to-back after 02:30(+02)+90 (absolute)")
    sm = slotmap(avail("r_night", "2026-10-25", 2))
    # n_1 [23:30Z,01:00Z) n_2 [00:30Z,02:00Z) and [02:00Z,03:30Z); 01:00+02 = [23:00Z,00:30Z) touches n_2 only at its end
    check("S1-083", sm["2026-10-25T02:00"]["available_table_ids"] == [] and
          sm["2026-10-25T01:00"]["available_table_ids"] == ["n_2"] and
          sm["2026-10-25T03:00"]["available_table_ids"] == ["n_1"], "availability uses absolute overlap")
    r = avail("r_ny", "2026-03-08", 2)
    got = [s["starts_at_local"][11:] for s in r.json["slots"]] if r.status == 200 else None
    check("S1-081", got is not None and "02:00" not in got and "02:30" not in got and "03:00" in got, f"ny spring {got}")
    expect("S1-081", create(ada, "r_ny", "y_1", "2026-03-08T02:30", 2), 422, "invalid_local_time", "ny gap")
    r = create(ada, "r_ny", "y_1", "2026-11-01T01:00", 2)
    check("S1-083", r.status == 201 and r.json["starts_at"] == "2026-11-01T01:00:00-04:00" and
          r.json["ends_at"] == "2026-11-01T01:30:00-05:00", "ny fall " + repr(r)[:200])
    r = avail("r_ny", "2026-11-01", 2)
    sm = slotmap(r) if r.status == 200 else {}
    check("S1-082", sm.get("2026-11-01T01:30", {}).get("starts_at") == "2026-11-01T01:30:00-04:00" and
          [s["starts_at_local"] for s in r.json["slots"]].count("2026-11-01T01:30") == 1, "ny repeated once")
    r = avail("r_ny", "2026-07-05", 2)
    check("S1-084", r.status == 200 and r.json["slots"][0]["starts_at"] == "2026-07-05T00:00:00-04:00", "ny summer")

    # ----------------------------------------------------------- moves
    D = "2026-11-12"
    m1 = create(ada, "r_big", "b_1", f"{D}T12:00", 2).json
    m2 = create(ada, "r_big", "b_2", f"{D}T12:00", 2).json
    c1 = create(ada, "r_big", "b_4", f"{D}T12:00", 2).json
    call("POST", f"/reservations/{c1['reference']}/cancel", token=ada)
    bobb = create(bob, "r_big", "b_3", f"{D}T16:00", 2).json
    M1, M2, C1 = m1["reference"], m2["reference"], c1["reference"]
    KM1 = k()
    swap = {"moves": [{"reference": M1, "table_id": "b_2"}, {"reference": M2, "table_id": "b_1"}]}
    r = call("POST", "/reservation-moves", swap, token=ada, key=KM1)
    ok = r.status == 201 and [x["reference"] for x in r.json["reservations"]] == [M1, M2] and \
        r.json["reservations"][0]["table_id"] == "b_2" and r.json["reservations"][1]["table_id"] == "b_1"
    check("S1-100", ok, "swap " + repr(r)[:300])
    swap_resp = r.json
    if ok:
        x = r.json["reservations"][0]
        check("S1-098", x["reservation_id"] == m1["reservation_id"] and x["created_at"] == m1["created_at"] and
              x["starts_at"] == m1["starts_at"] and x["party_size"] == 2, "identity kept")
    r = call("POST", "/reservation-moves", swap, token=ada, key=KM1)
    check("S1-104", r.status == 200 and r.json == swap_resp, "moves replay")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "table_id": "b_9"}]}, token=ada, key=KM1)
    expect("S1-093", r, 409, "idempotency_key_reuse", "moves key reuse")
    snap = {M1: get_res(ada, M1).json, M2: get_res(ada, M2).json}
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "foo": 1}]}, token=ada, key=k())
    check("S1-101", r.status == 201 and r.json["reservations"][0] == snap[M1], "no-op move " + repr(r)[:200])
    KM3 = k()
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "starts_at_local": f"{D}T14:00"},
                                                       {"reference": M2, "party_size": 99}]}, token=ada, key=KM3)
    expect("S1-102", r, 422, "party_exceeds_capacity", "second item fails")
    check("S1-102", get_res(ada, M1).json == snap[M1], "first item not applied")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "starts_at_local": f"{D}T14:00"}]},
             token=ada, key=KM3)
    expect("S1-102", r, 201, what="failed batch key reusable")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "table_id": "b_3",
                                                       "starts_at_local": f"{D}T16:30"}]}, token=ada, key=k())
    expect("S1-100", r, 409, "table_unavailable", "overlap with unlisted (bob)")
    m1now = get_res(ada, M1).json
    check("S1-102", m1now["starts_at_local"] == f"{D}T14:00" and m1now["table_id"] == "b_2", "unchanged after 409")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "table_id": "b_5", "starts_at_local": f"{D}T18:00"},
                                                       {"reference": M2, "table_id": "b_5", "starts_at_local": f"{D}T18:30"}]},
             token=ada, key=k())
    expect("S1-100", r, 409, "table_unavailable", "overlap among resulting")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": C1}, {"reference": "NOPE01"}]}, token=ada, key=k())
    expect("S1-099", r, 409, "reservation_cancelled", "cancelled first in input order")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": "NOPE01"}, {"reference": C1}]}, token=ada, key=k())
    expect("S1-099", r, 404, "not_found", "unknown first in input order")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "party_size": 99}, {"reference": C1}]},
             token=ada, key=k())
    expect("S1-099", r, 422, "party_exceeds_capacity", "validation error of item 1 precedes cancelled item 2")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "table_id": "b_3", "starts_at_local": f"{D}T16:00"},
                                                       {"reference": M2, "party_size": 99}]}, token=ada, key=k())
    expect("S1-099", r, 422, "party_exceeds_capacity", "non-occupancy error beats occupancy conflict")
    expect("S1-097", call("POST", "/reservation-moves", {"moves": [{"reference": "SEEDNEAR1", "party_size": 99}]},
                          token=ada, key=k()), 409, "cutoff_passed", "cutoff precedes field errors")
    expect("S1-095", call("POST", "/reservation-moves", {"moves": [{"reference": bobb["reference"]}]}, token=ada,
                          key=k()), 404, "not_found", "other owner's ref")
    expect("S1-096", call("POST", "/reservation-moves", {"moves": [{"reference": M1}, {"reference": P1}]},
                          token=ada, key=k()), 422, "validation_failed", "different restaurants")
    shapes = [{}, {"moves": []}, {"moves": "x"}, {"moves": [5]}, {"moves": [{}]}, {"moves": [{"reference": 5}]},
              {"moves": [{"reference": M1}, {"reference": M1}]},
              {"moves": [{"reference": M1}] + [{"reference": f"X{i:05d}"} for i in range(8)]}]
    for s in shapes:
        expect("S1-094", call("POST", "/reservation-moves", s, token=ada, key=k()), 422, "validation_failed",
               "shape " + json.dumps(s)[:60])
    expect("S1-093", call("POST", "/reservation-moves", swap, key=k()), 401, "unauthenticated", "moves no auth")
    expect("S1-093", call("POST", "/reservation-moves", swap, token=ada), 400, "missing_idempotency_key", "moves no key")
    expect("S1-093", call("POST", "/reservation-moves", raw=b"{x", token=ada, key=k()), 400, "malformed_request",
           "moves bad json")
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "table_id": 5}]}, token=ada, key=k())
    note("A-12", f"moves item table_id wrong type -> {r.status} {r.code}")
    # chain: M1 -> where M2 is, M2 -> elsewhere at same time (overlap with own old interval)
    m1now, m2now = get_res(ada, M1).json, get_res(ada, M2).json
    r = call("POST", "/reservation-moves", {"moves": [{"reference": M1, "table_id": m2now["table_id"],
                                                       "starts_at_local": m2now["starts_at_local"]},
                                                      {"reference": M2, "table_id": "b_6"}]}, token=ada, key=k())
    expect("S1-100", r, 201, what="chain into slot vacated by another listed booking")
    # replay after cancel of a moved booking
    call("POST", f"/reservations/{M2}/cancel", token=ada)
    r = call("POST", "/reservation-moves", swap, token=ada, key=KM1)
    check("S1-104", r.status == 200 and r.json == swap_resp, "moves replay after cancel returns original")
    check("S1-104", get_res(ada, M2).json["status"] == "cancelled", "replay changed nothing")

    # ----------------------------------------------------------- concurrency
    def burst(fns):
        bar = threading.Barrier(len(fns))

        def w(f):
            bar.wait()
            return f()
        with ThreadPoolExecutor(len(fns)) as ex:
            return list(ex.map(w, fns))

    D2 = "2026-11-26"
    fns = [(lambda i=i: create(ada if i % 2 else bob, "r_big", "b_6", f"{D2}T13:00", 2)) for i in range(50)]
    t0 = time.monotonic()
    rs = burst(fns)
    wall = time.monotonic() - t0
    sts = sorted(x.status for x in rs)
    check("S1-067", sts.count(201) == 1 and sts.count(409) == 49 and all(x.code == "table_unavailable" for x in rs
                                                                          if x.status == 409),
          f"50 concurrent creates statuses {dict((s, sts.count(s)) for s in set(sts))}")
    check("S1-005", max(x.elapsed for x in rs) < 5.0, f"max latency {max(x.elapsed for x in rs):.2f}s wall {wall:.2f}s")
    sm = slotmap(avail("r_big", D2, 2))
    check("S1-067", "b_6" not in sm[f"{D2}T13:00"]["available_table_ids"], "slot occupied once")
    KC = k()
    bodyc = {"restaurant_id": "r_big", "table_id": "b_7", "starts_at_local": f"{D2}T13:00", "party_size": 2}
    before_n = len(call("GET", "/reservations", token=ada).json["reservations"])
    rs = burst([(lambda: call("POST", "/reservations", bodyc, token=ada, key=KC)) for _ in range(20)])
    sts = sorted(x.status for x in rs)
    first = [x for x in rs if x.status == 201]
    check("S1-045", sts.count(201) == 1 and sts.count(200) == 19 and first and all(x.json == first[0].json for x in rs),
          f"20 concurrent identical {dict((s, sts.count(s)) for s in set(sts))}")
    after_n = len(call("GET", "/reservations", token=ada).json["reservations"])
    check("S1-045", after_n == before_n + 1, f"exactly one reservation created ({before_n}->{after_n})")
    # mixed contention: moves vs creates vs patches on b_1 18:00/18:30/19:00
    D3 = "2026-11-19"
    srcs10 = [create(ada, "r_big", f"b_{i}", f"{D3}T10:00", 2).json["reference"] for i in range(2, 12)]
    srcs5 = [create(ada, "r_big", f"b_{i}", f"{D3}T12:00", 2).json["reference"] for i in range(2, 7)]
    fns = [(lambda ref=ref: call("POST", "/reservation-moves", {"moves": [
        {"reference": ref, "table_id": "b_1", "starts_at_local": f"{D3}T18:00"}]}, token=ada, key=k())) for ref in srcs10]
    fns += [(lambda: create(bob, "r_big", "b_1", f"{D3}T18:30", 2)) for _ in range(10)]
    fns += [(lambda ref=ref: call("PATCH", f"/reservations/{ref}", {"table_id": "b_1",
                                                                  "starts_at_local": f"{D3}T19:00"}, token=ada))
            for ref in srcs5]
    rs = burst(fns)
    wins = [x for x in rs if x.status in (200, 201)]
    losses = [x for x in rs if x.status == 409 and x.code == "table_unavailable"]
    check("S1-080", len(wins) == 1 and len(losses) == 24, f"mixed contention wins={len(wins)} 409s={len(losses)} "
          f"other={[x.status for x in rs if x not in wins and x not in losses]}")
    on_b1 = []
    for tok in (ada, bob):
        for x in call("GET", "/reservations", token=tok).json["reservations"]:
            if x["restaurant_id"] == "r_big" and x["table_id"] == "b_1" and x["status"] == "confirmed" and \
                    x["starts_at_local"].startswith(D3):
                on_b1.append((parse_ts(x["starts_at"]), parse_ts(x["ends_at"])))
    on_b1.sort()
    check("S1-105", all(on_b1[i][1] <= on_b1[i + 1][0] for i in range(len(on_b1) - 1)) and len(on_b1) == 1,
          f"b_1 confirmed bookings on {D3}: {len(on_b1)}")
    # atomic batches under contention: each batch = contested item + uncontested item
    D4 = "2026-11-20"
    pairs = []
    for i in range(2, 12):
        a = create(ada, "r_big", f"b_{i}", f"{D4}T10:00", 2).json["reference"]
        b = create(ada, "r_big", f"b_{i}", f"{D4}T14:00", 2).json["reference"]
        pairs.append((a, b))
    fns = [(lambda a=a, b=b: call("POST", "/reservation-moves", {"moves": [
        {"reference": b, "starts_at_local": f"{D4}T16:00"},
        {"reference": a, "table_id": "b_12", "starts_at_local": f"{D4}T20:00"}]}, token=ada, key=k()))
        for a, b in pairs]
    rs = burst(fns)
    wins = [i for i, x in enumerate(rs) if x.status == 201]
    check("S1-105", len(wins) == 1 and all(x.status == 409 for i, x in enumerate(rs) if i not in wins),
          f"contended batches: wins={wins} statuses={[x.status for x in rs]}")
    partial = []
    for i, (a, b) in enumerate(pairs):
        bj = get_res(ada, b).json
        moved = bj["starts_at_local"] == f"{D4}T16:00"
        if moved != (i in wins):
            partial.append(b)
    check("S1-102", not partial, f"no partial batch visible: {partial}")
    # identical concurrent moves
    KMC = k()
    tgt = pairs[0][0] if 0 not in wins else pairs[1][0]
    bodym = {"moves": [{"reference": tgt, "starts_at_local": f"{D4}T12:00"}]}
    rs = burst([(lambda: call("POST", "/reservation-moves", bodym, token=ada, key=KMC)) for _ in range(10)])
    sts = sorted(x.status for x in rs)
    check("S1-045", sts.count(201) == 1 and sts.count(200) == 9 and all(x.json == rs[0].json for x in rs),
          f"10 identical concurrent moves {sts}")

    # ----------------------------------------------------------- export / import
    KFAIL = k()
    expect("S1-088", create(ada, "r_anker", "t_1", "2026-10-15T20:00", 9, key=KFAIL), 422, "party_exceeds_capacity",
           "failed key before export")
    ada_before = call("GET", "/reservations", token=ada).json
    bob_before = call("GET", "/reservations", token=bob).json
    r = call("GET", "/_test/export")
    check("S1-085", r.status == 200 and r.json.get("track") == "tablekeeper" and r.json.get("format_version") == 1
          and isinstance(r.json.get("state"), dict), repr(r)[:200])
    E1 = r.json
    E1raw = r.raw
    check("S1-036", b"correct horse" not in E1raw and b"battery staple" not in E1raw and b"12345678" not in E1raw,
          "no plaintext passwords in export")
    r = call("POST", "/auth/signup", {"email": "zed@example.com", "password": "zedzedzed", "display_name": "Zed"})
    zed = r.json["token"]
    KAFTER = k()
    expect("S1-090", create(ada, "r_anker", "t_1", "2026-10-29T20:00", 2, key=KAFTER), 201, what="write after export")
    call("POST", f"/reservations/{M1}/cancel", token=ada)
    check("S1-090", call("GET", "/_test/export").json != E1, "later writes visible in a new export only")
    # invalid imports leave state unchanged
    cur_ada = call("GET", "/reservations", token=ada).json
    bad = [(dict(E1, track="pocketful"), 422), (dict(E1, format_version=2), 422),
           ({k_: v for k_, v in E1.items() if k_ != "state"}, 422), (dict(E1, state="garbage"), 422),
           ({"track": "tablekeeper", "format_version": 1}, 422)]
    for body, st in bad:
        expect("S1-087", call("POST", "/_test/import", body), st, "validation_failed", "bad import " + str(list(body))[:60])
    expect("S1-087", call("POST", "/_test/import", raw=b"{nope"), 400, "malformed_request", "import bad json")
    r = call("POST", "/_test/import", dict(E1, state={}))
    note("S1-087", f"import with state={{}} -> {r.status} {r.code}")
    if r.status == 204:
        call("POST", "/_test/import", E1)
    else:
        check("S1-087", call("GET", "/reservations", token=ada).json == cur_ada and
              call("GET", "/reservations", token=zed).status == 200, "state unchanged after rejected imports")
        r = call("POST", "/reservations", body1, token=ada, key=K1)
        check("S1-087", r.status == 200 and r.json == res1, "receipts unchanged after rejected imports " + repr(r)[:120])
        check("S1-087", call("GET", "/reservations", token=ada).json == cur_ada, "replay after rejected imports booked nothing")
    for attempt in range(2):
        r = call("POST", "/_test/import", E1)
        expect("S1-086", r, 204, what=f"import #{attempt + 1}")
    check("S1-086", call("GET", "/reservations", token=ada).json == ada_before and
          call("GET", "/reservations", token=bob).json == bob_before, "state equals snapshot, no duplicates")
    expect("S1-089", call("GET", "/reservations", token=zed), 401, "unauthenticated", "post-export token gone")
    expect("S1-089", call("POST", "/auth/login", {"email": "zed@example.com", "password": "zedzedzed"}), 401,
           "unauthenticated", "post-export user gone")
    check("S1-088", login("cy@example.com", "12345678") is not None and
          call("GET", "/reservations", token=cy_tok).status == 200, "signup user + token survive")
    r = call("POST", "/reservations", body1, token=ada, key=K1)
    check("S1-088", r.status == 200 and r.json == res1, "replay after import")
    expect("S1-088", call("POST", "/reservations", dict(body1, party_size=1), token=ada, key=K1), 409,
           "idempotency_key_reuse", "reuse after import")
    r = call("POST", "/reservation-moves", swap, token=ada, key=KM1)
    check("S1-104", r.status == 200 and r.json == swap_resp, "moves receipt survives import")
    expect("S1-088", create(ada, "r_anker", "t_1", "2026-10-15T21:30", 2, key=KFAIL), 201, what="failed key reusable")
    r = create(ada, "r_anker", "t_1", "2026-10-29T20:00", 2, key=KAFTER)
    expect("S1-088", r, 201, what="post-export key is unused after import")
    refs = [x["reference"] for x in call("GET", "/reservations", token=ada).json["reservations"]] + \
        [x["reference"] for x in call("GET", "/reservations", token=bob).json["reservations"]]
    check("S1-092", len(refs) == len(set(refs)), f"{len(refs)} refs unique")
    if BASE2:
        r = call("POST", "/_test/import", E1, base=BASE2)
        expect("S1-090", r, 204, what="import into fresh container")
        r = call("POST", "/reservations", body1, token=ada, key=K1, base=BASE2)
        check("S1-090", r.status == 200 and r.json == res1, "fresh container: replay with old token")
        r = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}, base=BASE2)
        expect("S1-088", r, 200, what="fresh container: hashed-password login")
        r = call("GET", "/reservations", token=bob, base=BASE2)
        check("S1-088", r.status == 200 and r.json == bob_before, "fresh container: bob's list")
        r2 = call("POST", "/reservations", {"restaurant_id": "r_big", "table_id": "b_9",
                                            "starts_at_local": "2026-12-10T12:00", "party_size": 2},
                  token=ada, key=k(), base=BASE2)
        check("S1-092", r2.status == 201 and r2.json["reference"] not in
              {x["reference"] for x in ada_before["reservations"] + bob_before["reservations"]},
              "fresh container generated ref does not collide")
    # reset clears everything
    call("POST", "/_test/reset", FIXTURE)
    expect("S1-008", call("GET", "/reservations", token=ada), 401, "unauthenticated", "old token after reset")
    expect("S1-008", call("POST", "/auth/login", {"email": "cy@example.com", "password": "12345678"}), 401,
           "unauthenticated", "signup user after reset")
    ada = login("ada@example.com", "correct horse")
    r = call("POST", "/reservations", body1, token=ada, key=K1)
    expect("S1-008", r, 201, what="idempotency records cleared by reset")
    lst = call("GET", "/reservations", token=ada).json["reservations"]
    check("S1-007", sorted(x["reference"] for x in lst) == sorted(["SEEDNEAR1", "SEEDFAR01", r.json["reference"]]),
          "only fixture + new")
    # cutoff: new start not cutoff-checked (A-04), patch far -> near
    r = call("PATCH", "/reservations/SEEDFAR01", {"starts_at_local": NEAR}, token=ada)
    note("A-04", f"patch far booking to a start inside cutoff -> {r.status} {r.code}")


if __name__ == "__main__":
    t0 = time.monotonic()
    try:
        run()
    except Exception as e:  # noqa
        import traceback
        traceback.print_exc()
        RESULTS.append(("FAIL", "PROBE", f"probe crashed: {e!r}"))
    check("S1-006", not FIVEXX, f"5xx responses: {FIVEXX[:5]}")
    check("S1-009/S1-019", not CT_BAD, f"content-type/error-body violations: {CT_BAD[:5]}")
    LAT.sort(reverse=True)
    print(f"slowest: {[(round(a, 3), m, p[:40]) for a, m, p in LAT[:3]]}")
    fails = [x for x in RESULTS if x[0] == "FAIL"]
    print(f"SUMMARY pass={sum(1 for x in RESULTS if x[0] == 'PASS')} fail={len(fails)} "
          f"note={sum(1 for x in RESULTS if x[0] == 'NOTE')} requests={len(LAT)} {time.monotonic() - t0:.1f}s")
    for f in fails:
        print("FAILED", f[1], f[2][:300])
    sys.exit(1 if fails else 0)
