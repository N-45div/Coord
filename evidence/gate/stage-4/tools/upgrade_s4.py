"""Gate: stage-1/2/3 exports -> stage-4 import (S4-030). Stdlib only.
Usage: py -3.12 upgrade_s4.py http://S1 http://S2 http://S3 http://S4_FRESH_A http://S4_FRESH_B http://S4_FRESH_C"""
import http.client
import json
import sys
from urllib.parse import urlparse

S1, S2, S3, D1, D2, D3 = (urlparse(u) for u in sys.argv[1:7])
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
    print("PASS" if cond else "FAIL", lid, "" if cond else str(detail)[:500], flush=True)


ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HOURS = [{"weekday": d, "opens": "17:00", "closes": "23:00"} for d in ALL]


def fixture(stage):
    rest = {"id": "r_u", "name": "Upgrade", "timezone": "Europe/Berlin", "slot_minutes": 30,
            "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120, "opening_hours": HOURS,
            "tables": [{"id": "u_1", "label": "U1", "capacity": 4}, {"id": "u_2", "label": "U2", "capacity": 4},
                       {"id": "u_3", "label": "U3", "capacity": 4}]}
    if stage >= 2:
        rest["combinable"] = [["u_1", "u_2"]]
    if stage >= 3:
        rest["manager_user_ids"] = ["u_mgr"]
    users = [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"},
             {"id": "u_mgr", "email": "mgr@example.com", "password": "manager pass", "display_name": "Mgr"}]
    return {"users": users, "restaurants": [rest], "reservations": []}


def login(b, e, p):
    st, j = call(b, "POST", "/auth/login", {"email": e, "password": p})
    return j["token"] if st == 200 else None


def scenario(src, dst, stage):
    tag = f"S4-030 stage-{stage}"
    call(src, "POST", "/_test/reset", fixture(stage))
    ada = login(src, "ada@example.com", "correct horse")
    B1 = {"restaurant_id": "r_u", "table_id": "u_1", "starts_at_local": "2026-11-12T19:00", "party_size": 2}
    st, r1 = call(src, "POST", "/reservations", B1, token=ada, key="K1")
    st, r2 = call(src, "POST", "/reservations", dict(B1, table_id="u_2", starts_at_local="2026-11-12T19:30"), token=ada, key="K2")
    S = None
    if stage == 3:
        st, S = call(src, "POST", "/series", {"anchor_reference": r1["reference"], "count": 3, "interval_weeks": 1},
                     token=ada, key="KS")
        occ = [o["reference"] for o in S["occurrences"]]
        call(src, "PATCH", f"/reservations/{occ[1]}", {"party_size": 3}, token=ada)        # exception
        call(src, "POST", f"/reservations/{occ[2]}/cancel", token=ada)                       # cancelled occurrence
        st, Sg = call(src, "GET", f"/series/{S['series_id']}", token=ada)
    st, e = call(src, "GET", "/_test/export")
    st, _ = call(dst, "POST", "/_test/import", e)
    check(tag, st == 204, f"import {st}")
    st, lst = call(dst, "GET", "/reservations", token=ada)
    check(tag, st == 200 and r1["reference"] in {x["reference"] for x in lst["reservations"]}, "token + bookings carried")
    st, rep = call(dst, "POST", "/reservations", B1, token=ada, key="K1")
    check(tag, st == 200 and rep == r1, "original booking receipt replays")
    mgr = login(dst, "mgr@example.com", "manager pass")
    if stage < 3:
        call(dst, "POST", "/_test/reset", fixture(3))      # manager_user_ids only exists from stage 3 on
        call(dst, "POST", "/_test/import", e)
        note = "stage<3 export has no managers: replans need a stage-3+ manager, so only data checks apply"
        print("NOTE", tag, note)
        st, g = call(dst, "GET", f"/reservations/{r1['reference']}", token=ada)
        check(tag, st == 200 and g.get("revision") == 1 and g.get("accepted_terms", {}).get("policy_version") == 0,
              f"imported booking at revision 1, policy 0: {g}")
        return
    st, Sd = call(dst, "GET", f"/series/{S['series_id']}", token=ada)
    check(tag, st == 200 and Sd == Sg, "imported series identical (exception + cancelled occurrence)")
    st, rep = call(dst, "POST", "/series", {"anchor_reference": r1["reference"], "count": 3, "interval_weeks": 1},
                   token=ada, key="KS")
    check(tag, st == 200 and rep == S, "series receipt replays original")
    st, am = call(dst, "POST", f"/series/{S['series_id']}/amend",
                  {"expected_revision": Sg["revision"], "from_index": 0, "local_time": "20:00"}, token=ada, key="KA")
    times = [o["reservation"]["starts_at_local"][11:] for o in am["occurrences"]] if st == 201 else None
    check(tag, st == 201 and times == ["20:00", "19:00", "19:00"] and am["revision"] == Sg["revision"] + 1,
          f"amend on imported series skips exception and cancelled: {st} {times}")
    st, pv = call(dst, "POST", "/restaurants/r_u/replans", {"table_id": "u_2", "from": "2026-11-12T18:00:00+01:00",
                                                            "to": "2026-11-12T23:00:00+01:00"}, token=mgr, key="KP")
    ok = st == 201 and any(a["reference"] == r2["reference"] and a["changed"] for a in pv["assignments"])
    check(tag, ok, f"replan on imported bookings: {st} {pv}")
    if ok:
        st, ap = call(dst, "POST", f"/restaurants/r_u/replans/{pv['plan_id']}/apply", {}, token=mgr, key="KAP")
        check(tag, st == 201, f"apply on imported state {st}")
        st, h = call(dst, "GET", f"/reservations/{r2['reference']}/history", token=ada)
        check(tag, st == 200 and h["entries"][-1]["event"] == "reassigned", "reassigned history on imported booking")


scenario(S1, D1, 1)
scenario(S2, D2, 2)
scenario(S3, D3, 3)
print(f"SUMMARY pass={sum(RES)} fail={len(RES) - sum(RES)}")
sys.exit(0 if all(RES) else 1)
