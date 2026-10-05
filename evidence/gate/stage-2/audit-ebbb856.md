# Gate audit: stage 2, candidate ebbb856b1ae32dd1f913af50528b97e3f5232464

- **Verdict: ACCEPTED ebbb856b1ae32dd1f913af50528b97e3f5232464.** Basis: every checklist item below.
- **Spec:** `kickoff/tablekeeper/spec/stage-2.md`, plus `stage-1.md`, which stays in force.
- **Ledger:** 904c56f. S1-001..S1-105 and S2-001..S2-042; decisions A-01..A-26 and A-43/A-44.
- **Base:** stage 1 ACCEPTED at e48a498 (audit 7191654).
- **Candidate history:** cb8bd83 is the copy, tree a057193, which is the same tree as `e48a498:stage-1`. ebbb856
  extends it. `stage-1/` is unchanged from e48a498 to ebbb856 (empty diff).
- **Audited:** 2026-10-05 23:53 to 2026-10-06 00:25 IST, in the clean worktree `scratch/gate/ebbb856`
  (`git status` empty, HEAD = candidate).
- **Environment rules:** Gate ports 18300-18399, every docker call under a timeout, and at most one harness run at a
  time.

## 1. Clean build and start

Log: `logs-ebbb856/container-driver.log`.

- `docker build --no-cache` of `stage-2/`: exit 0. pip installed tzdata fresh. The image is 46,121,937 bytes.
- Start under `--cpus 2 --memory 2g`, time to the first `GET /health` 200:

  | Run | Healthy after |
  |---|---|
  | `PORT=8080` | 422 ms |
  | `PORT` unset (default 8080) | 623 ms |
  | `PORT=9123` | 646 ms |

- Memory after the probes: 18-47 MiB.
- The page loads nothing from another origin (UI probe), and the server sends
  `Content-Security-Policy: default-src 'self'` (code).
- Every asset ships in the image. The isolated run below had no outbound network.

## 2. External checks (organizers' harness)

| Run | Result |
|---|---|
| **Isolated, WSL** `--stage 2` on the worktree (`checks/gate-s2-ebbb856-isolated-wsl`) | stage 1: pass 120/120 · stage 2: pass 25/25 (incl. the stage-1 upgrade source built from `stage-1/`) · stage 3: fail (overshoot, expected) · **claimed stage: 2 on the shipped checks** |
| **Isolated, WSL** `--stage 1` on the same worktree (`checks/gate-s1-ebbb856-isolated-wsl`) | stage 1: pass 120/120 · stage 2: fail (overshoot, expected) · **claimed stage: 1**. The accepted `stage-1/` is still intact at this commit |
| Host `--stage 2` (`checks/gate-s2-ebbb856-host`) | stage 1 120/120 · stage 2 25/25 · stage 3 fail · claimed stage: 2 |

Report JSONs are copied to `logs-ebbb856/harness-*.json`.

## 3. Verifier suites, run by Gate on this commit

Both suites ran against Gate's own containers built from `tk-gate-s2-ebbb856`.

**Stage-2 suite** (`verification/stage-2` at ec1e588; it includes the stage-1 tests):

- Command: `run.py --base-url :18386 --second-base-url :18387`.
- Stage-1 source for the upgrade tests: `TK_STAGE1_BASE_URL` pointed at `tk-gate-s1-e48a498` on :18388.
- Result: **485 passed, 4 failed, 3 skipped** (552 s). Log: `logs-ebbb856/verifier-suite-s2-ec1e588.log`.
- **All 4 failures are suite defects.**
  - `test_20::test_create_pair_response_shape`, `test_patch_single_to_pair_and_back` and `test_moves_with_table_ids`:
    `tk.RES_KEYS` still requires `table_id`. The stage-2 rule is to omit `table_id` when there is more than one
    table, and the product's pair responses do that correctly.
  - `test_30::test_grid_matches_availability_api` reads the `restaurant-select` options straight after
    `page.goto`, before the client-side fetch fills them.
    - Gate measured the select at the load event: it holds `[["", "Loading restaurants…"]]` on 2 of 3 loads, and
      settles to the restaurant ids.
    - Client-side rendering and loading states are both permitted by the spec.
  - Gate fixed both suite issues in a disposable copy and re-ran the 4 tests: **4/4 pass**. Verifier was notified.
- Skips: 2 need `candidate.py` startup timing, which Gate measured in item 1. 1 is the null-string case the spec
  leaves undecided.

**Stage-1 suite** (`verification/stage-1` at 64b510b) against the stage-2 build:

- Command: `run.py --base-url :18389 --second-base-url :18390`.
- Result: **401 passed, 1 failed, 3 skipped**. Log: `logs-ebbb856/verifier-suite-s1-64b510b.log`.
- The failure is `test_parallel_same_key_different_bodies_take_effect_once`. The *client* raised
  `ConnectError [WinError 10055] … lacked sufficient buffer space` before any HTTP response. That is Windows host
  socket exhaustion (296 sockets in TIME_WAIT afterwards), not a product response.
- Re-run of `test_01_concurrency.py` on a fresh container: **10/10 pass**. The same test also passes inside the
  stage-2 suite run.

**Comparison with Verifier's RESULTS:** see the section at the end.

## 4. Gate's own probes (independent of the Verifier suites, from spec and ledger only)

| Probe | Target | Result |
|---|---|---|
| `probe_s1.py`: stage-1 regression | container A + fresh C | **240 PASS, 0 FAIL** (412 requests, no 5xx) |
| `probe_s2.py`: combined tables API | container A + fresh C | **55 PASS, 0 FAIL**, 4 NOTE (A-20 readings consistent) |
| `upgrade_s2.py`: real stage-1 image (e48a498) → export → fresh stage-2 import | :18391 → :18392 | **18 PASS, 0 FAIL** |
| `ui_s2.py`: Playwright Chromium, 1280 and 375 px | fresh container :18393 | **83 PASS, 0 FAIL**, 2 NOTE |

What each probe established:

- **`probe_s2.py`:**
  - `available_options` contents and order: singles in fixture order, then pairs in `combinable` order.
  - Pair occupancy blocks both members and every pair containing them; back-to-back is allowed.
  - Creating a reversed pair stores it in declared order; `table_id` is present only for singles.
  - Errors: 422 `combination_not_allowed` for an undeclared pair or three tables; 422 for a duplicate, empty, both
    fields or neither; 400 for a non-array or non-string; 404 for an unknown or foreign member; 422 when the party
    exceeds the summed capacity.
  - PATCH single↔pair; cancel frees both tables.
  - Moves with `table_ids`: a swap and a chain succeed; overlap gives 409; an undeclared pair gives 422.
  - Seeded `table_ids` and `status: cancelled` are honoured.
  - A 30-way pair-vs-single race is consistent with a serial order.
  - Export/import round trip, including into a fresh instance.
- **`upgrade_s2.py`:**
  - Stage-1 bearer tokens and a stage-1 signup's password still work.
  - Reservations come across in stage-2 shape.
  - The lost-before-export retry returns 200 with the original body, which is identical to the stage-1 original.
  - The pre-move create receipt and the move receipt replay; a reused key with a different body gives 409.
  - A failed stage-1 key is reusable.
  - Occupancy and options are imported, new references are unique, and the stage-2 re-export/import works.
- **`ui_s2.py`:**
  - Routes return HTML, with no horizontal scroll at 1280 and 375. Auth works, with `auth-error` present only when
    there is an error.
  - `current-user` appears on all four routes, and logout works.
  - The grid matches the API cell by cell, including the A-21 combination cells, at party sizes 2 and 5.
  - `no-slots` shows on a closed day; an unavailable click does nothing; a signed-out click gives auth-error or
    /login.
  - The booking form summary covers single and pair; the confirmation shows the reference, details and tables.
  - An unchanged resubmit reuses the same key and body and returns the same reference with no new booking; a
    changed field gets a new key.
  - 409 while the form is open: booking-error, availability refreshed, form preserved, no confirmation.
  - Response lost after commit (pair): uncertain, then the retry uses the same key and body and shows the original
    reference, with exactly one booking.
  - Response lost before commit, then the table is taken: booking-error.
  - Out-of-order searches: a held search-A response does not restore A, and the form describes B.
  - Lookup: found, status, tables; cancel removes the button; unknown and another user's references give
    `reservation-error`; a refused cancel (cutoff) gives `reservation-error`.
  - Mid-session export→reset→import: still signed in, and the pending retry recovers the original confirmation with
    the same key, without a reload.
  - At 375 px: Tab reaches the grid with a visible 3 px focus ring; Enter opens the form and Enter submits; every
    input has a label.

Logs: `logs-ebbb856/probe_s1-container.log`, `probe_s2-container.log`, `upgrade-s1-to-s2.log` and `ui-probe.log`.
Screenshots: `logs-ebbb856/screens/`.

## 5. Code audit (stage-2 diff cb8bd83..ebbb856: 11 files, +1560/−66)

- **Seating rules.**
  - `booking.check_table_types` → `requested_tables` → `select_tables` → `place` → `ensure_free` follows A-20.
  - `select_tables` returns the declared-order pair, or raises 404 / 422 `combination_not_allowed`.
  - `place` sums capacities.
  - `ensure_free` remains the single occupancy check, by set intersection over `table_ids`, for create, PATCH and
    moves.
  - Availability builds options from `Restaurant.options()`: singles first, then pairs in declared order. It derives
    `available_table_ids` from the free singles.
  - A PATCH no-op compares table *sets*, so a reversed pair is a no-op.
- **Concurrency.** The single store lock and the receipt-in-the-same-step design are unchanged from the accepted
  stage 1.
- **Upgrade.**
  - `model.READABLE_STAGES = (1, 2)`. Stage-1 state loads unchanged.
  - Receipts keep their original bodies, so a replay is identical to the stage-1 response (§7 "identical").
  - `_table_set` normalises stored pairs to declared order.
- **UI: out-of-order searches.** `app.js runSearch` numbers each search (`search.seq`). A response whose seq is no
  longer current is dropped before it touches state. A refresh after a 409 or a success is also a numbered search
  and keeps the form.
- **UI: retry identity.**
  - `submitBooking` keeps `{key, fingerprint(JSON body), userId}` in page memory and reuses the key while the body
    is unchanged.
  - A changed field means a new key and clears the old confirmation.
  - A network failure, timeout, 5xx or unparseable 2xx counts as uncertain and keeps the key. A 4xx is a confirmed
    rejection.
  - The confirmation is built only from the server's response data, never from cached data (S2-017).
- **Serving.** `ui.py` loads the assets into memory at start. `/static/<name>` is a dictionary lookup with no
  filesystem path, so there is no traversal. The CSP is `'self'` only, and the system font stack means no web
  fonts.
- **Stage-3 behaviour (A-17):** none present. There is no policy, revision or history surface, and the harness
  stage-3 probe fails.

## 6. Regression

- **Stage 1 in the stage-2 folder:** isolated shipped stage-1 checks 120/120; Gate `probe_s1` 240/0; Verifier
  stage-1 tests 401 passed + re-run 10/10 (in both suites).
- **Upgrade of stage-1 data and clients:** `upgrade_s2.py` 18/0, the Verifier `test_21_upgrade` tests pass, and the
  browser keeps its session and retry identity across import.
- **Accepted `stage-1/`:** unchanged and still claims stage 1.

## 7. Product judgement (S2-022 … S2-025), from screenshots at 1280 and 375 px

| Item | Judgement |
|---|---|
| S2-022 | **Meets.** A warm, coherent hospitality look: cream background, deep-red primary actions, serif headings. Clear hierarchy: search card → day header with a summary ("8 of 8 times with a free table") → grid by time → booking card → confirmation. Tables show human labels with "Seats N". Pairs read as seating options ("Window 1 + Booth 2 · Seats 6 · joined"). Ids appear only in the booking reference. |
| S2-023 | **Meets.** A consistent type, spacing and colour system. The states are visually distinct: available (green-tinted), unavailable (greyed and struck through), selected (solid red), loading ("Updating availability…"), success (green confirmation panel), refused (red error panel with icon), uncertain (amber panel with "?" icon and a "Try again" button). |
| S2-024 | **Meets.** No horizontal page scroll on any route or state at 375 or 1280 (measured). At 375 the grid wraps to two columns. |
| S2-025 | **Meets.** Visible labels on every input; a 3 px focus ring (`:focus-visible`); grid cells and buttons work from the keyboard; text and controls have adequate contrast (dark on cream, white on deep red); considered empty, loading and error states (`no-slots` panel, "Loading restaurants…", inline errors). |

Polish notes, not blocking:

- At 375 px the confirmation sits below a long grid, and the page does not scroll to it.
- The empty-day header reads "0 of 0 times".
- `restaurant-select` briefly shows a "Loading restaurants…" option with value `""` before the list loads. This is
  permitted, but rendering the options server-side would remove the race that the Verifier's test hit.

## 8. Ledger audit (S2-001 … S2-042; S1 lines re-evidenced in item 6)

| Items | Status | Evidence |
|---|---|---|
| S2-001 | OK | UI probe: 4 routes 200 `text/html` at both widths. Harness stage 2. |
| S2-002 | OK | UI probe: zero cross-origin requests. CSP `'self'`. Isolated run offline. |
| S2-003, S2-004 | OK | UI probe: auth flows, `auth-error` presence and absence, current-user on 4 routes, logout. Verifier test_30. |
| S2-005 | OK | Select options are restaurant ids once loaded; date is `type=date` and party size is `type=number` (DOM check). The loading placeholder is noted above. |
| S2-006, S2-007, S2-008, S2-010 | OK | UI probe: cell-by-cell grid vs API at parties 2 and 5 including pairs (A-21); no-slots; unavailable click; signed-out click. Verifier test_30, fixed copy 4/4. |
| S2-009 | OK | UI probe: held response A vs B, and the form describes B. Code: `runSearch` seq. Verifier test_30. |
| S2-011, S2-012, S2-013 | OK | UI probe plus Verifier test_30. |
| S2-014 … S2-018 | OK | UI probe: 409; lost after commit (pair); lost before commit then rejected; retry key and body identity. Code `submitBooking`. Verifier test_30. |
| S2-019, S2-020, S2-021 | OK | UI probe: lookup found, cancelled, not found, another user's, refused cancel. Verifier test_30. |
| S2-022 … S2-025 | OK | Item 7 judgement, plus measured no-scroll, focus, keyboard and label checks. |
| S2-026 … S2-029 | OK | `upgrade_s2.py` 18/0 (real stage-1 image). UI probe: import mid-session. Verifier test_21 and test_30 upgrade. Harness stage 2 (upgrade source). |
| S2-030 … S2-042 | OK | `probe_s2.py` 55/0. Verifier test_20 (fixed copy for the 3 shape tests). Code audit. |

- **Coverage counts:** S2: 42/42 OK, 0 FAIL, 0 PENDING. S1: 105/105 OK in the stage-2 folder (item 6).
- **Gaps:** none in invariants, error cases, all-or-nothing operations, concurrency, retries or persisted state.

## 9. Fault probe

Each mutant is a disposable copy of ebbb856 `stage-2/tablekeeper` with one planted defect, run natively on Gate
ports 18360-18367. The runner is `tools/faultprobe_s2.sh`; the M26 stage-1 source is the e48a498 image on :18368.

- **Frozen suite:** Verifier stage-2 at ec1e588, with its 4 known-bad tests deselected, run with `-x`.
- **Gate probe:** `ui_s2` for the UI mutants, `probe_s2` for the API mutants, `upgrade_s2` for M26.

| Mutant | Planted defect (ledger) | Frozen suite: first failing test | Gate probe |
|---|---|---|---|
| M20 | stale search responses not dropped (S2-009) | DETECTED `test_late_search_response_never_restores_old_results` | DETECTED (2 fails) |
| M21 | new Idempotency-Key on every submit (S2-013/S2-016) | DETECTED `test_book_confirm_resubmit_and_change` (no same reference) | DETECTED |
| M22 | lost response shown as booking-error, not uncertain (S2-015) | DETECTED `test_lost_response_then_retry_recovers_original[single]` | DETECTED (3) |
| M23 | availability checks only the first pair member (S2-033/S2-037) | DETECTED `test_pair_booking_blocks_members_and_every_pair_containing_them` | DETECTED (2) |
| M24 | pair capacity = max instead of sum (S2-031/S2-038) | DETECTED (pair booking refused 422) | DETECTED (10) |
| M25 | undeclared pairs bookable (S2-036) | DETECTED `test_table_set_validation[undeclared]` | DETECTED (3) |
| M26 | stage-1 state rejected on import (S2-026) | DETECTED `test_stage1_export_imports_into_stage2` | DETECTED (14) |
| M27 | `table_id` also sent for pairs (S2-035) | DETECTED `test_cancel_pair_frees_every_member` (shape) | DETECTED (7) |

**Outcome: 8 of 8 detected by the frozen suite, and 8 of 8 by Gate's probes. No survivors.** Logs:
`logs-ebbb856/faultprobe-M2x.txt`.

## Verifier report comparison

Verifier's RESULTS for ebbb856 (room message 2f04a81f) were run in Docker from a clean worktree.

| Suite | Verifier | Gate |
|---|---|---|
| Stage-1 suite 64b510b on the stage-2 build | 404 passed, 0 failed, 1 skipped | 401 passed + 1 host-socket error; the re-run of that module gives 10/10 |
| Stage-2 suite, first full run at ec1e588 | 488 passed, 3 failed (RES_KEYS suite defect) | 485 passed, 4 failed (same 3 + the options race) |
| Stage-2 suite at c9e88ab | 490 passed, 1 failed (the options race) | not run (superseded) |
| Stage-2 suite at 1aecf08 | browser + upgrade modules 38/38 | test_20, 21, 30, 13 and 14: **183 passed, 0 failed, 1 skipped** |

- **The two reports agree.** Both found no product failures. Gate and Verifier independently identified the same two
  suite defects (RES_KEYS; the asynchronously loaded options), which Verifier fixed in c9e88ab and 1aecf08.
- Gate's run at 1aecf08 against fresh `tk-gate-s2-ebbb856` containers (:18386/:18387, stage-1 source :18388) is
  logged in `logs-ebbb856/verifier-suite-s2-1aecf08-modules.log`.
- The isolated harness and the colour-contrast judgement were done by Gate (items 2 and 7).

## Gaps judged acceptable (none blocking)

- A null `starts_at_local`: 400 vs 422 is undecided by the spec and untested by design.
- A-44: pre-1893 offsets are out of scope.
- The polish notes in item 7: at 375 px the confirmation sits below a long grid; the empty-day text reads
  "0 of 0 times"; the restaurant select shows a transient loading option.
