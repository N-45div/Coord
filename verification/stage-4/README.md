# Tablekeeper stage-4 verifier suite (independent, black-box)

Owner: Verifier. Expected values come only from `kickoff/tablekeeper/spec/stage-1.md` .. `stage-4.md` and
the ledger (`evidence/ledger/ledger.md`). The product is reached only over HTTP and through Chromium. No
product source and no harness test file was read to write this suite.

Optimal seating plans are checked against `tk.plan_oracle`. It is an independent brute-force
implementation of the stage-4 feasibility rules and the three-level objective: bookings moved, then
unused seats, then option ranks in reference order. Its input is the bookings as the API reports them.

## Run

```sh
py -3.12 verification/stage-4/run.py --base-url http://127.0.0.1:18282
py -3.12 verification/stage-4/candidate.py <commit> --with-stage1 <s1> --with-stage2 <s2> --with-stage3 <s3>
```

## New in stage 4

| File | Area | Ledger |
|---|---|---|
| `test_50_replan.py` | previews checked against the oracle (fixed and 10 seeded random scenarios), own-terms capacity, no-feasible, planning limit, preview has no effects, validation, permissions, restaurant revision accounting | S4-001..S4-010, A-35, A-36, A-38, A-39 |
| `test_51_apply.py` | application, reassigned history, closure effects (availability, explain, create, PATCH), idempotency, already applied, stale plans, other restaurants, concurrent applies, series occurrences, export/import, screens | S4-011..S4-020, A-37, A-42 |
| `test_52_series_amend.py` | eligible occurrences, no-ops, validation, stale revision, replay, occupancy, index-order precedence, resulting-date policy, DST gap, concurrency, closures, replan-moved tables, accepted cutoff on the real clock | S4-021..S4-029, A-40, A-41 |
| `test_53_upgrade.py` | stage-1..3 exports into stage 4: retries, series amend, replan and apply on imported data | S4-030 |
