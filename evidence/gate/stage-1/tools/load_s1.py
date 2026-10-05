"""Gate load probe (S1-005): many bookings, then 50 concurrent mixed requests. Stdlib only.
Usage: py -3.12 load_s1.py http://127.0.0.1:PORT [n_bookings]"""
import http.client
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

B = urlparse(sys.argv[1])
N = int(sys.argv[2]) if len(sys.argv) > 2 else 1000


def call(method, path, body=None, headers=None):
    c = http.client.HTTPConnection(B.hostname, B.port, timeout=30)
    t0 = time.monotonic()
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data, time.monotonic() - t0


days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
fix = {"users": [{"id": f"u{i}", "email": f"u{i}@example.com", "password": "correct horse", "display_name": f"U{i}"}
                 for i in range(20)],
       "restaurants": [{"id": f"r{j}", "name": f"R{j}", "timezone": "Europe/Berlin", "slot_minutes": 15,
                        "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 60,
                        "opening_hours": [{"weekday": d, "opens": "08:00", "closes": "23:00"} for d in days],
                        "tables": [{"id": f"t{k}", "label": str(k), "capacity": 8} for k in range(20)]}
                       for j in range(3)],
       "reservations": []}
# seed N bookings on r0 across 2026-11-02 .. spread, plus some on the probed day
res = []
i = 0
day = 0
while len(res) < N:
    for k in range(20):
        for h in range(8, 22):
            if len(res) >= N:
                break
            res.append({"id": f"s{len(res)}", "reference": f"SEED{len(res):06d}", "user_id": f"u{len(res) % 20}",
                        "restaurant_id": "r0", "table_id": f"t{k}",
                        "starts_at_local": f"2026-11-{2 + day:02d}T{h:02d}:00", "party_size": 2})
    day += 1
fix["reservations"] = res
st, _, dt = call("POST", "/_test/reset", fix)
print(f"reset with {N} seeded bookings: {st} in {dt:.2f}s")
toks = []
for i in range(20):
    st, data, _ = call("POST", "/auth/login", {"email": f"u{i}@example.com", "password": "correct horse"})
    toks.append(json.loads(data)["token"])


def mixed(i):
    kind = i % 5
    if kind == 0:
        return call("GET", "/availability?restaurant_id=r0&date=2026-11-02&party_size=2")
    if kind == 1:
        return call("GET", "/reservations", headers={"Authorization": f"Bearer {toks[i % 20]}"})
    if kind == 2:
        return call("POST", "/reservations", {"restaurant_id": "r1", "table_id": f"t{i % 20}",
                                              "starts_at_local": "2026-12-01T12:00", "party_size": 2},
                    headers={"Authorization": f"Bearer {toks[i % 20]}", "Idempotency-Key": f"L{i}-{time.time_ns()}"})
    if kind == 3:
        return call("POST", "/auth/login", {"email": f"u{i % 20}@example.com", "password": "correct horse"})
    return call("GET", "/restaurants/r0")


for rnd in range(3):
    bar = threading.Barrier(50)

    def w(i):
        bar.wait()
        return mixed(i)
    t0 = time.monotonic()
    with ThreadPoolExecutor(50) as ex:
        out = list(ex.map(w, range(50)))
    wall = time.monotonic() - t0
    sts = {}
    for s, _, _ in out:
        sts[s] = sts.get(s, 0) + 1
    print(f"round {rnd}: statuses {sts} max {max(d for _, _, d in out):.2f}s wall {wall:.2f}s "
          f"5xx={sum(1 for s, _, _ in out if s >= 500)}")
st, data, dt = call("GET", "/_test/export")
print(f"export {st} {len(data)} bytes in {dt:.2f}s")
st, _, dt = call("POST", "/_test/import", json.loads(data))
print(f"import {st} in {dt:.2f}s")
