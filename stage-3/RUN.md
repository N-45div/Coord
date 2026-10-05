# Tablekeeper — stage 3: booking policies, history and recurring reservations

A restaurant reservation service: the HTTP API from stages 1-2 (reservations, combinable
table pairs, the browser product), plus dated booking policies, availability explanations,
reservation revisions and history, and recurring series. Python 3.12 standard library plus the
pinned IANA tz database (`tzdata`), installed at image build time; the page loads only its
own script, stylesheet and icon, so nothing is fetched at run time. State is held in memory
and starts empty; load it with `POST /_test/reset`.

## Build and start

From this folder:

```sh
docker build -t tablekeeper-stage-3 . && docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-3
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
| `tablekeeper/booking.py` | Availability (+ explanations), table-set rules, occupancy, create/amend/cancel, moves, history/decision reads |
| `tablekeeper/policies.py` | Policy 0 and published policies: validation, selection by local date, accepted terms |
| `tablekeeper/series.py` | Recurring series: adoption and reads |
| `tablekeeper/model.py` | State data, fixture loading, export/import (de)serialisation, upgrade of stage 1-2 state |
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
- **Policies and terms.** `State.policy_for` is the only policy selection (greatest
  `effective_from` not after the local date, then greatest version; policy 0 otherwise);
  `booking.place` validates against it and every placement carries the policy whose terms
  the booking accepts.
- **Revisions and history.** `booking.apply_change` (real amendments and moves) and
  `booking.cancel` are the only places a booking's terms, revision and history change; each
  appends exactly one entry. No-ops return before them. Restaurant and series revisions are
  bumped once per operation by the operation itself.
- **All-or-nothing writes.** Writes validate everything first and mutate only after every
  check passed; a batch of moves or a series adoption is planned in full, checked once, then applied.
- **Retries.** `Api._idempotent` looks up the `(user, method, path, Idempotency-Key)`
  receipt and stores the response in the same locked step as the write. Only successes are
  stored, so a key whose first use failed stays usable.
- **Export/import.** Export serialises the whole state under the lock. Import builds and
  validates a complete new state before swapping it in. Exports of the stage-1 and stage-2
  services load too: their bookings get revision 1 under policy 0 with a synthesised
  `created` entry (and a `cancelled` entry at revision 2 when cancelled), decision A-31.

## Browser behaviour

- One page shell is served for every screen route; `app.js` renders the screen for the path
  and navigates in-page, so the booking form, its pending retry key and the session survive
  anything that happens on the server between requests (including an export/import).
- The page shell embeds the current restaurant list as a JSON data block, so the search
  form is complete when the page loads; the client refreshes the list on every visit.
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
  fixture value when given, otherwise the reset time. Like imported pre-stage-3 bookings
  they start at revision 1 under policy 0; a seeded cancelled one also has its `cancelled`
  entry, still at revision 1 (decision A-43).
- History `at` timestamps are rendered in the restaurant's time zone.
- Signed out, choosing a table shows a sign-in prompt (`auth-error`) and keeps the search.
  Looking up a booking needs a sign-in, because reservations are owner-only.
