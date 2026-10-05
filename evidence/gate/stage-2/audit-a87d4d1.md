# Gate audit: stage-2 re-candidate a87d4d1c87081338d435429761a58d640cae3178 (A-46/A-47)

- **Verdict: ACCEPTED a87d4d1c87081338d435429761a58d640cae3178.** It supersedes ebbb856 as the accepted stage 2.
- **Base:** ACCEPTED ebbb856 (audit `audit-ebbb856.md`). This re-candidate supersedes it once accepted. Until then
  ebbb856 stands.
- **Scope of the change:**
  - `git show a87d4d1` touches only `stage-2/` (RUN.md, api.py, server.py, ui.py, static/index.html, static/app.js).
  - Ignoring CR line endings, the content diff against ebbb856 is +45/−8. RUN.md and app.js were also re-saved with
    a line-ending change.
  - `stage-1/` is unchanged.
  - `ui.py` and `static/index.html` are byte-identical to `585e646:stage-3` (blob hashes 98dba8d and b972f6e).
- **Audited:** 2026-10-06 00:40 to 01:08 IST, in the clean worktree `scratch/gate/a87d4d1`. Image
  `tk-gate-s2-a87d4d1` (no-cache build). Gate ports 18370-18393.

## Diff review

- **`ui.screen(restaurants)`** embeds the current `GET /restaurants` list as
  `<script type="application/json" id="restaurants-data">`.
  - `<` is escaped as `<`, so a name cannot close the script element.
  - A JSON data block is not executed, so it is compatible with CSP `script-src 'self'`.
  - `Api.restaurant_summaries` reads the list under the store lock.
- **`app.js`:**
  - `search.restaurants` is seeded from the block, and `loadRestaurants()` still refreshes it.
  - `showConfirmation()` scrolls the new confirmation into view.
  - The empty-day text is changed. Nothing else changed.

## Results (all measured on this commit)

| Check | Result |
|---|---|
| No-cache build + start, `--cpus 2 --memory 2g` | healthy in 847 ms (PORT=8080), 1354 ms (PORT unset → 8080), 1219 ms (PORT=9123) |
| WSL isolated `--stage 2` | stage 1 120/120, stage 2 25/25, stage 3 fail (overshoot) → **claimed stage: 2** |
| WSL isolated `--stage 1` | **claimed stage: 1** (120/120) |
| Verifier stage-2 suite f574735 (full, includes A-46 test and stage-1 tests) | **490 passed, 0 failed, 3 skipped** (the same 3 skips as before) |
| Gate `probe_s1` / `probe_s2` / `upgrade_s2` / `ui_s2` | 240/0, 55/0, 18/0, 83/0 |
| Gate `a46_s2.py` | **7/0** |
| Polish: 375 px confirmation | after booking, the confirmation box sits at y = 457 to 814 in an 812 px viewport, i.e. in view (`screens/confirmation-viewport-375.png`) |
| Polish: empty day | reads "Party of 2 · no bookable times on this day" (`screens/no-slots-1280.png`) |

What `a46_s2.py` established:
- 10/10 page loads show the options exactly as the restaurant ids at the load event.
- With the client's `GET /restaurants` *held back*, the options at load are still the ids. This is the deterministic
  form of the check.
- A hostile restaurant name (`</script><img onerror=…>`) renders as text, with no injected element and no page
  error.
- The embedded list follows a reset.

## Fault probe (embed)

| Mutant | Frozen Verifier suite (f574735 `test_30_browser.py`) | Gate `a46_s2.py` |
|---|---|---|
| M30: embed removed (shell served without the data block) | **survived**, 37 passed. The A-46 test is timing-dependent: natively the client fetch finishes before `load` | **DETECTED** by the held-back check (options `['']` at load) |
| M31: `<` not escaped in the data block | **survived**, 37 passed. No hostile-name test | **DETECTED** (injected `<img>` present) |

The two survivors are coverage gaps for Verifier: a deterministic A-46 test, and a hostile-name test. Gate sends
them after Verifier's first RESULTS for this commit, as the mandate requires.

## Ledger

- S2-001..S2-042 and S1-001..S1-105 are re-evidenced on this commit: Gate probes, the Verifier stage-2 suite, and
  the isolated harness.
- A-46 is met (deterministic check above).
- S2-022..S2-025: the judgement from the ebbb856 audit stands. The only visible changes are the two polish fixes,
  both verified.

## Verifier report comparison

Verifier's RESULTS for a87d4d1 (room message a5cabcf8) were run in Docker from a clean worktree.

| Suite | Verifier | Gate |
|---|---|---|
| Stage-2 suite 869224e (tests identical to f574735) | 492 passed, 0 failed, 1 skipped (incl. the A-46 at-load test) | 490 passed, 0 failed, 3 skipped |
| Stage-1 suite 64b510b against the stage-2 build | 404 passed, 0 failed, 1 skipped | (stage-1 modules are inside the stage-2 suite) |

- **The counts agree.** Gate's two extra skips are the `candidate.py`-only startup tests; Gate measured startup
  directly.
- **Coverage gaps sent to Verifier after this report:** M30 and M31 from the fault probe above, i.e. a
  deterministic A-46 test with the API held back, and a hostile-name test.

## Gaps judged acceptable (none blocking)

- A null `starts_at_local` is undecided by the spec.
- A-44 is out of scope.
