"""Gate edge probes for stage 1 found during code audit (5xx hunting, odd inputs). Stdlib only.
Usage: py -3.12 edge_s1.py http://127.0.0.1:PORT"""
import http.client
import json
import sys
from urllib.parse import urlparse

B = urlparse(sys.argv[1])


def call(method, path, raw=None, headers=None):
    c = http.client.HTTPConnection(B.hostname, B.port, timeout=30)
    c.request(method, path, body=raw, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data[:160]


FIX = {"users": [{"id": "u_a", "email": "a@example.com", "password": "correct horse", "display_name": "A"}],
       "restaurants": [{"id": "r", "name": "R", "timezone": "Europe/Berlin", "slot_minutes": 30,
                        "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
                        "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}],
                        "tables": [{"id": "t", "label": "1", "capacity": 4}]}],
       "reservations": [{"id": "res_old", "reference": "OLDREF1", "user_id": "u_a", "restaurant_id": "r",
                         "table_id": "t", "starts_at_local": "1890-01-02T18:00", "party_size": 2}]}
print("reset", call("POST", "/_test/reset", json.dumps(FIX).encode(), {"Content-Type": "application/json"}))
st, body = call("POST", "/auth/login", json.dumps({"email": "a@example.com", "password": "correct horse"}).encode())
tok = json.loads(body)["token"] if st == 200 else None
H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
for depth in (500, 900, 980, 1000, 1100, 1300, 1600, 3000, 100000):
    nested = "[" * depth + "]" * depth
    raw = ('{"restaurant_id":"r","table_id":"t","starts_at_local":"2026-10-15T18:00","party_size":2,"x":' + nested + "}").encode()
    for path, method, extra in (("/reservations", "POST", {"Idempotency-Key": f"d{depth}"}),
                                ("/reservation-moves", "POST", {"Idempotency-Key": f"m{depth}"}),
                                ("/reservations/OLDREF1", "PATCH", {}),
                                ("/auth/signup", "POST", {}), ("/_test/import", "POST", {})):
        print(f"depth={depth} {method} {path}", call(method, path, raw, dict(H, **extra)))
# a seeded booking in 1890 Berlin: offset rendering (LMT has seconds)
print("GET old", call("GET", "/reservations/OLDREF1", headers=H))
print("avail 1890", call("GET", "/availability?restaurant_id=r&date=1890-01-02&party_size=2")[0])
print("export", call("GET", "/_test/export")[0])
