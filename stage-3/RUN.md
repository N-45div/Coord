# Tablekeeper — stage 2: online booking and combined tables

A restaurant reservation service: the HTTP API from stage 1, combinable table pairs, and a
browser product served from the same container. Python 3.12 standard library plus the
pinned IANA tz database (`tzdata`), installed at image build time; the page loads only its
own script, stylesheet and icon, so nothing is fetched at run time. State is held in memory
and starts empty; load it with `POST /_test/reset`.

## Build and start

From this folder:

```sh
docker build -t tablekeeper-stage-2 . && docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-2
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and answers `GET /health` with
`200 {"status":"ok"}` as soon as it is up. Open `http://localhost:8080/` for the browser
product (`/`, `/signup`, `/login`, `/lookup`).

Without Docker: `PORT=8080 python3.12 -m tablekeeper` from this folder, with `tzdata`
installed (`pip install tzdata==2025.3`) on hosts that have no system zoneinfo.

## Layout

| Module | Concern |
|---|---|
| `tablekeeper/__main__.py` | Entry point: threaded HTTP server on `$PORT` |
| `tablekeeper/server.py` | Routing table, request framing, JSON responses, error bodies, page/asset serving |
| `tablekeeper/ui.py` | The page shell and static assets, loaded from `static/` into memory at start |
| `tablekeeper/static/` | `index.html`, `app.css`, `app.js` (no build step, no dependencies), `favicon.svg` |
| `tablekeeper/api.py` | Endpoint handlers, authentication, idempotency (§6, §7), reset/export/import |
| `tablekeeper/booking.py` | Availability and options, table-set rules, occupancy, create/amend/cancel, moves |
| `tablekeeper/model.py` | State data, fixture loading, export/import (de)serialisation, stage-1 state upgrade |
| `tablekeeper/store.py` | The live state and the single lock around it |
| `tablekeeper/timeutil.py` | Local times, IANA zones, DST gap/overlap resolution (§9) |
| `tablekeeper/validate.py`, `jsonio.py`, `errors.py`, `passwords.py` | Field checks, strict JSON, §5 errors, scrypt |

## Where the invariants live

- **Serial equivalence.** Every request that reads or writes state holds `Store.lock`
  (`store.py`) for its whole read-validate-write, so concurrent requests behave as some
  serial order. Only password hashing runs outside it.
- **No overlapping bookings.** `booking.ensure_free` is the only occupancy check; it compares
  table *sets*, so a pair occupies both members. Create, PATCH and moves all call it on the
  complete resulting set of bookings before mutating.
- **Table sets.** `booking.requested_tables` (shape) and `booking.select_tables` (existence,
  declared pairs) are the one path every write takes; a pair is always stored and returned
  in its declared `combinable` order, so a reversed pair is the same set.
- **All-or-nothing writes.** Writes validate everything first and mutate only after every
  check passed; a batch of moves is planned in full, checked once, then applied.
- **Retries.** `Api._idempotent` looks up the `(user, method, path, Idempotency-Key)`
  receipt and stores the response in the same locked step as the write. Only successes are
  stored, so a key whose first use failed stays usable.
- **Export/import.** Export serialises the whole state under the lock. Import builds and
  validates a complete new state before swapping it in. A stage-1 export (state `stage: 1`)
  loads as is: its restaurants simply have no combinable pairs.

## Browser behaviour

- One page shell is served for every screen route; `app.js` renders the screen for the path
  and navigates in-page, so the booking form, its pending retry key and the session survive
  anything that happens on the server between requests (including an export/import).
- The session token is kept in `localStorage`; tokens survive import, so a signed-in browser
  stays signed in after an upgrade.
- Searches are numbered; a response for anything but the newest search is dropped, so a late
  response never replaces newer results or the booking form built from them.
- The booking form keeps one Idempotency-Key per request body. Resubmitting unchanged
  reuses it (the server replays the original confirmation); changing any field starts a new
  request. A network failure, timeout or 5xx shows `booking-uncertain` and keeps the key, so
  "Try again" recovers the original outcome; `409 table_unavailable` shows `booking-error`
  and refreshes availability while keeping the form.
- Confirmations are only ever built from a server response.

## Decisions on unstated points

- A wrong HTTP method on a known path, like an unknown path, is `404 not_found`.
- Email uniqueness and login are case-insensitive. Passwords are hashed with scrypt, and
  only the hash is stored or exported. Bearer tokens are stored as SHA-256 digests.
- `GET /reservations` orders by `starts_at` descending, then the most recently created first.
- Seeded reservations keep their fixture `id` and `reference`. Their `created_at` is the
  fixture value when given, otherwise the reset time.
- Signed out, choosing a table shows a sign-in prompt (`auth-error`) and keeps the search.
  Looking up a booking needs a sign-in, because reservations are owner-only.
