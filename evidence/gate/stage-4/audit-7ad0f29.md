# Gate audit: stage 4, candidate 7ad0f2981a9716ccb5167bb14d7ef25afbc84eb0

- **Verdict: ACCEPTED 7ad0f2981a9716ccb5167bb14d7ef25afbc84eb0.**
- **Spec:** `stage-4.md`, plus stages 1-3. **Ledger:** 9c129ab (S4-001..S4-030, A-35..A-42), plus E-03 (f51debe).
- **Lineage, measured with git tree hashes:**
  - `ee33b9b:stage-4` = `0720c48:stage-3` (accepted stage 3).
  - At 7ad0f29, `stage-1/`, `stage-2/` and `stage-3/` are identical to the accepted e48a498, a87d4d1 and 0720c48.
  - Stage-4 work: 10 files, +411/−17. New file `replan.py`; changes to `series.py`, `model.py`, `api.py`, `booking.py`,
    `server.py`, `app.js`, plus Dockerfile/RUN.md wording.
- **Audited:** 2026-10-06 01:47 to 02:30 IST, in the clean worktree `scratch/gate/7ad0f29` (`git status` empty,
  HEAD = candidate).
- **Environment:** Docker restarted at about 01:53 (E-03). Every result below was produced after the restart. Gate
  ports 18300-18399; every docker call under a timeout; one harness run at a time.
- **Dry run:** Gate had already dry-run all probes on this same commit at 01:49, before it was posted. That dry run
  was green (`scratch/gate/tk/dry-7ad0f29`).

## 1. Clean build and start (`logs-7ad0f29/container-driver.log`)

`docker build --no-cache`: exit 0 in 8 s; image 46,132,406 bytes. Healthy under `--cpus 2 --memory 2g` in:

| Run | Healthy after |
|---|---|
| `PORT=8080` | 648 ms |
| `PORT` unset (default 8080) | 1360 ms |
| `PORT=9123` | 1478 ms |

Memory 18-39 MiB.

## 2. External checks: WSL isolated, all on the 7ad0f29 worktree

| Run | Result |
|---|---|
| `--stage 4` | stage 1 pass · stage 2 pass · stage 3 pass (stage-3 upgrade source built) · stage 4 pass · **claimed stage: 4 on the shipped checks** |
| `--stage 3` | stages 1-3 pass · stage 4 fail (overshoot, expected) · **claimed stage: 3** |
| `--stage 2` | stages 1-2 pass · stage 3 fail · **claimed stage: 2** |
| `--stage 1` | stage 1 pass · stage 2 fail · **claimed stage: 1** |

Report JSONs: `logs-7ad0f29/harness-isolated-stage{4,3,2,1}.json`.

**E-04 (Docker engine event reported at 02:03 IST).** Gate's run times (report `started_at`/`finished_at`, IST):

| Run | Started | Finished |
|---|---|---|
| `--stage 4` | 02:01:16 | 02:03:11 |
| `--stage 3` | 02:03:17 | 02:06:12 |
| `--stage 2` | 02:06:25 | 02:08:09 |
| `--stage 1` | 02:08:11 | 02:08:58 |

- The `upgrade_s4`, `ui_s2` and `a46` probes finished at 02:02:39, 02:03:21 and 02:03:26. The tk-gate-h1..h8 "exit
  137 at 02:03:27" is Gate's own `docker rm -f` teardown after those probes completed.
- The only Gate run in flight at 02:03:27 was `--stage 3`, and it passed. Per E-04 it was **re-run**
  (`checks/gate-s4-7ad0f29-iso-stage3-rerun`): stages 1-3 pass, stage 4 fails as expected, **claimed stage: 3**.

## 3. Verifier suite, run by Gate on this commit

`verification/stage-4` at 61a1e4b contains the stage-1..3 modules plus test_50..53.

- **Targets:** `tk-gate-s4-7ad0f29` on :18386 (PORT=9137) and :18387. Sources: e48a498 (:18388), a87d4d1
  (:18389) and 0720c48 (:18390).
- **Result: 673 passed, 3 failed, 3 skipped** (851 s). Log: `logs-7ad0f29/verifier-suite-s4-61a1e4b.log`.
- **All 3 failures are suite defects** (sent to Verifier):
  1. `test_50::test_more_than_six_considered_may_hit_planning_limit`.
     - The scenario is infeasible: at 19:30, six bookings are in progress on five usable tables once r_1 closes.
     - The suite's own oracle returns `(None, None)`, and Gate's independent `plan_oracle` also returns `None`.
     - The product's 409 `no_feasible_plan` is correct; the test nevertheless calls `check_plan`, which requires
       201.
  2. `test_52::test_occupancy_conflict_changes_nothing`, and
  3. `test_52::test_non_occupancy_errors_take_precedence_in_index_order`.
     - The setup books 21:30 on `r_rep` (120-min duration, closes 23:00). That booking would end at 23:30, so the
       product's 422 `outside_opening_hours` is correct.
     - The tests' real assertions never ran.
  - Gate fixed all three in a disposable copy (21:00 setup bookings, an 18:30 retry, and 409 when the oracle finds
    nothing feasible). Result against 7ad0f29: **3/3 pass**.
- **Skips:** 2 need `candidate.py` startup timing (measured in item 1); 1 is the null case the spec leaves
  undecided.

## 4. Gate probes (spec and ledger only)

Expected plans come from Gate's own brute-force `plan_oracle.py` over the S4-006 objective.

| Probe | Result |
|---|---|
| `probe_s4`, container A + fresh C | **90 PASS, 0 FAIL** |
| `upgrade_s4`: real stage-1, stage-2 and stage-3 images → fresh stage-4 | **17/0** |
| `ui_s4`: S4-020 browser, 1280 and 375 px | **12/0** |
| `probe_s3` / `probe_s2` / `probe_s1` (regression) | 175/0 · 55/0 · 240/0 |
| `ui_s2` browser regression / `a46_s2` | 83/0 · 7/0 |

What `probe_s4` covers:
- **S4-010, end to end:**
  - +1 each for: create, real PATCH, cancel, policy publication, plan apply (once per plan), series amend.
  - +0 for: replay, failed create, no-op PATCH, repeated cancel, preview, publication replay, all-no-op amend.
  - Batch move and series adoption increments are covered by Verifier test_51/52 (and Builder's rev_count), not by
    Gate's probe.
- **Replan validation:** 401/403 (non-manager, other restaurant's manager)/404/400; 7 invalid bodies give 422;
  unknown or foreign table gives 404.
- **Plans equal the oracle optimum in three scenarios:**
  - own accepted terms differ from the current policy;
  - the rank tie-break;
  - fewest unused seats beats a lower rank (pair t_1+t_5 over t_4).
- **Previews:** assignments are every considered booking in reference order (A-35); closure echo (A-39); preview
  replay; a preview changes nothing.
- **Apply:** 403/404; 201 with the new revision; a reassigned history entry with a `table_ids` change, the
  `plan_id` and revision; terms and times unchanged; unmoved bookings untouched; apply replay; plan_already_applied;
  stale_plan with nothing changed.
- **Other restaurants and concurrency:** another restaurant's closure does not invalidate a plan; 6 concurrent
  applies give exactly 1×201 and 5×409.
- **No feasible plan:** 409 with the revision unchanged.
- **Closures afterwards:** excluded from singles, pairs and explain (`no_overlap` false); create, pair create and
  PATCH are refused with 409; other days are unaffected.
- **Series amend:**
  - 401/404/400 and 11 invalid bodies give 422; stale before validation;
  - success: dates kept, occurrence revisions +1, changed entries, series and restaurant revisions +1, no
    exceptions;
  - replay; all-no-op;
  - exception and cancelled occurrences excluded;
  - conflict gives 409 with nothing changed; non-occupancy errors give 422;
  - 6 concurrent amends: exactly 1×201;
  - a replan-moved occurrence keeps its flags, dates and terms, with series revision +1; a later amend keeps the
    replan-moved tables.
- **Export → import round trip:** bookings and restaurant revision, apply receipt, applied state, and closure all
  survive.

What `upgrade_s4` covers:
- stage-1/2 exports: data, tokens, receipts, revision 1 under policy 0;
- stage-3 export: a series with an exception and a cancelled occurrence is identical after import; the series
  receipt replays; amend skips the exception and cancelled occurrences; replan and apply work on imported data.

What `ui_s4` covers: book on Booth 2 through the UI, then the manager closes Booth 2 and applies. Afterwards the
unchanged resubmit shows the same reference with confirmation-tables "Window 1", the grid shows Booth 2
unavailable, and lookup shows Window 1, with no horizontal scroll.

Logs: `logs-7ad0f29/`; screenshots: `logs-7ad0f29/screens/`.

## 5. Code audit

Gate pre-audited this exact commit at 01:49, before it was posted.

- **Planner (`replan._solve`).** Exact depth-first search over the considered bookings in reference order, trying
  options in rank order (singles in fixture order, then declared pairs).
  - Candidate filter: capacity under **each booking's accepted terms** ≥ party, no applied or proposed closure, no
    fixed-booking overlap.
  - Pruning on `(moved + must_move, unused + least_unused) >= best`. Both are valid lower bounds, and componentwise
    ≥ implies lexicographic ≥.
  - DFS meets complete assignments in lexicographic rank-vector order, and best changes only on a strictly smaller
    (moved, unused), so the first assignment with the optimal pair is the rank-vector minimum. **Exact.**
  - Unbounded up to 6 tables / 4 pairs / 6 bookings. Beyond that: ≤ 12 bookings under a 20 000-node budget, else
    422 `planning_limit` (S4-004 allows it).
- **Apply (`replan.apply`).** Order 404 plan → `plan_already_applied` → `stale_plan` (A-37). Under the store lock,
  the closure and every reassignment are written in one step. `_reassign` changes only `table_ids`, adds revision
  +1 and one `reassigned` entry carrying `plan_id`; terms, times and exception flags are untouched.
  `touch_series(moved)` runs once and `bump_restaurant` runs once.
- **Staleness.** The restaurant revision is captured at preview and compared at apply. Every state-changing write
  bumps it (`bump_restaurant` call sites).
- **Closure enforcement.** `Closure.blocks` covers singles and any pair containing the table. It is used in
  `booking.ensure_free` (create, PATCH, moves, series adoption, series amend) and in `booking.availability` (the
  taken set, so explain `no_overlap` is false and options are excluded).
- **Series amend (`series.amend`)** follows A-40:
  - 404 → 422 body → 409 stale;
  - then each eligible occurrence (index ≥ from, not exception, not cancelled) in index order: no-op skip, old
    accepted cutoff, `place` under the resulting date's policy;
  - then one `ensure_free` over the set;
  - then `apply_change(exception=False)`; series and restaurant revisions +1 once.
- **Imports.** `state_from_json` reads stages 1-4. Plans and closures round-trip, and series keep their scheduled
  dates.
- **UI (S4-020).** `refreshConfirmation` re-reads the reservation after any success, including a replay, to show
  current tables from server data only.
- **Idempotency.** Every new write path goes through `Api._idempotent` (A-36/A-37/A-40 order).

## 6. Regression

- **Stages 1-3 in the stage-4 folder:** isolated suites 1-3 pass; Verifier stage-1..3 modules are inside the 673
  passes; Gate probes s1/s2/s3/ui/a46 are green.
- **Accepted folders:** byte-identical at this commit.
- **Data and clients from stages 1-3:** `upgrade_s4` 17/0 and Verifier test_53 imports.

## 7. Fault probe

Each mutant is a disposable copy of 7ad0f29 `stage-4/tablekeeper` with one planted defect, run natively on Gate
ports 18360-18389. Tools: `tools/mkmut6.py` and `tools/faultprobe_s4.sh`.

- **Frozen suite:** Verifier 61a1e4b, test_50..53, with the 3 suite-defect tests deselected, run with `-x`.
- **Gate probe:** `probe_s4`.

| Mutant | Planted defect (ledger) | Frozen suite | Gate `probe_s4` |
|---|---|---|---|
| M60 | objective ignores unused seats (S4-006 criterion 2) | DETECTED `test_other_considered_bookings_stay_and_pair_used` | DETECTED |
| M61 | only bookings on the closed table are considered (A-35/S4-003) | DETECTED (same test) | DETECTED (3) |
| M62 | planner uses fixture capacities, not the booking's own accepted terms (S4-005) | **SURVIVED** (73 passed) | DETECTED (own-terms scenario) |
| M63 | apply skips the staleness check (S4-013) | DETECTED `test_apply_idempotency_already_applied_and_stale` | DETECTED (2) |
| M64 | restaurant revision +1 per moved booking, not per plan (S4-010/S4-017) | DETECTED `test_apply_moves_bookings_and_records_history` | DETECTED (2) |
| M65 | preview records the closure (S4-008) | DETECTED `test_preview_changes_nothing` | DETECTED |
| M66 | series amend marks exceptions (S4-027) | DETECTED `test_amend_moves_eligible_occurrences` | DETECTED (6) |
| M67 | series amend includes exception occurrences (S4-024) | DETECTED `test_exceptions_and_cancelled_are_not_eligible` | DETECTED |
| M68 | a closure blocks a pair only when it is the pair's first member (S4-018) | DETECTED `test_no_feasible_plan_changes_nothing` | **SURVIVED** (90/0) |
| M69 | reassignment does not bump the booking revision (S4-017) | DETECTED `test_apply_moves_bookings_and_records_history` | DETECTED |

**Outcome:** the frozen suite detected 9/10 and Gate's probe detected 9/10. Each survivor is caught by the other
side.

- **M62 (suite survivor):** a coverage gap for Verifier. No test has a considered booking whose *accepted* policy
  capacities differ from the fixture. It goes to Verifier after their RESULTS on this commit.
- **M68 (Gate survivor):** Gate's pair test happened to put the closed table first. Gate added a check with the
  closed table as a pair's second member to `tools/probe_s4.py`. Re-verified: the extended probe gives 91/0 on 7ad0f29
  (`logs-7ad0f29/probe_s4-final.log`) and now detects M68 (fail on "pair whose SECOND member is the closed table").
- Neither survivor is a product defect: 7ad0f29 passes both tests.
- Logs: `logs-7ad0f29/faultprobe-M6x.txt`.

## 8. Ledger audit

| Items | Evidence |
|---|---|
| S4-001 … S4-009 (preview) | probe_s4 (oracle-checked plans, validation, no-change, no-feasible), Verifier test_50, code audit |
| S4-010 (restaurant revision) | probe_s4 end to end, Verifier test_51/52 |
| S4-011 … S4-020 (apply, closures, series moves, browser) | probe_s4, ui_s4, Verifier test_51 |
| S4-021 … S4-029 (series amend) | probe_s4, Verifier test_52 |
| S4-030 (imports) | upgrade_s4, probe_s4 round trip, Verifier test_53 |

**Coverage counts:** S4 30/30 OK; S3 51/51, S2 42/42 and S1 105/105 OK in the stage-4 folder.

## Verifier report comparison

Verifier's RESULTS for 7ad0f29 (room message 0ee6d9ef) were run in Docker from a clean worktree, with stage-1/2/3
sources.

| Run | Verifier | Gate |
|---|---|---|
| Full suite 61a1e4b | 675 passed, 3 failed, 1 skipped | 673 passed, 3 failed, 3 skipped |
| The 3 failures | the same three suite misreadings Gate reported (msg 5160d9b4) | same |
| Fixed stage-4 modules at 31be4e8 (test_50..53) | 79 passed, 0 failed | **79 passed, 0 failed** (`logs-7ad0f29/verifier-suite-s4-31be4e8-modules.log`) |

- **The two reports agree.** Neither found a product failure. Gate's two extra skips are the `candidate.py`-only
  startup tests; Gate measured startup directly.
- **Coverage gap sent to Verifier after this report:** fault-probe survivor M62. No suite test has a considered
  booking whose accepted policy capacities differ from the fixture, so a planner using fixture capacities passes.
- **E-04:** Verifier's correction is recorded in the ledger. Their void run died in E-03 at about 01:52. The 02:03:27
  exit-137 records were Gate's own teardown.

## Gaps judged acceptable (none blocking)

- A null `starts_at_local` is undecided by the spec.
- A-44 is out of scope.
- `planning_limit` above the guaranteed 6/4/6 size is allowed by S4-004. The implementation plans up to 12
  bookings under a node budget.
