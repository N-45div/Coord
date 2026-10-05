# Tablekeeper — stage 1: reservations

A restaurant reservation HTTP API. Python 3.12 standard library plus the pinned IANA tz
database (`tzdata`), installed at image build time; nothing is fetched at run time. State
is held in memory and starts empty; load it with `POST /_test/reset`.

## Build and start

From this folder:

```sh
docker build -t tablekeeper-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-1
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and answers `GET /health` with
`200 {"status":"ok"}` as soon as it is up (well under a second).

Without Docker: `PORT=8080 python3.12 -m tablekeeper` from this folder, with `tzdata`
installed (`pip install tzdata==2025.3`) on hosts that have no system zoneinfo.

## Layout

| Module | Concern |
|---|---|
| `tablekeeper/__main__.py` | Entry point: threaded HTTP server on `$PORT` |
| `tablekeeper/server.py` | Routing table, request framing, JSON responses, error bodies |
| `tablekeeper/api.py` | Endpoint handlers, authentication, idempotency (§6, §7), reset/export/import |
| `tablekeeper/booking.py` | Availability, booking rules, occupancy, create/amend/cancel, moves (§8, §11) |
| `tablekeeper/model.py` | State data, fixture loading, export/import (de)serialisation (§4, §10) |
| `tablekeeper/store.py` | The live state and the single lock around it |
| `tablekeeper/timeutil.py` | Local times, IANA zones, DST gap/overlap resolution (§9) |
| `tablekeeper/validate.py`, `jsonio.py`, `errors.py`, `passwords.py` | Field checks, strict JSON, §5 errors, scrypt |

## Where the invariants live

- **Serial equivalence.** Every request that reads or writes state holds `Store.lock`
  (`store.py`) for its whole read-validate-write, so concurrent requests behave as some
  serial order. Only password hashing runs outside it.
- **No overlapping bookings.** `booking.ensure_free` is the only occupancy check; create,
  PATCH and moves all call it on the complete resulting set of bookings before mutating.
- **All-or-nothing writes.** Writes validate everything first (`booking.place`,
  `booking.plan_amendment`) and mutate only after every check passed; a batch of moves is
  planned in full, checked once, then applied.
- **Retries.** `Api._idempotent` looks up the `(user, method, path, Idempotency-Key)`
  receipt and stores the response in the same locked step as the write. Only successes are
  stored, so a key whose first use failed stays usable.
- **Export/import.** Export serialises the whole state under the lock. Import builds and
  validates a complete new state before swapping it in, so a rejected import changes nothing.

## Decisions on unstated points

- A wrong HTTP method on a known path, like an unknown path, is `404 not_found`.
- Email uniqueness and login are case-insensitive. Passwords are hashed with scrypt, and
  only the hash is stored or exported. Bearer tokens are stored as SHA-256 digests.
- `GET /reservations` orders by `starts_at` descending, then the most recently created first.
- Seeded reservations keep their fixture `id` and `reference`. Their `created_at` is the
  fixture value when given, otherwise the reset time.
