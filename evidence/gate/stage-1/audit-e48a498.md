# Gate audit: stage 1, candidate e48a498f699eb9f7dd4f5c08f1092b7821e69aef

- Verdict: **ACCEPTED e48a498f699eb9f7dd4f5c08f1092b7821e69aef**. The basis is in "Verdict basis" at the end.
- Supersedes: REJECTED 105337a (D1). The previous audit is `audit-105337a.md`, with its fault probe in
  `faultprobe-105337a.md`.
- Spec: `kickoff/tablekeeper/spec/stage-1.md`. Ledger: stage-1 section of `evidence/ledger/ledger.md`. That section
  is unchanged between fe058da and 904c56f; 904c56f adds only E-01/E-02 and A-43/A-44.
- Verifier suite: verification/stage-1 at 4a5ac23. Its test files are identical to bab7c99 (the tuned suite); 4a5ac23
  changes only default ports and README text.
- Audited 2026-10-05, 23:28 to 23:45 IST. Worktree `scratch/gate/e48a498`: clean, `git status` empty, HEAD equal to
  the candidate.
- Environment: Docker 29.0.1 after DOCKER READY. All containers and ports were in Gate's E-02 range (18383-18392),
  and every docker call ran under a timeout.

## 1. Clean build and start

Run by `tools/gate_run.sh`; log in `logs-e48a498/container-driver.log`.

- `docker build --no-cache` of `stage-1/` from the clean worktree: exit 0 in 9 s.
  - `pip install tzdata==2025.3` ran fresh, as `build.log` shows.
  - Image `tk-gate-s1-e48a498` is 46,103,169 bytes.
  - `Dockerfile` and `RUN.md` are byte-identical to 105337a.
- Start under `--cpus 2 --memory 2g`, time to first `GET /health` = 200 `{"status":"ok"}` with
  `application/json; charset=utf-8`:

  | Run | Healthy after |
  |---|---|
  | `-e PORT=8080` | 545 ms |
  | `PORT` unset (default 8080) | 686 ms |
  | `-e PORT=9123` | 766 ms |

- After the probe: 18-55 MiB used of 2 GiB. The container log contains only the start line.
- Offline at run time: the graded isolated run (no outbound network) passed. See item 2.

## 2. External checks (the organizers' harness)

| Mode | Command | Result |
|---|---|---|
| Graded **isolated**, WSL, `~/harness-venv` | `harness run --track tablekeeper --repo /mnt/c/.../scratch/gate/e48a498 --stage 1 --mode isolated --out .../checks/gate-s1-e48a498-isolated-wsl` | `stage 1: pass` 120/120. `stage 2: fail` (overshoot, 1 failed of 25, expected). `highest contiguous stage: 1`, **`claimed stage: 1 on the shipped checks`**. |
| Host, Windows, `PYTHONTZPATH` set to host tzdata (client-side workaround) | `harness run --track tablekeeper --repo C:/.../scratch/gate/e48a498 --stage 1 --out .../checks/gate-s1-e48a498-host` | `stage 1: pass` 120/120. `stage 2: fail` (overshoot). `claimed stage: 1`. Report `revision` = e48a498f699e…. |

- Both reports are copied to `logs-e48a498/`.
- The WSL report's `revision` is empty because WSL git cannot read a worktree made by Windows git; the worktree HEAD
  is e48a498f699eb9f7dd4f5c08f1092b7821e69aef.
- There is no earlier increment, so there are no earlier-stage checks to run.

## 3. Verifier suite, run by Gate on this exact commit

- Command:
  `run.py --base-url http://127.0.0.1:18386 --second-base-url http://127.0.0.1:18387`
  - suite at 4a5ac23;
  - containers `tk-gate-v` (`PORT=9137`) and `tk-gate-w` (`PORT` unset), both from `tk-gate-s1-e48a498` with
    `--cpus 2 --memory 2g`;
  - `TK_CANDIDATE_DIR` = the worktree's `stage-1`.
- Result: **401 passed, 0 failed, 3 skipped** in 514 s. Log: `logs-e48a498/suite-e48a498-container.log`.
  - Two skips are the startup-timing tests, which need Verifier's `candidate.py`. Gate measured the same things
    directly in item 1.
  - One skip is the undecided `null` string case, an A-xx open point.
  - The suite includes the post-fault-probe tests: D1 at depths 500 to 2500 as lists and objects on five endpoints,
    and M8, receipts after every rejected import. All pass.
- Comparison with Verifier's report: see "Verifier report comparison" below.

## 4. Ledger audit (S1-001 … S1-105)

Legend: G = Gate probe (`probe-container.log`, against the container), V = Verifier suite (item 3),
E = Gate edge and deep round trip, H = harness, C = code reference. Everything was measured on e48a498 in
containers unless marked otherwise.

| Items | Status | Evidence |
|---|---|---|
| S1-001 | OK | `Dockerfile` and `RUN.md` present. The RUN.md command form (`docker build` then `docker run -e PORT -p`) is what the driver ran (item 1). |
| S1-002 | OK | Isolated harness run with no outbound network: 120/120. A single image, no compose. tzdata is installed at build. |
| S1-003 | OK | Containers started with `PORT=8080`, `PORT` unset and `PORT=9123` all became healthy (item 1). |
| S1-004 | OK | Healthy in 0.55-0.77 s, far under 60 s (item 1, H). |
| S1-005 | OK | 50-way bursts under `--cpus 2 --memory 2g`: probe and suite concurrency tests pass with every request under 5 s. Native load with 4000 bookings had max 0.77 s (105337a audit; the fix does not change request handling). |
| S1-006 | OK | D1 fixed. Edge probe: no 5xx at depths 500 to 100000 (100000 is 400). Suite `test_15_nested_ignored` passes. Probe and suite saw no other 5xx. |
| S1-007 … S1-105 | OK | Same evidence as the 105337a audit table: G (240 PASS, 0 FAIL in the container, now also checking receipts after rejected imports) and V (401 passed). The fix touches only fingerprinting, import depth, timestamp rendering for offsets with seconds, and error logging. Each is re-covered: S1-039/S1-040/S1-045 by G and V; S1-086/S1-088/S1-090 by the deep round trip below; S1-010 by G. |

- **Coverage counts:** 105 of 105 stage-1 items OK, 0 FAIL, 0 PENDING. No gaps in invariants, error cases,
  all-or-nothing operations, concurrency, retries or persisted state.
- **A-01 … A-19 readings:** consistent, as listed in the 105337a audit.
- **A-44** (out of scope): the candidate now renders offsets that contain seconds in UTC. This is harmless and keeps
  RFC 3339.

**Coordinator's audit pointer** (import rule "state nested > 64 → 422" vs S1-086/S1-088). Script
`tools/deep_roundtrip_s1.py`, log `logs-e48a498/roundtrip-e48a498-container.log`. Result **42 PASS, 0 FAIL**:

- Creates and moves batches carrying an ignored field nested 1000, 1400 and 1490 deep (list and object): 201,
  then replay 200 on the source.
- Export: 86 KB.
- Import into a *fresh* container: **204**.
- Every create and moves key replayed there gives **200 with the original body**; reuse with a different body gives
  409; the replays add no bookings.
- An ignored 1400-deep field on the import envelope: 204.
- A state carrying an *extra* 100-deep key: 422, with state intact. This is not an unchanged export, so the
  rejection is acceptable.

Reason this holds: receipts store the canonical fingerprint string and the shallow response, never the request
body, so exports stay about 6 levels deep.

## 5. Code audit

- **Diff 105337a..e48a498** (4 files, +81/−14):
  - `jsonio.fingerprint` and the new `depth` use an explicit stack. Gate traced the stack order:
    `{` key0 `:` v0 `,` key1 `:` v1 `}`.
  - `sorted(items)` sorts on the unique keys only, giving the same text as `json.dumps(sort_keys, separators)`
    with integral floats normalised. So existing receipt fingerprints and 4/4.0 equality are unchanged.
  - `Api.import_` rejects state deeper than 64 *before* `state_from_json`, so the destination is unchanged.
  - `timeutil.render` falls back to UTC only for offsets with seconds.
  - `server.Server` drops the redundant `allow_reuse_address` (HTTPServer already sets it) and silences
    connection-reset tracebacks only.
- **Siblings:** there is no other Python recursion over request JSON. `json.loads` is C, and its RecursionError is
  caught and returned as 400. `copy.deepcopy` in export walks server-built data only.
- **Invariant code unchanged from 105337a:** `store.py`, `booking.py` and `model.py` have no diff. `api.py` changed
  only in the import depth check. The 105337a code audit therefore stands:
  - one lock per request;
  - receipt check and store in the same locked step, 2xx only;
  - a single `ensure_free`;
  - moves planned before they are applied;
  - import and reset validated before the swap;
  - nothing special-cased to examples or check inputs.

## 6. Regression

Stage 1 is the first increment, so there is no earlier stage or carried-over data to regress against.

## 7. Fault probe

| Probe | Defect | Result |
|---|---|---|
| M1-M9 on 105337a (invariant code identical in e48a498), frozen suite becaddb | see `faultprobe-105337a.md` | 8 of 9 detected |
| M8 re-run against the tuned suite (4a5ac23 = bab7c99 tests), native port 18390 | rejected import wipes receipts | **DETECTED** by `test_import_of_internally_invalid_state_is_all_or_nothing`: a replay after a rejected import got 201 instead of 200 |
| M10, new, on e48a498 code | fingerprint ignores array contents | **DETECTED** by `test_03_moves::test_moves_key_reuse_with_different_or_invalid_body_409` |
| M11, new, on e48a498 code | import depth bound 3, which refuses valid exports | **DETECTED** by `test_05::test_round_trip_into_replaced_destination_preserves_everything` |

- Survivors on the current suite: none. M6 (the cutoff boundary) is detected by the suite, not by Gate's probe.
- Logs: `logs-e48a498/faultprobe-M10.txt` and `faultprobe-M11.txt`.

## Verifier report comparison

Verifier's RESULTS for e48a498 (room message dd65ad1d), Docker mode, suite 64b510b:
**404 passed, 0 failed, 1 skipped** (405 collected). 64b510b is bab7c99 plus Verifier's version of Coordinator's
deep round-trip test.

| Run | Suite | Collected | Passed | Failed | Skipped |
|---|---|---|---|---|---|
| Gate, containers 18386/18387 | 4a5ac23 (bab7c99 tests) | 404 | 401 | 0 | 3 |
| Verifier, `candidate.py`, Docker | 64b510b | 405 | 404 | 0 | 1 |

- **The counts agree.**
  - Gate has two more skips: the startup-timing and default-port tests that need `candidate.py`. Gate measured both
    directly in item 1.
  - Verifier has one more test: `test_export_import_round_trip_with_deep_ignored_fields`.
- Gate then ran Verifier's new and changed tests at 64b510b on fresh `tk-gate-s1-e48a498` containers (18386/18387):
  `-k "round_trip_with_deep_ignored_fields or nested_ignored"`, **21 passed, 0 failed**.
- Gate's own script for the same pointer (`deep_roundtrip_s1.py`) gave 42/42. The two independent checks agree.
- Verifier did not run the isolated harness or check for no outbound network. Gate's WSL isolated run covers both
  (item 2).

## Verdict basis

Every checklist item has evidence Gate measured on e48a498: a clean no-cache container build, start under 1 s, the
graded isolated harness claiming stage 1, the host harness claiming stage 1, the Verifier suite with 0 failures,
Gate's probe and edge probes with 0 failures, the deep-body export/import round trip, and a fault probe with no
survivors on the current suite. Gaps judged acceptable: none blocking. The open points are the undecided `null`
string case (A-xx, untested by design) and A-44 (out of scope).
