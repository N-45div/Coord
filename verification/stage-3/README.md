# Tablekeeper stage-3 verifier suite (independent, black-box)

Owner: Verifier. Expected values come only from `kickoff/tablekeeper/spec/stage-1.md`, `stage-2.md`,
`stage-3.md` and the stage-1..3 sections and recorded decisions of `evidence/ledger/ledger.md`. The
product is reached only over HTTP and through Chromium (Playwright). No product source and no harness
test file was read to write this suite.

Every stage-1 and stage-2 requirement stays in force, so those tests are carried over. Their
reservation-shape assertion now also requires stage-3's `revision` and `accepted_terms` (S3-023).

## Run against a running service (one command; Verifier ports are 18200-18299, ledger E-02)

```sh
py -3.12 verification/stage-3/run.py --base-url http://127.0.0.1:18282
```

## Run against an exact commit

```sh
py -3.12 verification/stage-3/candidate.py <commit> --with-stage1 <accepted stage-1> --with-stage2 <accepted stage-2>
```

The accepted stage-1 and stage-2 builds start on 18262 and 18272. They are the export sources for the
upgrade tests (`test_21_upgrade.py`, `test_45_upgrade.py`).

## New in stage 3

| File | Area | Ledger |
|---|---|---|
| `test_40_explain.py` | `explain=true` values, shape, rule order, consistency, closed days, policy versions | S3-001..S3-006 |
| `test_41_history.py` | created, changed, no-op, cancelled, replay; owner-only 404 even without a token; decision; pair history; terms per entry; seeded bookings | S3-007..S3-013, S3-024, S3-032, S3-033, S3-047, A-43 |
| `test_42_policies.py` | permissions, versions, idempotency, validation, selection by local date, capacities, publication never edits bookings, amendment against the resulting date, expected_revision, concurrent stale revisions, accepted cutoff on the real clock | S3-014..S3-031, A-27..A-29, A-34 |
| `test_43_series.py` | adoption, intervals, pairs, per-occurrence policy, all-or-nothing, index-order errors, DST, validation, anchor rules, owner-only GET, exceptions and revisions, replay, export/import | S3-034..S3-046, S3-051, A-30, A-33 |
| `test_44_moves_policies.py` | batch moves under policies: resulting-date policy, per-move expected_revision, failures, replays, series occurrences | S3-048..S3-050 |
| `test_45_upgrade.py` | stage-1 and stage-2 exports into stage 3, synthesised history, original receipts, adoption after import | S3-046, A-31 |
