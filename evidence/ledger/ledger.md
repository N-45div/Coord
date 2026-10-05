# Tablekeeper requirements ledger

Owner: Coordinator. Source of truth: the human task message (dispatched Mon 5 Oct 2026 21:25 IST)
and the four specifications at `C:/Users/DivijN/dark-factory/kickoff/tablekeeper/spec/stage-N.md`.
The specification always wins over this ledger; if a line here contradicts the spec, report it to
Coordinator and follow the spec.

Observation codes: **R** = HTTP response (status/code/body), **P** = persisted state seen by a later
read, **C** = concurrency (parallel requests), **T** = time/DST arithmetic, **U** = upgrade
(export/import), **B** = browser, **D** = delivery/container.

Every requirement of an earlier stage stays in force in every later stage folder.

---

## Stage 1 — reservations (spec: `stage-1.md`)

### 1.A Delivery and runtime (§2, §3)

- S1-001 [D] `stage-1/` contains a `Dockerfile` and a `RUN.md` whose command builds and starts the service with no manual setup. §2
- S1-002 [D] The image runs on its own with `-e PORT=<port>` and a port mapping; no compose, no second container, no outbound network at run time; all deps/seed/init inside the image. §2
- S1-003 [D] Listens on `0.0.0.0:$PORT`, default 8080 when PORT is unset. §3.1
- S1-004 [R,D] `GET /health` → 200 `{"status":"ok"}` within 60 s of container start (non-200 allowed before ready). §3.2
- S1-005 [D,C] Operates in 2 vCPU / 2 GiB, serves up to 50 in-flight requests, each answered within 5 s (reset/import/export within 10 s). §2
- S1-006 [R,C] No request ever produces a 5xx, including under 50-way concurrent load and malformed input. §5
- S1-007 [R] `POST /_test/reset` with a fixture body → 204, no body; afterwards every read sees only that fixture (users, restaurants, tables, reservations); repeated resets work; no auth required; enabled in the delivered image. §3.3
- S1-008 [R] Reset clears everything: accounts created by signup, tokens, reservations, idempotency records, imported state. §3.3, §10
- S1-009 [R] JSON responses use `Content-Type: application/json; charset=utf-8`. §3.4
- S1-010 [R] Response timestamps are RFC 3339 with an explicit numeric offset (`+02:00`, `+00:00`), seconds precision. §3.4
- S1-011 [R] Unknown body fields and unknown query parameters are ignored, never an error, on every endpoint. §3.4
- S1-012 [R] IDs are opaque strings of at most 64 characters, including IDs the service generates (reservation_id, user_id, later series/plan ids); fixture IDs of any characters up to 64 long work everywhere (paths, bodies, query strings). (A-19.) §3.4

### 1.B Model and fixture (§4)

- S1-013 [R] Fixture shape: `users[]` (id, email, password, display_name), `restaurants[]` (id, name, timezone, slot_minutes, reservation_duration_minutes, cancellation_cutoff_minutes, opening_hours[], tables[]), `reservations[]`. §4
- S1-014 [R] Seeded users can log in immediately with the fixture password; their `user_id` is the fixture `id`. §4
- S1-015 [R,P] Seeded `reservations` carry the POST body fields plus `id`, `reference`, `user_id`; they are confirmed, occupy their table, appear in that user's `GET /reservations`, and `reservation_id` equals the fixture `id`, `reference` equals the fixture `reference`. §4
- S1-016 [R] `weekday` ∈ `mon tue wed thu fri sat sun`; a weekday with no entry is closed; `opens`/`closes` are local HH:MM, closes later than opens, never across midnight. §4
- S1-017 [R,T] All of a restaurant's times are local to its IANA `timezone`; offsets follow IANA rules for that zone and date. §4, §9
- S1-018 [R] A booking is never rejected solely because its start is in the past (fixtures may use any date); cutoff rules still apply. §4

### 1.C Errors (§5)

- S1-019 [R] Every 4xx/5xx carries `{"error":{"code":..., "message":...}}` with the specified status and code. §5
- S1-020 [R] 400 `malformed_request`: body is not parseable JSON, the body is not a JSON object where one is required, or a field has the wrong JSON type (except where an endpoint says otherwise). §5
- S1-021 [R] 422 `validation_failed`: missing required field or query parameter; correct JSON type but invalid format or out-of-range value (invalid dates, negative counts, values above a stated max or length). §5
- S1-022 [R] `party_size` invalid in any way (0, negative, non-integer, string, boolean, null) → 422 `validation_failed`, not 400. §5, §8
- S1-023 [R] `starts_at_local` string not exactly a bare local `YYYY-MM-DDTHH:MM` (seconds, offset, `Z`, wrong pattern, impossible date like 2026-02-30 or 25:00) → 422 `validation_failed`; a non-string `starts_at_local` → 400 `malformed_request`. §5
- S1-024 [R] Integer query parameters must be plain decimal digits: `1e9`, `4.0`, `+4`, `-1`, `abc`, empty → 422 `validation_failed`. §5
- S1-025 [R] `Idempotency-Key` longer than 255 characters → 422 `validation_failed`; absent or empty → 400 `missing_idempotency_key`. §5, §7
- S1-026 [R] Unknown route → 404 `not_found` with the error body. (Ambiguity A-14.)

### 1.D Authentication (§6)

- S1-027 [R] `POST /auth/signup {email,password,display_name}` → 201 `{user_id, display_name, token}`; the token works immediately. §6
- S1-028 [R] `POST /auth/login {email,password}` → 200 `{user_id, display_name, token}`. §6
- S1-029 [R] Signup with an already registered email (including a seeded user's) → 409 `email_taken`. §6
- S1-030 [R] Signup password shorter than 8 characters → 422 `validation_failed`; exactly 8 is accepted. §6
- S1-031 [R] Signup email not `local@domain` (no `@`, empty local or domain part, more than one `@`, whitespace) → 422 `validation_failed`. §6
- S1-032 [R] Login with wrong password or unknown email → 401 `unauthenticated`. §6
- S1-033 [R] Missing/wrong-type signup/login fields → 422 / 400 per §5 (missing → 422, wrong JSON type → 400). §5, §6
- S1-034 [R] Every endpoint except `/health`, `/_test/*`, `/auth/signup`, `/auth/login`, `GET /restaurants`, `GET /restaurants/{id}`, `GET /availability` requires `Authorization: Bearer <token>`; missing, malformed or unknown token → 401 `unauthenticated`. §6
- S1-035 [R] Tokens never expire; one account may hold several valid tokens at once (login twice → both work). §6
- S1-036 [P] Passwords are stored with bcrypt/scrypt/Argon2/PBKDF2 or equivalent; never plaintext (also not in exports). §6 (audited in code and in the export body)

### 1.E Idempotency (§7) — applies to `POST /reservations` and `POST /reservation-moves`

- S1-037 [R] Header absent or empty → 400 `missing_idempotency_key`. §7
- S1-038 [R] First use → normal response, 201. §7
- S1-039 [R,P] Replay (same user, same method, same path, same JSON body value — key order/whitespace irrelevant) → 200 with a body equal (as a JSON value) to the original 201 body, and no further state change. §7
- S1-040 [R] Same key + different body, same user, same path → 409 `idempotency_key_reuse`, even when the new body would be invalid (idempotency resolved after JSON-object parse and auth, before field validation and resource checks). §7
- S1-041 [R] Keys are scoped per authenticated user: another user may use the same key string independently (gets their own 201). §7
- S1-042 [R] Same key + same body on a different path is a new request, not a replay, and succeeds normally (keys are namespaced by method+path). §7
- S1-043 [R,P] A key whose first use failed with a 4xx is treated as unused: the next request with it is a first use. §7
- S1-044 [R,P] Replay returns the original response even after the reservation was later amended or cancelled; it changes nothing. §7
- S1-045 [C,P] N concurrent identical requests with an unused key → exactly one 201, the rest 200 with the same body; exactly one reservation exists. §7
- S1-046 [R] The same user's replay is recognised whichever of that user's tokens is used (scope is the user, not the token). §7

### 1.F Restaurants and availability (§8)

- S1-047 [R] `GET /restaurants` (public) → 200 `{"restaurants":[{id,name,timezone}, ...]}` in fixture order. §8
- S1-048 [R] `GET /restaurants/{id}` (public) → 200 with id, name, timezone, slot_minutes, reservation_duration_minutes, cancellation_cutoff_minutes, opening_hours, tables (id,label,capacity) in fixture shape and order; unknown → 404 `not_found`. §8
- S1-049 [R] `GET /availability?restaurant_id&date&party_size` is public; each of the three parameters is required (missing → 422); unknown restaurant → 404 `not_found`; `date` must be a real `YYYY-MM-DD` date (else 422); `party_size` plain digits ≥ 1 (else 422). §8, §5
- S1-050 [R] Response `{restaurant_id, date, timezone, slots:[{starts_at_local, starts_at, available_table_ids}]}`; `starts_at_local` is full `YYYY-MM-DDTHH:MM`, `starts_at` RFC 3339 with the correct offset. §8
- S1-051 [R,T] A slot exists for every `slot_minutes` step from `opens` (wall-clock grid on that local date) such that start + duration ≤ closes; slots in ascending order. §8
- S1-052 [R] `available_table_ids` = tables of that restaurant with capacity ≥ party_size and no overlapping confirmed reservation, in fixture order; slots with no available table still appear with `[]`. §8
- S1-053 [R] A closed weekday → `"slots": []` (200). §8
- S1-054 [R,P] Cancelled reservations do not block availability; a cancel frees the slot for the very next availability read. §8

### 1.G Create reservation (§8)

- S1-055 [R] `POST /reservations` (auth + Idempotency-Key) body `{restaurant_id, table_id, starts_at_local, party_size}` → 201 with `reservation_id, reference, restaurant_id, table_id, party_size, status:"confirmed", starts_at_local, starts_at, ends_at, created_at`. §8
- S1-056 [R,T] `starts_at_local` is resolved in the restaurant's timezone; `starts_at` carries that instant's offset; `ends_at` = starts_at + duration in absolute time, rendered with the offset in force at the end instant. §8, §9
- S1-057 [R,P] `reference` is 6–12 characters of `A-Z0-9`, unique across all reservations (including seeded and imported ones), never changes. §8
- S1-058 [R,P] Overlapping confirmed booking on the table (half-open `[start, start+duration)`) → 409 `table_unavailable`; back-to-back bookings (end == next start) are allowed. §1, §8
- S1-059 [R] Start not on the slot grid (minutes from `opens` not a multiple of `slot_minutes`) → 422 `not_on_slot_grid`. §8
- S1-060 [R] Start before opens, on a closed day, or end after closes → 422 `outside_opening_hours`. §8
- S1-061 [R] party_size > table capacity → 422 `party_exceeds_capacity`; party_size == capacity is accepted. §8
- S1-062 [R] party_size < 1 or not an integer → 422 `validation_failed`. §8
- S1-063 [R,T] `starts_at_local` in a spring-forward gap → 422 `invalid_local_time`. §8, §9
- S1-064 [R] Unknown restaurant, unknown table, or table of another restaurant → 404 `not_found`. §8
- S1-065 [R] Missing required body field → 422 `validation_failed`; wrong JSON type for restaurant_id/table_id → 400. §5
- S1-066 [P] A rejected create leaves no reservation, no occupancy, no consumed reference and no idempotency record. §1, §7
- S1-067 [C,P] Concurrent creates for the same table and overlapping times (different users/keys) → exactly one 201, the rest 409 `table_unavailable`; never two confirmed overlapping bookings on a table. §1

### 1.H Read, cancel, amend (§8)

- S1-068 [R] `GET /reservations` → 200 `{"reservations":[...]}` with only the caller's bookings, confirmed and cancelled, ordered by `starts_at` descending, each in the create-response shape; none → `{"reservations":[]}`. §8
- S1-069 [R] `GET /reservations/{reference}` → 200 the reservation for its owner; another user's or unknown reference → 404 `not_found` (identical to unknown). §8
- S1-070 [R,P] `POST /reservations/{reference}/cancel` → 200 full reservation with `status:"cancelled"`; the table is free immediately. §8
- S1-071 [R] Cancelling an already cancelled reservation → 200 with the current state (no error, even past the cutoff). §8
- S1-072 [R,T] Cancel when now ≥ starts_at − cancellation_cutoff_minutes → 409 `cutoff_passed`, state unchanged. §8
- S1-073 [R] Cancel of another user's or unknown reference → 404 `not_found`. §8
- S1-074 [R,P] `PATCH /reservations/{reference}` with any subset of `table_id, starts_at_local, party_size` (no idempotency key) → 200 with the updated reservation; `reference` and `reservation_id` unchanged; omitted fields keep their values. §8
- S1-075 [R] PATCH validation identical to create: same codes and conditions as S1-058..S1-065 applied to the resulting booking. §8
- S1-076 [R,T] PATCH within the cutoff of the **current** start → 409 `cutoff_passed`. §8
- S1-077 [R] PATCH on a cancelled reservation → 409 `reservation_cancelled`. §8
- S1-078 [R] PATCH of another user's or unknown reference → 404 `not_found`. §8
- S1-079 [P,C] A successful PATCH releases the old interval and reserves the new one atomically (moving a booking to an interval overlapping its own old interval on the same table succeeds); a failed PATCH leaves the booking and its occupancy unchanged. §8
- S1-080 [C] Concurrent PATCHes/creates/moves competing for the same table interval never yield two overlapping confirmed bookings. §1

### 1.I Time and DST (§9)

- S1-081 [R,T] Spring forward: local times in the skipped hour never appear in availability and booking one → 422 `invalid_local_time` (Europe/Berlin 2026-03-29 02:00–02:59; America/New_York 2026-03-08 02:00–02:59). §9
- S1-082 [R,T] Fall back: a repeated local time appears once in availability and resolves to the first occurrence (pre-transition offset, e.g. Berlin 2026-10-25 02:30 → `+02:00`, New York 2026-11-01 01:30 → `-04:00`); the second occurrence is not bookable. §9
- S1-083 [R,T] Duration is absolute: Berlin 2026-10-25 01:30 + 90 min → `ends_at` `2026-10-25T02:00:00+01:00`; overlap checks use absolute instants. §9
- S1-084 [R,T] All offsets follow IANA rules for the zone and date (e.g. Berlin summer `+02:00`, winter `+01:00`; New York `-04:00`/`-05:00`); the tz database ships in the image. §9

### 1.J Export and import (§10)

- S1-085 [R] `GET /_test/export` (no auth) → 200 `{"track":"tablekeeper","format_version":1,"state":{...}}`. §10
- S1-086 [R,U] `POST /_test/import` with an unchanged export → 204 and atomically replaces all state (replacement, not merge; importing twice gives no duplicates). §10
- S1-087 [R,U] Import of invalid JSON → 400 `malformed_request`; missing fields, wrong `track`, wrong `format_version`, or an invalid `state` → 422 `validation_failed` with the destination state unchanged. §10
- S1-088 [U] After import, everything is preserved: accounts and hashed-password login, existing bearer tokens, fixture configuration, reservations with their ids/references/statuses/timestamps, all completed idempotency records with their original responses (replays still return 200 + original body; reused keys with different body still 409), successful move receipts. Failed-request keys remain reusable. §10
- S1-089 [U] Import removes all previous destination data and credentials (old tokens/users not in the export stop working). §10
- S1-090 [U] Export is an atomic, read-only snapshot; later writes on the source do not alter an export already taken; the export has no dependency on the source process, files, port or address (works on a fresh container). §10
- S1-091 [U] Reset after import clears imported state too. §10
- S1-092 [U] Generated references/ids after import never collide with imported ones. §8, §10

### 1.K Atomic reservation moves (§11)

- S1-093 [R] `POST /reservation-moves` requires auth (401 without) and an Idempotency-Key (§7 rules). §11
- S1-094 [R] Body `{"moves":[{reference, table_id?, starts_at_local?, party_size?}, ...]}`; `moves` must be an array of 1..8 objects with distinct string `reference`s; any other shape (missing/non-array `moves`, 0 or >8 items, non-object item, missing/non-string reference, duplicate references) → 422 `validation_failed`. §11
- S1-095 [R] Unknown reference or another owner's reference → 404 `not_found`. §11
- S1-096 [R] Bookings from different restaurants in one batch → 422 `validation_failed`. §11
- S1-097 [R] A cancelled listed booking → 409 `reservation_cancelled`; a listed booking within its cutoff → 409 `cutoff_passed`. §11
- S1-098 [R] Each item takes the ordinary PATCH fields; omitted fields keep current values; unknown fields ignored; identity, owner, reference and created_at never change. §11
- S1-099 [R] Non-occupancy errors use ordinary amendment codes and the first failing item **in input order** decides the response; within one item, cutoff errors precede its other field errors; occupancy conflicts (409 `table_unavailable`) are reported only when no item has a non-occupancy error. §11
- S1-100 [R,P] Occupancy is judged on the resulting state: an overlap among resulting bookings, or with an unlisted confirmed booking → 409 `table_unavailable`; swaps and chains among listed bookings (e.g. A t_1→t_2 while B t_2→t_1 at the same time) succeed. §11
- S1-101 [R,P] Listed bookings with no change keep their occupancy and all values (no-op). §11
- S1-102 [P,C] All-or-nothing: on any failure no reservation, occupancy or idempotency key changes (the key stays reusable); on success every move commits together. §11
- S1-103 [R] Success → 201 `{"reservations":[...]}` in input order, including unchanged items, each in reservation shape. §11
- S1-104 [R,U] Replay → 200 with the original body, even after later amendments or cancellations; export/import preserves batch receipts and resulting bookings. §11
- S1-105 [C] Concurrent moves/creates/amendments touching the same tables behave as some serial order: no overlapping confirmed bookings and no partial batch is ever observable. §1, §11

### Stage 1 ambiguities and chosen readings (Coordinator decisions)

- A-01 **Request-level precedence (create and moves).** 401 auth → 400 body not parseable / not a JSON object → 400 `missing_idempotency_key` → 422 key length → idempotency resolution (200 replay / 409 reuse) → field type and validation → resources → rules → occupancy. Why: §7 says idempotency is resolved after JSON-object parse and auth, before field validation and resource checks; the order of 401 vs 400 is unstated, and auth-first is the common convention.
- A-02 **Create rule precedence** after idempotency: 400 wrong JSON type (restaurant_id/table_id/starts_at_local) → 422 missing required field / invalid party_size / malformed starts_at_local → 404 restaurant / table (incl. table of another restaurant) → 422 `invalid_local_time` → 422 `outside_opening_hours` → 422 `not_on_slot_grid` → 422 `party_exceeds_capacity` → 409 `table_unavailable`. Why: occupancy is last (spec §11 treats it as last); DST gap must win over opening hours (a gap time is outside typical hours but the spec names `invalid_local_time` for it); the grid is defined only inside opening hours.
- A-03 **Cutoff boundary.** Refused iff now ≥ starts_at − cutoff (exactly at the boundary counts as "within"). With cutoff 0, refused iff now ≥ starts_at. Why: "within N minutes ... or later".
- A-04 **PATCH precedence.** 401 → 400 unparseable/non-object body → 404 not found/not owner → 400 wrong JSON type → 409 `reservation_cancelled` → 409 `cutoff_passed` (current start) → create validation order (A-02) on the merged result. An empty or no-op PATCH on an editable booking → 200 with the unchanged booking; it is still subject to cancelled/cutoff. The new start is not itself cutoff-checked. Why: §8 says cutoff measured against the current start; stage 3 confirms cutoff precedes field validation and no-ops require an editable booking.
- A-05 **Cancel precedence.** 401 → 404 → already cancelled (200) → cutoff (409). Why: cancelling twice "is not an error".
- A-06 **Idempotency namespace** is (user, method, path, key). Same key on another path is independent whatever the body. Request fingerprint = parsed JSON body value.
- A-07 **Idempotency for failed first requests**: only a 2xx outcome is stored; a 4xx leaves the key unused.
- A-08 **End vs closes**: slot offered / booking accepted iff the absolute end instant ≤ the instant of `closes` on that local date. Grid steps are wall-clock minutes from `opens`; gap times are skipped; repeated times appear once (first occurrence). Why: §9 says duration is absolute; §9 says skipped times never appear and repeated ones appear once, which only a wall-clock grid gives.
- A-09 **`GET /reservations` tie order**: equal `starts_at` → later `created_at` first, then reference. Unspecified; any deterministic order is acceptable.
- A-10 **Email comparison** is case-insensitive for uniqueness and login; stored as given. Email valid iff exactly one `@`, non-empty local and domain parts, no whitespace. `display_name` is a required non-empty string.
- A-11 **Availability param precedence**: missing/invalid params (422) before unknown restaurant (404).
- A-12 **Moves precedence**: after A-01, envelope shape (422) for the whole body; then per item **in input order**: 404 unknown/not owner → 422 restaurant differs from the first item's → 409 `reservation_cancelled` → 409 `cutoff_passed` → ordinary amendment validation (A-02 order, occupancy excluded). Then occupancy over the whole resulting set (409 `table_unavailable`). No-op items are still subject to cancelled/cutoff checks. Wrong JSON type of an item's PATCH field → 400 `malformed_request` in that item's turn.
- A-13 **Seeded reservations**: `created_at` = the fixture value if present, otherwise the reset time; references taken verbatim from the fixture.
- A-14 **Unknown routes** → 404 `not_found`; a known path with an unsupported method → 404 `not_found` or 405 with the error body; either is acceptable.
- A-15 **Success status codes not stated**: PATCH 200, cancel 200, GET 200, signup 201, login 200, moves 201, create 201.
- A-16 **`party_size` JSON numbers with a fraction** (e.g. 2.5) → 422; whether `4.0` is accepted is implementation-defined and not tested by the band.
- A-17 **Stage folders hold their own stage only.** `stage-1/` must not implement stage-2+ behaviour (the harness probes `stage-N/` with suite N+1 and a full pass there voids the stage). Designing the data model so later stages can extend it is encouraged.
- A-19 **Fixture IDs over 64 characters**: the spec bounds fixtures to 64; the service may assume it. Rejecting a longer fixture ID with 422 `validation_failed` (state unchanged) is acceptable; it is not tested by the band.
- A-18 **Isolated checks**: graded (isolated) evidence comes only from the WSL command in the task; native-Windows isolated runs prove nothing (they collect zero tests).

---

## Stage 2 — online booking and combined tables (spec: `stage-2.md`; all stage-1 lines stay in force)

### 2.A Screens and routes

- S2-001 [B,R] `GET /`, `/signup`, `/login`, `/lookup` each return an HTML page (text/html) reachable directly by URL; other screens are reachable through the UI. Stage-2 "Routes"
- S2-002 [B,D] Every script, stylesheet, font and image the UI uses is served from the image (no CDN, no outbound fetch). Stage-1 §2, task constraints
- S2-003 [B] Navigation is consistent across the four routes; `current-user` (text contains the display name) is visible on every screen while signed in; `logout-button` signs out. "Signup and login"
- S2-004 [B] Signup (`signup-email`, `signup-password`, `signup-display-name`, `signup-submit`) and login (`login-email`, `login-password`, `login-submit`) work against the API; failures show `auth-error`, which is absent from the DOM when there is no error. "Signup and login"

### 2.B Search and availability grid (`/`)

- S2-005 [B] `restaurant-select` option values are restaurant ids; `date-input` value is `YYYY-MM-DD`; `party-size-input` is a number input; `search-button` runs the search; results live in `availability-grid`. "Search and availability grid"
- S2-006 [B] One cell per table per slot with testid `slot-{table_id}-{HH:MM}` (local start time), carrying `data-available="true"` exactly when the table is in that slot's `available_table_ids` for the searched party size, otherwise `"false"`. "Search and availability grid"
- S2-007 [B] A day with no slots shows `no-slots` instead of the grid. "Search and availability grid"
- S2-008 [B] Clicking an available cell opens the booking form for that table/option and slot; clicking an unavailable cell does nothing; signed out, clicking an available cell shows `auth-error` or navigates to `/login`. "Search and availability grid"
- S2-009 [B] Out-of-order responses: if search A starts before search B and finishes after it, the grid, table labels and booking form describe B; a late response never restores A. "Competing clients"
- S2-010 [B] Combination cells `slot-{t_a}+{t_b}-{HH:MM}` (ids in `combinable` order) with `data-available` exactly as for single cells (true iff the pair is in that slot's `available_options`). (A-21.) "UI"

### 2.C Booking form, confirmation, recovery

- S2-011 [B] `booking-form` contains `booking-summary` (text names every table label of the selection and the local start time), `booking-party-size` (number input pre-filled from the search), `booking-submit`. "Booking form", "UI"
- S2-012 [B] Success shows `confirmation` with `confirmation-reference` (text is exactly the reference), `confirmation-details` (restaurant name, table label, local start time) and `confirmation-tables` (every table label). "Confirmation", "UI"
- S2-013 [B,R] The booking form stays on screen after success; resubmitting it unchanged returns the same `confirmation-reference` with no `booking-error` and no second booking (same Idempotency-Key and body → 200 replay); changing any field makes the next submission a new request with a new key. "Booking form", §7
- S2-014 [B] `409 table_unavailable` on submit → `booking-error` shown, availability refreshed, the selected form and its inputs preserved, no confirmation for that attempt. "Competing clients"
- S2-015 [B] A lost booking response (network failure, including after the server committed) → nonempty `booking-uncertain`, no `booking-error`, no new confirmation. "Competing clients"
- S2-016 [B,R] Retrying the unchanged form after an uncertain outcome sends the same Idempotency-Key and body; a successful retry removes the uncertainty/error elements and shows the original reference; a confirmed rejection shows `booking-error`. "Competing clients"
- S2-017 [B] The browser never manufactures a successful result from cached data; the server is authoritative. No polling, live updates, cross-tab sync or reload recovery is required. "Competing clients"
- S2-018 [B] S2-014..S2-017 apply equally to combination bookings. "Competing clients", "UI"

### 2.D Lookup (`/lookup`)

- S2-019 [B] `lookup-reference-input` + `lookup-submit`; found → `reservation-detail` with `reservation-status` (text exactly `confirmed` or `cancelled`) and `reservation-tables` (every table label). "Lookup", "UI"
- S2-020 [B] `reservation-cancel-button` cancels; it is absent from the DOM once the reservation is cancelled. "Lookup"
- S2-021 [B] `reservation-error` shown when the reference is not found (or not the caller's) or when a cancel is refused (e.g. 409 `cutoff_passed`). "Lookup"

### 2.E Product quality (judged on its own merits)

- S2-022 [B] Coherent, presentation-ready, warm hospitality character; clear hierarchy for search → availability → booking; human-readable restaurant and table labels prominent; technical ids only where useful; combinations read as intentional seating options (e.g. "Tables 1 + 2 · seats 6"), not concatenated ids. "Product and visual direction"
- S2-023 [B] Consistent visual system (type, spacing, colour, controls, feedback); obvious primary actions; visually distinct available, unavailable, selected, loading, successful, refused and uncertain states. "Product and visual direction"
- S2-024 [B] No horizontal page scrolling at 375 CSS px and at desktop widths; required flows usable at both. "Product and visual direction"
- S2-025 [B] Visible labels on inputs, visible keyboard focus, keyboard-operable grid cells and buttons, sufficient contrast; considered empty, loading and error states. "Product and visual direction"

### 2.F Upgrade from stage 1

- S2-026 [U] A stage-2 service imports an export produced by the team's stage-1 service (204) and serves all of its data: users/passwords, tokens, reservations, references, idempotency receipts and move receipts. "Existing clients after an upgrade"
- S2-027 [U,B] A browser signed in before the export/import stays signed in afterwards without reload (its token still works). "Existing clients after an upgrade"
- S2-028 [U,B] A retained booking reference still works through the lookup screen after the upgrade. "Existing clients after an upgrade"
- S2-029 [U,B,R] A booking whose response was lost before export is retryable after import with the same key and body; the UI recovers the original confirmation; the form and its pending retry identity survive the upgrade without reload. "Existing clients after an upgrade"

### 2.G Combined tables — model and API

- S2-030 [R] Restaurant fixture gains `combinable`: list of unordered table-id pairs of that restaurant (default `[]` when absent); pairs only; not transitive. "Model"
- S2-031 [R] Combination capacity = sum of the two tables' capacities. "Model"
- S2-032 [R] Seeded reservations are confirmed unless `status: "cancelled"` (cancelled seeds occupy nothing) and may carry `table_id` or `table_ids`. "Model"
- S2-033 [R] Availability slots gain `available_options`: every single table and every declared pair with capacity ≥ party_size and no overlapping confirmed reservation on any member; singles first in fixture order, then pairs in `combinable` order; pair `table_ids` in `combinable` order; each `{table_ids, capacity}`. `available_table_ids` is unchanged (singles only). "API / GET /availability"
- S2-034 [R] `POST /reservations` accepts `table_ids` (array) instead of `table_id`; `table_id` still accepted as a set of one; both present → 422 `validation_failed`; neither → 422 `validation_failed`. "API / POST /reservations"
- S2-035 [R] Every reservation response carries `table_ids` (in `combinable` order for a pair); it carries `table_id` only when the set has exactly one member and omits it otherwise. This applies to create, GET, list, cancel, PATCH, moves, replays. "API / POST /reservations"
- S2-036 [R] Pair not declared in `combinable` (either order) → 422 `combination_not_allowed`; more than two tables → 422 `combination_not_allowed`; duplicate table id → 422 `validation_failed`; empty `table_ids` → 422 `validation_failed`; non-array or non-string members → 400 `malformed_request`. "API / POST /reservations", §5
- S2-037 [R,C] Any member taken for an overlapping interval → 409 `table_unavailable`; a pair booking occupies both tables for the full duration (each member then shows unavailable as a single and in every pair containing it). "API", "Combined tables"
- S2-038 [R] party_size > the pair's summed capacity → 422 `party_exceeds_capacity`. "API"
- S2-039 [R,P] `PATCH` accepts `table_ids` under the same rules (single ↔ pair changes allowed); cancelling frees every table in the set. "API"
- S2-040 [R,P] `POST /reservation-moves` items accept `table_ids`; no table may belong to overlapping resulting bookings; all stage-1 move rules apply. "UI" (last paragraph)
- S2-041 [C] Concurrent bookings, amendments, cancels and moves produce results equal to some serial order, and every invariant holds at every read. "Concurrent bookings and amendments"
- S2-042 [U] Stage-2 export → stage-2 import round-trips combined bookings, `combinable` and every stage-1 item (S1-085..S1-092).

### Stage 2 ambiguities and chosen readings

- A-20 **Table-set validation precedence** (create/PATCH/move item): 400 wrong JSON type → 422 both/neither of `table_id`/`table_ids`, empty set, duplicate id → 404 unknown table or table of another restaurant → 422 `combination_not_allowed` (more than two, or undeclared pair) → then stage-1 order from `invalid_local_time` onwards (capacity uses the summed capacity). Why: shape errors first, resources next, rules last, occupancy always last (A-02).
- A-21 **Combination cells**: render a cell for every declared pair at every slot, `data-available` true exactly when the pair is in that slot's `available_options` for the searched party size, false otherwise. Why: "carries `data-available` like a single cell" implies both values occur; this reading also satisfies "shown when a declared pair is available".
- A-22 **Pair order**: a pair given in reversed order names the same set; stored and returned in `combinable` order. (Stage 3 states this explicitly; adopted from stage 2 on.)
- A-23 **Export format**: `format_version` stays 1 (stage 1 fixes it); the opaque `state` may carry an internal schema version; stage-2 import must accept both the stage-1 and the stage-2 state shapes.
- A-24 **Lookup while signed out**: lookup uses the owner-only API, so a signed-out lookup shows `reservation-error` or `auth-error` with a sign-in link; a reference of another user shows `reservation-error` (no leak).
- A-25 **Retry identity**: the idempotency key is created when the booking form is opened or any of its fields changes, kept in page memory (not storage), and reused for every unchanged resubmission, including after an import between requests. Signed-in token may be kept in localStorage.
- A-26 **"Present only when there is one"** for `auth-error`, `booking-error`, `booking-uncertain`, `reservation-error`: the element is removed from the DOM (not merely hidden) when there is nothing to show.

---

## Stage 3 — booking policies, history and recurring reservations (spec: `stage-3.md`; all stage-1 and stage-2 lines stay in force)

### 3.A Availability explanations

- S3-001 [R] `explain` is optional; its only accepted value is `true`; any other value (`false`, `1`, `TRUE`, empty string) → 422 `validation_failed`. "Availability explanations"
- S3-002 [R] Without `explain` the response has no explanation fields (stage-1 shape plus stage-2 `available_options`). "Availability explanations"
- S3-003 [R] With `explain=true` every slot carries `explain`: every table of the restaurant exactly once, in fixture order, each `{table_id, policy_version, available, rules:[{rule:"capacity",holds}, {rule:"no_overlap",holds}]}` — both rules always present in that order. "Availability explanations" 1–2
- S3-004 [R] `available` is true exactly when both rules hold; the `table_id`s with `available: true` equal `available_table_ids` in the same order; a table failing both reports both false. "Availability explanations" 2–3
- S3-005 [R] Closed day → `"slots": []`; a slot with no available table still appears with a full `explain`. "Availability explanations" 4
- S3-006 [R] `capacity` uses the selected policy's capacity for that date; `policy_version` names the policy selected for the slot's local date (0 = fixture). "Policies and accepted terms"

### 3.B Reservation history

- S3-007 [R] `GET /reservations/{reference}/history` → 200 `{reference, entries:[...]}` for the owner only; anyone else, signed in or not (no token at all included), → 404 `not_found`. A cancelled reservation still has its history. "Reservation history", "Policies" last paragraph
- S3-008 [R] Each entry: `seq`, `at` (RFC 3339 with offset), `event`, `changes`, `revision`, `accepted_terms`. `seq` starts at 1 and increases by exactly 1; entries are in `seq` order, which is also `at` order (non-decreasing). "Reservation history" 1
- S3-009 [R] `created` names all three fields with `"from": null`, in the order `table_id` (or `table_ids` for a pair, S3-047), `starts_at_local`, `party_size`. "Reservation history" 2
- S3-010 [R] `changed` names only fields that actually changed, in the order `table_id`/`table_ids`, `starts_at_local`, `party_size`, with real `from`/`to` values; a PATCH that changes nothing succeeds and records no entry. "Reservation history" 3
- S3-011 [R] `cancelled` carries `changes: []` and nothing follows it. "Reservation history" 4
- S3-012 [R] An idempotent replay records nothing. "Reservation history" 5
- S3-013 [R] History entries carry the reservation's resulting `revision` and complete `accepted_terms` at that point; old entries never acquire newer terms. "Policies and accepted terms"

### 3.C Policies and accepted terms

- S3-014 [R] Fixture restaurants may carry `manager_user_ids` (default `[]`); only those users may publish policies. "Policies and accepted terms"
- S3-015 [R] `POST /restaurants/{id}/policies`: no token → 401; unknown restaurant → 404; authenticated non-manager → 403 `forbidden`; Idempotency-Key required with all stage-1 §7 rules (400 missing, 422 length, 200 replay, 409 reuse, 4xx keys reusable). "Policies and accepted terms"
- S3-016 [R] Body is a complete policy: `effective_from` (real `YYYY-MM-DD`), `slot_minutes` and `reservation_duration_minutes` integers 1..1440, `cancellation_cutoff_minutes` integer 0..10080, `opening_hours` per stage-1 rules with no duplicate weekday, `capacities` naming exactly the restaurant's table ids with integers 1..100. Booleans are not integers. Any violation (missing field, wrong type, out of range, extra or missing table id, unknown table id, duplicate weekday, closes ≤ opens, bad HH:MM, bad weekday) → 422 `validation_failed` with no version or state change. Unknown fields ignored. (A-28.) "Policies and accepted terms"
- S3-017 [R,P] Success → 201 with the supplied policy fields plus `policy_version` = 1, 2, 3… per restaurant (independent per restaurant). Failed writes and replays allocate no version. "Policies and accepted terms"
- S3-018 [R] Policies are immutable; table ids, labels, timezone and declared combinations cannot be changed by a policy. "Policies and accepted terms"
- S3-019 [R] `GET /restaurants/{id}/policies` is public → `{"policies":[...]}` in publication order, omitting policy 0 (empty list when none); unknown restaurant → 404. "Policies and accepted terms"
- S3-020 [R] `GET /restaurants/{id}` keeps returning the original fixture configuration after publications. "Policies and accepted terms"
- S3-021 [R,T] Selection: for a booking's (or slot's) local start date choose the policy with the greatest `effective_from` ≤ that date; ties → greatest `policy_version`; policy 0 (fixture rules) applies when none qualifies. Publication order may differ from effective-date order; effective dates may be in the past. "Policies and accepted terms"
- S3-022 [R] Availability (slot grid, opening hours, duration, capacities) and booking decisions (create, PATCH, moves, series occurrences) use the selected policy for the relevant local date, not the restaurant detail. "Policies and accepted terms"
- S3-023 [R] Every reservation response carries `revision` (1 at creation) and `accepted_terms` = `{policy_version, slot_minutes, reservation_duration_minutes, cancellation_cutoff_minutes, opening_hours, capacities}` — the whole selected policy except `effective_from`. "Policies and accepted terms"
- S3-024 [R] Seeded bookings start at revision 1 under policy 0. Replays of old idempotency keys return the original response, including its original revision and terms (or its original pre-stage-3 shape). "Policies and accepted terms"
- S3-025 [R,P] Publishing a policy never changes existing bookings, their `ends_at`, terms, revisions or history (also for past effective dates). "Policies and accepted terms"
- S3-026 [R,T] Cancel checks the booking's **accepted** cutoff against its current start; cancel increments revision once; a repeated cancel changes nothing. "Policies and accepted terms"
- S3-027 [R,P] A real amendment checks the **old accepted** cutoff first, then validates all resulting fields against the policy for the resulting start date; on success it atomically replaces accepted terms and `ends_at` and increments revision exactly once. "Policies and accepted terms"
- S3-028 [R,P] A no-op amendment (all supplied values equal the current ones, including a reversed pair) keeps terms, `ends_at`, revision and records no history, but still requires a confirmed booking outside its cutoff (409 `reservation_cancelled` / `cutoff_passed`). "Policies and accepted terms"
- S3-029 [R,P] A failed amendment changes nothing (revision, terms, history, occupancy). "Policies and accepted terms"
- S3-030 [R] PATCH optionally takes `expected_revision`: a positive integer different from the current revision → 409 `stale_revision`, checked before cutoff and validation; wrong type or range (0, negative, boolean, string, fraction, null) → 422 `validation_failed`; omitted → stage-1 behaviour. "Policies and accepted terms"
- S3-031 [C] Two concurrent amendments carrying the same `expected_revision`: at most one makes a real change; the other gets 409 `stale_revision` (or is a no-op). "Policies and accepted terms"
- S3-032 [R] `GET /reservations/{reference}/decision` → `{reference, revision, accepted_terms}` for the current booking, also after cancellation; owner-only, everyone else (including no token) → 404 `not_found`. "Policies and accepted terms"
- S3-033 [R] Managers gain no access to other diners' reservations, lookup, history or decision. "Policies and accepted terms"

### 3.D Recurring reservations (series)

- S3-034 [R] `POST /series` requires auth (401) and an Idempotency-Key (§7 rules). Body `{anchor_reference, count, interval_weeks}`; `count` integer 2..12, `interval_weeks` integer 1..4; invalid values including booleans, strings, fractions, missing → 422 `validation_failed`; unknown fields ignored. "Recurring reservations"
- S3-035 [R] Anchor unknown or another owner's → 404; cancelled → 409 `reservation_cancelled`; already adopted (anchor of a series or any occurrence of one) → 409 `already_in_series`; within its accepted cutoff → 409 `cutoff_passed`. "Recurring reservations"
- S3-036 [R,P] Occurrence 0 is the anchor itself, unchanged: reference, id, revision, terms, history, timestamps and its original idempotent response. "Recurring reservations"
- S3-037 [R,T] Occurrence i (1..count−1) starts on the anchor's local calendar date + i × interval_weeks × 7 days at the same local clock time, with the anchor's party size and table selection (single or pair). "Recurring reservations"
- S3-038 [R,T] Each generated occurrence selects its own date's policy (duration, grid, hours, capacity) and obeys opening hours, DST and occupancy; a nonexistent local time rejects the whole adoption with 422 `invalid_local_time`; a repeated time resolves to the first occurrence. "Recurring reservations"
- S3-039 [R,P] All-or-nothing: on any failure no series, reservation, history, counter or idempotency claim survives; the first failing occurrence in index order determines the ordinary booking error code. "Recurring reservations"
- S3-040 [R] 201 `{series_id, revision: 1, interval_weeks, occurrences:[{index, reference, exception:false, reservation:{ordinary reservation response}}]}` — all `count` occurrences in index order, each with a distinct reference. "Recurring reservations"
- S3-041 [R,P] Generated occurrences are ordinary reservations: listed in `GET /reservations`, occupy tables, have ordinary histories (a `created` entry), revisions and terms; references and indices never change when dates or tables change. "Recurring reservations"
- S3-042 [R] `GET /series/{series_id}` → the same shape with current reservation states and exception flags; another user or no token → 404 `not_found`. "Recurring reservations"
- S3-043 [R,P] A real individual PATCH of an occurrence permanently sets its `exception: true` and increments the series revision once; a no-op or failed PATCH changes neither. "Recurring reservations"
- S3-044 [R,P] Cancelling an occurrence increments the series revision once and keeps the occurrence in the series with its exception flag unchanged; a repeated cancel changes nothing; cancelling the anchor does not cancel its siblings. "Recurring reservations"
- S3-045 [R,P] Replays of `POST /series` return the original response (200) even after later changes and change no counter; adoption increments the restaurant revision once. "Recurring reservations"
- S3-046 [U] A stage-3 service imports exports from the team's stage-1 and stage-2 services; adoption works on imported reservations; confirmation links, sessions and original booking retries remain valid. "Recurring reservations" last paragraph

### 3.E Combined-table history and collective moves

- S3-047 [R] History: single-to-single operations use `table_id`; creating a pair uses `table_ids` (null → pair); any change involving a pair uses `table_ids` with complete before/after lists; table-set order is the declared combination order; a reversed input pair is the same set and is not an amendment on its own. Combination capacity in terms = sum of the **selected policy's** capacities. "Combined-table history"
- S3-048 [R,P] `POST /reservation-moves`: each real change checks the old accepted cutoff, then adopts the resulting date's policy; optional per-move `expected_revision` with PATCH validation and `stale_revision` rules; no-ops keep terms and history. "Collective moves"
- S3-049 [R,P] On success every changed booking gains exactly one revision and one `changed` history entry; the restaurant revision increases once per batch; each affected series revision increases once; each changed series occurrence becomes a permanent exception. "Collective moves"
- S3-050 [R,P] A failed batch or a replay changes no revisions, histories or exception flags. "Collective moves"
- S3-051 [U] Stage-3 export → import round-trips policies, versions, revisions, terms, histories, series (ids, revisions, exception flags), restaurant revisions and all receipts.

### Stage 3 ambiguities and chosen readings

- A-27 **Policy endpoint precedence**: 401 → 400 unparseable/non-object body → 400 missing key / 422 key length → idempotency resolution → 404 unknown restaurant → 403 non-manager → 422 policy validation. Why: §7 resolves idempotency before resource checks; a non-manager can never hold a successful key on that path, so 403 is unaffected in practice.
- A-28 **Wrong JSON types inside a policy, series or series-amend body** → 422 `validation_failed` (not 400). Why: "Invalid policy is 422", "Invalid values, including booleans, give 422" and "invalid type/range gives 422" are endpoint-specific and override §5's 400 rule; only an unparseable or non-object body is 400.
- A-29 **PATCH precedence (extends A-04)**: 401 → 400 body → 404 → 400 wrong type of table/time fields → 422 invalid `expected_revision` → 409 `stale_revision` → 409 `reservation_cancelled` → 409 `cutoff_passed` (old accepted cutoff) → resulting-field validation against the resulting date's policy → 409 `table_unavailable`.
- A-30 **Series precedence**: 401 → 400 body → key / idempotency → 422 body (`anchor_reference` missing/non-string, count, interval_weeks) → 404 anchor → 409 `reservation_cancelled` → 409 `already_in_series` → 409 `cutoff_passed` → occurrences 1..count−1 in index order, each with the A-02/A-20 order.
- A-31 **Imported pre-stage-3 bookings**: revision 1 and policy-0 terms (the restaurant's fixture rules); history synthesised as a `created` entry (at `created_at`, current fields) plus a `cancelled` entry (revision 2) when the booking is cancelled. Pre-stage-3 receipts replay with their original stage-1/2 bodies.
- A-32 **Restaurant revision** (observable from stage 4) is tracked from stage 3 on: +1 per successful new booking (including each adoption as a whole), real amendment, cancellation, policy publication, batch move; never for no-ops, failures or replays; exported and imported with the state.
- A-33 **Series revision events**: +1 for a real individual PATCH of an occurrence, +1 for a (first) cancel of an occurrence, +1 per successful batch move touching the series' occurrences with a real change.
- A-34 **Policy response** echoes the supplied policy's known fields (`effective_from`, `slot_minutes`, `reservation_duration_minutes`, `cancellation_cutoff_minutes`, `opening_hours`, `capacities`) plus `policy_version`; the list endpoint returns the same objects.

---

## Stage 4 — seating changes and recurring amendments (spec: `stage-4.md`; all stage 1–3 lines stay in force)

### 4.A Replan preview

- S4-001 [R] `POST /restaurants/{id}/replans`: no token → 401; unknown restaurant → 404; non-manager → 403 `forbidden`; Idempotency-Key required with §7 rules (replay 200 original, reuse 409, 4xx keys reusable). "Seating changes"
- S4-002 [R] Body `{table_id, from, to}`: `from`/`to` are RFC 3339 instants with explicit offsets and `from < to`; missing, unparseable, offset-less, or `from ≥ to` → 422 `validation_failed`; unknown table (or another restaurant's) → 404 `not_found`. "Seating changes"
- S4-003 [R] The proposed closure is `[from, to)`. Considered bookings = every confirmed booking at this restaurant whose occupancy overlaps that interval, on any table; all other bookings are fixed. (A-35.) "Seating changes"
- S4-004 [R] Planning supports at least 6 tables, 4 declared pairs and 6 considered bookings; larger inputs may return 422 `planning_limit`. "Seating changes"
- S4-005 [R] Each considered booking keeps reference, owner, party size, start, end and accepted terms and is assigned one single table or one declared pair whose capacity under **its own accepted terms** ≥ party size, with no conflict against fixed bookings, other assignments, previously applied closures or the proposed closure. Cutoffs do not prevent a repair; no booking disappears or is cancelled. "Seating changes"
- S4-006 [R] Among feasible plans choose the lexicographic minimum of: (1) number of bookings whose table set changes; (2) total unused seats (assigned capacity − party size, summed); (3) the vector of option ranks taken in ascending reservation-reference order, where singles are ranked first in fixture order, then pairs in declared order, from 0. "Seating changes"
- S4-007 [R] 201 `{plan_id, restaurant_revision, closure:{table_id, from, to}, assignments:[{reference, table_ids, changed}], moved_count, unused_seats}` with every considered booking in ascending reference order; `restaurant_revision` is the current restaurant revision. "Seating changes"
- S4-008 [R,P] Preview stores only the plan: no closure, occupancy, reservation revision, history or restaurant revision change. "Seating changes"
- S4-009 [R,P] No feasible plan → 409 `no_feasible_plan`, nothing stored or changed. "Seating changes"

### 4.B Restaurant revision

- S4-010 [R,P] Restaurant revision starts at 0 after reset and increments exactly once per successful new booking (create; a series adoption counts once), real amendment (PATCH; a batch move counts once; a series amend counts once), cancellation, policy publication, or plan application. No-op writes, failures, previews and replays never increment it. "Seating changes", stage-3 "Recurring reservations"

### 4.C Plan application

- S4-011 [R] `POST /restaurants/{id}/replans/{plan_id}/apply` with body `{}`: manager only (401/404/403 as S4-001) and Idempotency-Key required. "Seating changes"
- S4-012 [R] Unknown plan, or a plan of another restaurant → 404 `not_found`. "Seating changes"
- S4-013 [R,P] Any restaurant revision change since the preview → 409 `stale_plan`, nothing changed. A closure applied at another restaurant does not invalidate the plan. "Seating changes"
- S4-014 [R] A plan already applied under a different key → 409 `plan_already_applied`; replay of the successful key → 200 with the original response, even after later changes. "Seating changes"
- S4-015 [R] Success → 201 `{plan_id, restaurant_revision (new value), reservations:[...]}` with every considered booking in ascending reference order, in ordinary reservation shape. "Seating changes"
- S4-016 [R,P,C] Application is atomic: closure and all assignments are recorded together; concurrent applications never leave partially moved bookings. "Seating changes"
- S4-017 [R,P] Each moved booking: revision +1 once and exactly one `reassigned` history entry carrying a `table_ids` change (complete before/after lists) and the `plan_id`; accepted terms, `starts_at`, `ends_at` unchanged. Unmoved bookings gain nothing. Restaurant revision +1 once for the whole plan. "Seating changes"
- S4-018 [R,P] After application the closure removes the table (as a single and in every pair containing it) from availability for overlapping slots, creates and amendments overlapping it get 409 `table_unavailable`, and explanations report `no_overlap: false` for it. "Seating changes"
- S4-019 [R,P] Moved series occurrences keep their exception flags, scheduled dates, identities and accepted terms; each affected series revision +1 once per application if at least one member moved. "Amend recurring reservations"
- S4-020 [B] Existing availability, confirmation and lookup screens reflect an applied plan (new tables shown). "Seating changes"

### 4.D Series amendment

- S4-021 [R] `POST /series/{series_id}/amend`: owner only (unknown or other owner's series → 404; no token → 401); Idempotency-Key required with §7 rules. "Amend recurring reservations"
- S4-022 [R] Body `{expected_revision, from_index, local_time}`: `expected_revision` positive integer, `from_index` integer 0..count−1, `local_time` exactly `HH:MM` in 00:00..23:59; booleans, strings for integers, fractions, missing fields → 422 `validation_failed`; unknown fields ignored. "Amend recurring reservations"
- S4-023 [R] Series revision ≠ `expected_revision` → 409 `stale_revision`, before any occurrence's cutoff or booking validation. "Amend recurring reservations"
- S4-024 [R,T] Eligible = occurrences with index ≥ `from_index` that are neither cancelled nor exceptions. Each moves to `local_time` on its original scheduled local date, keeping reference, owner, party size and current table selection (including a replan-moved table set). "Amend recurring reservations"
- S4-025 [R] An occurrence whose resulting fields are identical is a no-op (keeps terms, revision, history). Each real change checks its old accepted cutoff, then adopts the policy for its resulting start date, exactly like an individual PATCH (DST gap → `invalid_local_time`, grid, hours, capacity). "Amend recurring reservations"
- S4-026 [R,P] Resulting occurrences must not conflict with unchanged occurrences, other bookings or applied closures; non-occupancy errors take precedence in occurrence-index order; otherwise an occupancy conflict → 409 `table_unavailable`. On failure no history, idempotency record or revision changes. "Amend recurring reservations"
- S4-027 [R,P] Success → 201 with the current series response; each changed occurrence gains exactly one `changed` history entry and one reservation revision; series revision and restaurant revision each +1 once if anything changed; no exception flags are set. All-no-op or empty eligible set → success with no revision change. "Amend recurring reservations"
- S4-028 [R] Replay → 200 with the original response, even after later edits or cancellations. "Amend recurring reservations"
- S4-029 [C] Concurrent amendments from the same `expected_revision` cannot both make a real change. "Amend recurring reservations"
- S4-030 [U] A stage-4 service imports exports from the team's stages 1–3; replans and series amendments work on imported data, including imported series with moved and cancelled occurrences; earlier booking and series receipts, histories and retries remain valid. Stage-4 export → import round-trips plans, closures, applied-plan receipts and series amend receipts. "Amend recurring reservations" last paragraph

### Stage 4 ambiguities and chosen readings

- A-35 **Considered bookings** are all confirmed bookings at the restaurant overlapping `[from,to)` in time, on any table (a booking on another table may stay, `changed: false`, or move if that lowers the objective). Why: "Consider every confirmed booking at this restaurant overlapping that interval. Other bookings retain their assignments."
- A-36 **Replan precedence**: 401 → 400 body → key / idempotency → 404 restaurant → 403 → 422 body (`table_id` missing/non-string, interval invalid) → 404 unknown table → 422 `planning_limit` → 409 `no_feasible_plan`.
- A-37 **Apply precedence**: 401 → 400 body → key / idempotency (replay 200) → 404 restaurant → 403 → 404 plan → 409 `plan_already_applied` → 409 `stale_plan`.
- A-38 **Empty plan** (no considered bookings): feasible; 201 with `assignments: []`, `moved_count: 0`, `unused_seats: 0`; applying it records the closure and increments the restaurant revision once.
- A-39 **Closure echo**: `closure.from`/`closure.to` are returned as RFC 3339 instants equal to the supplied instants (the supplied strings are acceptable).
- A-40 **Series amend precedence**: 401 → 400 body → key / idempotency → 404 series → 422 body → 409 `stale_revision` → per eligible occurrence in index order: old accepted cutoff (409 `cutoff_passed`) then resulting-field validation (non-occupancy codes) → occupancy over the whole resulting set (409 `table_unavailable`).
- A-41 **Scheduled date** of occurrence i = anchor local date + i × interval_weeks × 7 days (the anchor's original date at adoption); `local_time` must still exist on that date and satisfy the selected policy.
- A-42 **Reassigned entry shape**: `{seq, at, event:"reassigned", changes:[{field:"table_ids", from:[...], to:[...]}], plan_id, revision, accepted_terms}`; `table_ids` is used even for single→single repairs.

---

## Environment decisions and blockers

- E-01 (2026-10-05 22:12 IST) **BLOCKED: shared Docker daemon hung.** Evidence: `docker version` times out after 15-20 s; dockerd/containerd idle (load 0.00) in the docker-desktop VM with 10 GiB free; docker clients stuck since 21:59 IST (an `inspect` of tk-verifier-main-18082, an `rm -f` of tk-gate-a/b/c, a `ps`). Reported by Gate. Coordinator attempted to restart Docker Desktop; the runtime refused (not permitted to interfere with other workloads), so no restart or process kill was done by any seat on Coordinator's instruction. Non-docker work continues (code/ledger audit, suite writing); a read-only probe watches for recovery. Any result from a run interrupted by the hang is void as evidence.
