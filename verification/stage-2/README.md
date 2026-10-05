# Tablekeeper stage-2 verifier suite (independent, black-box)

Owner: Verifier. Expected values come only from `kickoff/tablekeeper/spec/stage-1.md`, `stage-2.md` and
the stage-1 and stage-2 sections of `evidence/ledger/ledger.md`. The product is reached only over HTTP and
through Chromium (Playwright). No product source and no harness test file was read to write this suite.

Every stage-1 requirement stays in force, so the stage-1 tests are carried over. Their reservation-shape
assertion (`tk.assert_res`) now also enforces stage-2 S2-035: `table_ids` always present, and `table_id`
present exactly when the set has one member.

## Run against a running service (one command; Verifier ports are 18200-18299, ledger E-02)

```sh
py -3.12 verification/stage-2/run.py --base-url http://127.0.0.1:18282
```

On first use this creates `verification/stage-2/.venv` from the pinned `requirements.txt` and installs
Playwright's Chromium. Optional environment variables:

- `TK_STAGE1_BASE_URL`: the accepted stage-1 service, used by the upgrade tests in `test_21_upgrade.py`.
- `TK_SCREENSHOT_DIR`: where to save the UI screenshots used for product review.
- `--second-base-url`: a second fresh instance, used for the cross-instance import test.

## Run against an exact commit

```sh
py -3.12 verification/stage-2/candidate.py <commit> --with-stage1 <accepted stage-1 commit>
# Docker outage fallback:
py -3.12 verification/stage-2/candidate.py <commit> --with-stage1 <s1> --native "python -m tablekeeper" --native-pip "tzdata==2025.3"
```

## New in stage 2

| File | Area | Ledger |
|---|---|---|
| `test_15_nested_ignored.py` | deeply nested ignored fields never 5xx. Tuned after Gate's stage-1 D1; this is not first-time detection | S1-006, S1-011 |
| `test_20_combined.py` | `available_options`, `table_ids` create/PATCH/cancel/moves, A-20 precedence, seeds, replay, export, races | S2-030..S2-042, A-20, A-22 |
| `test_21_upgrade.py` | stage-1 export into stage 2: tokens, receipts (original stage-1 bodies), occupancy, references | S2-026, A-23 |
| `test_30_browser.py` | routes, assets, auth UI, grid vs API, combination cells, booking, resubmission, 409, lost response and retry, out-of-order searches, lookup, 375 px, keyboard, labels, distinct states, upgrade with a pending retry | S2-001..S2-029, A-21, A-24..A-26 |

`COVERAGE.md` maps every stage-1 and stage-2 ledger item to its tests. Product quality (S2-022) and
colour contrast are judged from screenshots, not by assertion.
