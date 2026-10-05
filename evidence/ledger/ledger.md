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
