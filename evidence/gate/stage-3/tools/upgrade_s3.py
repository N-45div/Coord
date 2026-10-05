"""Gate: stage-1 and stage-2 exports -> stage-3 import (S3-046, A-31). Stdlib only.
Usage: py -3.12 upgrade_s3.py http://STAGE1 http://STAGE2 http://STAGE3_FRESH_A http://STAGE3_FRESH_B"""
import http.client
import json
import sys
from urllib.parse import urlparse

S1, S2, D1, D2 = (urlparse(u) for u in sys.argv[1:5])
RES = []


def call(b, method, path, body=None, token=None, key=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    c = http.client.HTTPConnection(b.hostname, b.port, timeout=20)
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
    print("PASS" if cond else "FAIL", lid, "" if cond else str(detail)[:420], flush=True)


HOURS = [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}]
REST = {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30,
        "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120, "opening_hours": HOURS,
        "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4},
                   {"id": "t_3", "label": "3", "capacity": 4}]}
T0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
      "opening_hours": HOURS, "capacities": {"t_1": 2, "t_2": 4, "t_3": 4}}
USERS = [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"}]


def scenario(src, dst, stage):
    rest = dict(REST, combinable=[["t_1", "t_2"]]) if stage == 2 else REST
    st, _ = call(src, "POST", "/_test/reset", {"users": USERS, "restaurants": [rest], "reservations": []})
    st, a = call(src, "POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
    ada = a["token"]
    B1 = {"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": "2026-11-12T19:00", "party_size": 3}
    st, r1 = call(src, "POST", "/reservations", B1, token=ada, key="K1")
    B2 = {"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": "2026-11-12T18:00", "party_size": 2}
    st, r2 = call(src, "POST", "/reservations", B2, token=ada, key="K2")
    call(src, "POST", f"/reservations/{r2['reference']}/cancel", token=ada)
    st, rp = call(src, "PATCH", f"/reservations/{r1['reference']}", {"party_size": 4}, token=ada)
    BP = None
    if stage == 2:
        BP = {"restaurant_id": "r_anker", "table_ids": ["t_2", "t_1"], "starts_at_local": "2026-11-12T21:00", "party_size": 5}
        st, rpair = call(src, "POST", "/reservations", BP, token=ada, key="KP")
    st, e = call(src, "GET", "/_test/export")
    st, _ = call(dst, "POST", "/_test/import", e)
    tag = f"S3-046 stage-{stage}"
    check(tag, st == 204, f"import stage-{stage} export: {st}")
    st, lst = call(dst, "GET", "/reservations", token=ada)
    check(tag, st == 200, f"stage-{stage} token works: {st}")
    st, _ = call(dst, "POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
    check(tag, st == 200, "login after import")
    st, g1 = call(dst, "GET", f"/reservations/{r1['reference']}", token=ada)
    check(f"A-31 stage-{stage}", st == 200 and g1.get("revision") == 1 and g1.get("accepted_terms") == T0 and
          g1.get("party_size") == 4 and g1.get("table_ids") == ["t_2"], f"imported booking revision 1 + policy-0 terms: {g1}")
    st, h1 = call(dst, "GET", f"/reservations/{r1['reference']}/history", token=ada)
    ent = (h1 or {}).get("entries", [])
    check(f"A-31 stage-{stage}", st == 200 and [x["event"] for x in ent] == ["created"] and ent[0]["seq"] == 1 and
          ent[0]["changes"] == [{"field": "table_id", "from": None, "to": "t_2"},
                                {"field": "starts_at_local", "from": None, "to": "2026-11-12T19:00"},
                                {"field": "party_size", "from": None, "to": 4}] and ent[0].get("revision") == 1,
          f"synthesised created entry with current fields: {ent}")
    st, h2 = call(dst, "GET", f"/reservations/{r2['reference']}/history", token=ada)
    ent2 = (h2 or {}).get("entries", [])
    st2, g2 = call(dst, "GET", f"/reservations/{r2['reference']}", token=ada)
    check(f"A-31 stage-{stage}", [x["event"] for x in ent2] == ["created", "cancelled"] and ent2[1].get("revision") == 2 and
          ent2[1]["changes"] == [] and g2.get("revision") == 2 and g2.get("status") == "cancelled",
          f"cancelled import: created + cancelled(rev 2): {ent2} / {g2}")
    st, d1 = call(dst, "GET", f"/reservations/{r1['reference']}/decision", token=ada)
    check(tag, st == 200 and d1 == {"reference": r1["reference"], "revision": 1, "accepted_terms": T0}, f"decision {d1}")
    st, rep = call(dst, "POST", "/reservations", B1, token=ada, key="K1")
    check(tag, st == 200 and rep == r1, f"original stage-{stage} receipt replays its original body: {rep}")
    st, rep = call(dst, "POST", "/reservations", dict(B1, party_size=2), token=ada, key="K1")
    check(tag, st == 409, f"reuse 409: {st}")
    st, s = call(dst, "POST", "/series", {"anchor_reference": r1["reference"], "count": 3, "interval_weeks": 1}, token=ada,
                 key="KS")
    ok = st == 201 and [o["reservation"]["starts_at_local"] for o in s["occurrences"]] == \
        ["2026-11-12T19:00", "2026-11-19T19:00", "2026-11-26T19:00"] and s["occurrences"][0]["reference"] == r1["reference"]
    check(tag, ok, f"adoption on an imported reservation: {st} {s}")
    st, h1b = call(dst, "GET", f"/reservations/{r1['reference']}/history", token=ada)
    check(tag, h1b == h1, "adoption leaves the imported anchor's history unchanged")
    if stage == 2:
        st, rep = call(dst, "POST", "/reservations", BP, token=ada, key="KP")
        check(tag, st == 200 and rep == rpair, "stage-2 pair receipt replays")
        st, hp = call(dst, "GET", f"/reservations/{rpair['reference']}/history", token=ada)
        ch0 = (hp or {}).get("entries", [{}])[0].get("changes")
        check(f"A-31 stage-2", ch0 and ch0[0] == {"field": "table_ids", "from": None, "to": ["t_1", "t_2"]},
              f"imported pair history uses table_ids: {ch0}")
    st, av = call(dst, "GET", "/availability?restaurant_id=r_anker&date=2026-11-12&party_size=2&explain=true")
    s19 = [x for x in av["slots"] if x["starts_at_local"].endswith("19:00")][0] if st == 200 else {}
    check(tag, st == 200 and "t_2" not in s19.get("available_table_ids", ["t_2"]) and
          all(x["policy_version"] == 0 for x in s19.get("explain", [])), "imported occupancy + explain policy 0")


scenario(S1, D1, 1)
scenario(S2, D2, 2)
print(f"SUMMARY pass={sum(RES)} fail={len(RES) - sum(RES)}")
sys.exit(0 if all(RES) else 1)
