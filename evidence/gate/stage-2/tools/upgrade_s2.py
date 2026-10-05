"""Gate: stage-1 export -> stage-2 import (S2-026..S2-029 at the API level). Stdlib only.
Usage: py -3.12 upgrade_s2.py http://STAGE1 http://STAGE2_FRESH"""
import http.client
import json
import sys
import time
from urllib.parse import urlparse

S1, S2 = urlparse(sys.argv[1]), urlparse(sys.argv[2])
RES = []


def call(b, method, path, body=None, token=None, key=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    c = http.client.HTTPConnection(b.hostname, b.port, timeout=15)
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        j = json.loads(raw) if raw else None
    except Exception:
        j = None
    return r.status, j


def check(lid, cond, detail=""):
    RES.append(cond)
    print("PASS" if cond else "FAIL", lid, "" if cond else detail[:400], flush=True)


FIX = {"users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"}],
       "restaurants": [{"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30,
                        "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
                        "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}],
                        "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}]}],
       "reservations": [{"id": "res_seed", "reference": "SEEDREF01", "user_id": "u_ada", "restaurant_id": "r_anker",
                         "table_id": "t_1", "starts_at_local": "2026-11-12T18:00", "party_size": 2}]}
st, _ = call(S1, "POST", "/_test/reset", FIX)
check("setup", st == 204, f"stage-1 reset {st}")
st, cy = call(S1, "POST", "/auth/signup", {"email": "cy@example.com", "password": "cy password", "display_name": "Cy"})
cy_tok = cy["token"]
st, a = call(S1, "POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
ada = a["token"]
B1 = {"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": "2026-11-12T19:00", "party_size": 3}
st, r1 = call(S1, "POST", "/reservations", B1, token=ada, key="K1")
B2 = {"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": "2026-11-12T20:00", "party_size": 2}
st, r2 = call(S1, "POST", "/reservations", B2, token=ada, key="K-LOST")      # the browser never saw this response
BM = {"moves": [{"reference": r1["reference"], "starts_at_local": "2026-11-12T19:30"}]}
st, rm = call(S1, "POST", "/reservation-moves", BM, token=ada, key="KM")
st, _ = call(S1, "POST", "/reservations", dict(B1, party_size=9), token=ada, key="KF")   # failed, key stays unused
check("setup", st == 422, f"failed key setup {st}")
st, e = call(S1, "GET", "/_test/export")
check("setup", st == 200 and e["format_version"] == 1, "stage-1 export")
st, _ = call(S2, "POST", "/_test/import", e)
check("S2-026", st == 204, f"stage-2 imports stage-1 export: {st}")
st, lst = call(S2, "GET", "/reservations", token=ada)
check("S2-027", st == 200, f"stage-1 bearer token works on stage-2: {st}")
check("S2-026", st == 200 and sorted(x["reference"] for x in lst["reservations"]) ==
      sorted(["SEEDREF01", r1["reference"], r2["reference"]]), f"reservations carried: {lst}")
check("S2-035", st == 200 and all(x.get("table_ids") == [x.get("table_id")] for x in lst["reservations"]),
      f"imported reservations served in stage-2 shape: {lst}")
st, _ = call(S2, "GET", "/reservations", token=cy_tok)
check("S2-027", st == 200, f"signup token from stage-1 works: {st}")
st, _ = call(S2, "POST", "/auth/login", {"email": "cy@example.com", "password": "cy password"})
check("S2-026", st == 200, f"hashed-password login of a stage-1 signup user: {st}")
st, g = call(S2, "GET", f"/reservations/{r2['reference']}", token=ada)
check("S2-028", st == 200 and g["reference"] == r2["reference"], "retained reference resolves (lookup API)")
st, rep = call(S2, "POST", "/reservations", B2, token=ada, key="K-LOST")
check("S2-029", st == 200 and rep.get("reference") == r2["reference"] and rep.get("reservation_id") == r2["reservation_id"],
      f"lost-before-export booking retry -> 200 original: {st} {rep}")
exact = rep == r2
print(f"NOTE S2-029 replayed body identical to the stage-1 original: {exact}; "
      f"extra keys {sorted(set(rep or {}) - set(r2))}, missing {sorted(set(r2) - set(rep or {}))}")
st, rep = call(S2, "POST", "/reservations", B1, token=ada, key="K1")
check("S2-026", st == 200 and rep["reference"] == r1["reference"] and rep["starts_at_local"] == "2026-11-12T19:00",
      f"K1 replay returns original (pre-move) response: {st} {rep}")
st, rep = call(S2, "POST", "/reservation-moves", BM, token=ada, key="KM")
check("S2-026", st == 200 and [x["reference"] for x in rep["reservations"]] == [r1["reference"]], f"move receipt: {st}")
st, rep = call(S2, "POST", "/reservations", dict(B1, party_size=2), token=ada, key="K1")
check("S2-026", st == 409 and rep["error"]["code"] == "idempotency_key_reuse", f"reuse 409: {st} {rep}")
st, rep = call(S2, "POST", "/reservations", {"restaurant_id": "r_anker", "table_ids": ["t_2"],
                                             "starts_at_local": "2026-11-12T21:30", "party_size": 2}, token=ada, key="KF")
check("S2-026", st == 201, f"failed stage-1 key is unused on stage-2: {st} {rep}")
st, av = call(S2, "GET", "/availability?restaurant_id=r_anker&date=2026-11-12&party_size=2")
s = {x["starts_at_local"][11:]: x for x in av["slots"]} if st == 200 else {}
check("S2-026", st == 200 and "t_1" not in s["18:00"]["available_table_ids"] and "t_2" not in s["19:30"]["available_table_ids"]
      and "available_options" in s["18:00"], f"imported occupancy + options: {s.get('18:00')}")
st, r3 = call(S2, "POST", "/reservations", {"restaurant_id": "r_anker", "table_id": "t_1",
                                            "starts_at_local": "2026-11-12T21:30", "party_size": 1}, token=ada, key="KN")
check("S1-092", st == 201 and r3["reference"] not in {"SEEDREF01", r1["reference"], r2["reference"]}, "new reference unique")
st, e2 = call(S2, "GET", "/_test/export")
st2, _ = call(S2, "POST", "/_test/import", e2)
check("S2-042", st == 200 and st2 == 204, "stage-2 re-export/import of upgraded state")
print(f"SUMMARY pass={sum(RES)} fail={len(RES) - sum(RES)}")
sys.exit(0 if all(RES) else 1)
