# Gate addendum: stage-4 fault-probe survivor M62 re-tested against Verifier's tuned test

- Accepted candidate (unchanged): `7ad0f2981a9716ccb5167bb14d7ef25afbc84eb0` (audit `a01c994`). This addendum does not change the verdict.
- Suite: `verification/stage-4` at `b220403` ("TUNED stage-4 test after Gate fault probe M62"). The test was tuned after the probe; it is not a first-time detection.
- Mutant M62 (from `audit-7ad0f29.md`, fault-probe table): the planner uses the restaurant's current table capacities instead of each considered booking's own `accepted_terms.capacities`.

## Measured (native, Gate ports, listener PIDs checked before and after each run)

Both tests are in `test_50_replan.py`. Command: `py -3.12 <suite>/run.py --base-url http://127.0.0.1:P1 --second-base-url http://127.0.0.1:P2 -p no:cacheprovider -q -rf <the two tests>`

| Target | Ports | `test_planner_uses_accepted_capacities_that_differ_from_fixture` | `test_capacity_under_each_bookings_own_accepted_terms` | Result line |
|---|---|---|---|---|
| M62 mutant | 18362/18382 | **FAILED**: got `['r_4']`, expected `['r_6']` | passed | `1 failed, 1 passed in 1.79s` |
| 7ad0f29 (unmutated) | 18390/18391 | passed | passed | `2 passed in 1.49s` |

Logs: `logs-7ad0f29/m62-retest/`.

## Outcome

- M62 is now detected by the frozen suite at `b220403`.
- Stage-4 fault-probe tally for the suite: 10/10 with the tuned test. It was 9/10 at the time of acceptance.
- No product change. The stage-4 folder at HEAD still equals `7ad0f29:stage-4`.
