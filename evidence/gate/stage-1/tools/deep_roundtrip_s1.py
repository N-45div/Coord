"""Gate: deep-body idempotent writes survive export -> import into a fresh instance (Coordinator pointer on e48a498).
Usage: py -3.12 deep_roundtrip_s1.py http://SRC http://FRESH"""
import http.client
import json
import sys
from urllib.parse import urlparse

SRC, DST = urlparse(sys.argv[1]), urlparse(sys.argv[2])
OK = []


def call(b, method, path, raw=None, headers=None):
    c = http.client.HTTPConnection(b.hostname, b.port, timeout=30)
    c.request(method, path, body=raw, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        j = json.loads(data) if data else None
    except Exception:
        j = None
    return r.status, j, data


def check(name, cond, detail=""):
    OK.append(cond)
    print("PASS" if cond else "FAIL", name, "" if cond else detail[:300], flush=True)


FIX = {"users": [{"id": "u_a", "email": "a@example.com", "password": "correct horse", "display_name": "A"}],
       "restaurants": [{"id": "r", "name": "R", "timezone": "Europe/Berlin", "slot_minutes": 30,
                        "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
                        "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}],
                        "tables": [{"id": "t1", "label": "1", "capacity": 4}, {"id": "t2", "label": "2", "capacity": 4}]}],
       "reservations": []}
st, _, _ = call(SRC, "POST", "/_test/reset", json.dumps(FIX).encode(), {"Content-Type": "application/json"})
check("reset", st == 204)
st, j, _ = call(SRC, "POST", "/auth/login", json.dumps({"email": "a@example.com", "password": "correct horse"}).encode())
tok = j["token"]
H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
for depth in (1000, 1400, 1490):
    for kind in ("list", "object"):
        deep = ("[" * depth + "]" * depth) if kind == "list" else ('{"a":' * depth + "1" + "}" * depth)
        k1, k2 = f"c-{depth}-{kind}", f"m-{depth}-{kind}"
        day = "2027-06-17" if kind == "list" else "2027-06-24"
        hour = {1000: "18:00", 1400: "19:30", 1490: "21:00"}[depth]
        create_raw = ('{"restaurant_id":"r","table_id":"t1","starts_at_local":"%sT%s","party_size":2,"x":%s}'
                      % (day, hour, deep)).encode()
        st, created, _ = call(SRC, "POST", "/reservations", create_raw, dict(H, **{"Idempotency-Key": k1}))
        check(f"create depth={depth} {kind} -> 201", st == 201, f"{st} {created}")
        ref = created["reference"]
        move_raw = ('{"moves":[{"reference":"%s","table_id":"t2"}],"x":%s}' % (ref, deep)).encode()
        st, moved, _ = call(SRC, "POST", "/reservation-moves", move_raw, dict(H, **{"Idempotency-Key": k2}))
        check(f"moves depth={depth} {kind} -> 201", st == 201, f"{st} {moved}")
        st, rep, _ = call(SRC, "POST", "/reservations", create_raw, dict(H, **{"Idempotency-Key": k1}))
        check(f"replay create on source -> 200 original", st == 200 and rep == created, f"{st}")
        globals().setdefault("CASES", []).append((k1, create_raw, created, k2, move_raw, moved))
st, exp, raw = call(SRC, "GET", "/_test/export")
check("export 200", st == 200, str(st))
print(f"export bytes={len(raw)}")
st, _, body = call(DST, "POST", "/_test/import", raw, {"Content-Type": "application/json"})
check("import unchanged export into FRESH instance -> 204", st == 204, f"{st} {body[:200]!r}")
for k1, create_raw, created, k2, move_raw, moved in CASES:
    st, rep, _ = call(DST, "POST", "/reservations", create_raw, dict(H, **{"Idempotency-Key": k1}))
    check(f"fresh: replay {k1} -> 200 original", st == 200 and rep == created, f"{st} {rep}")
    st, rep, _ = call(DST, "POST", "/reservation-moves", move_raw, dict(H, **{"Idempotency-Key": k2}))
    check(f"fresh: replay {k2} -> 200 original", st == 200 and rep == moved, f"{st} {rep}")
    st, rep, _ = call(DST, "POST", "/reservations", create_raw.replace(b'"party_size":2', b'"party_size":3'),
                      dict(H, **{"Idempotency-Key": k1}))
    check(f"fresh: reuse {k1} with different body -> 409", st == 409 and rep["error"]["code"] == "idempotency_key_reuse",
          f"{st} {rep}")
st, lst, _ = call(DST, "GET", "/reservations", headers=H)
check("fresh: 6 bookings, none duplicated by replays", st == 200 and len(lst["reservations"]) == 6, f"{st} {lst}")
# deep ignored field on the import envelope itself, and an over-deep state
env = json.loads(raw)
env_raw = raw[:-1] + b',"zz":' + b"[" * 1400 + b"]" * 1400 + b"}"
st, _, body = call(DST, "POST", "/_test/import", env_raw, {"Content-Type": "application/json"})
check("import with deep ignored envelope field -> 204", st == 204, f"{st} {body[:200]!r}")
bad = dict(env)
bad["state"] = dict(env["state"], extra=json.loads("[" * 100 + "]" * 100))
st, j, _ = call(DST, "POST", "/_test/import", json.dumps(bad).encode(), {"Content-Type": "application/json"})
print(f"NOTE import of state with an extra 100-deep field -> {st} {j}")
st, lst2, _ = call(DST, "GET", "/reservations", headers=H)
check("state intact after that import attempt", st == 200 and len(lst2["reservations"]) == 6)
print(f"SUMMARY pass={sum(OK)} fail={len(OK) - sum(OK)}")
sys.exit(0 if all(OK) else 1)
