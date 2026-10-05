# Tablekeeper stage-1 verifier suite (independent, black-box)

Owner: Verifier. Expected values come only from `kickoff/tablekeeper/spec/stage-1.md` and the
stage-1 section of `evidence/ledger/ledger.md` (S1-001..S1-105, A-01..A-19). The product is reached
only over HTTP. No product source and no harness test file was read to write this suite.

## Run against a running service (one command)

```sh
py -3.12 verification/stage-1/run.py --base-url http://localhost:18082
```

`run.py` creates `verification/stage-1/.venv` (or `$TK_VERIFIER_VENV`) from the pinned
`requirements.txt` on first use, then runs pytest. Extra arguments go to pytest, for example
`-k moves`, `-x` or `--junitxml out.xml`. Use `--second-base-url <url>` to point at a second fresh
container for the cross-container import test.

## Run against an exact commit (clean worktree build)

```sh
py -3.12 verification/stage-1/candidate.py <commit> [--port 18082] [--second-port 18092]
```

This adds a detached worktree at `scratch/verifier/<short-sha>`, `docker build`s `stage-1/`
(tag `tk-verifier-s1-<short>`) and starts it with `--cpus 2 --memory 2g -e PORT=9137 -p 18082:9137`. A
second container starts with PORT unset on `18092:8080`. It times the first healthy `/health`, runs
the suite and writes `pytest.txt`, `junit.xml`, container logs and `summary.json` to
`scratch/verifier/results/<short>-s1-<timestamp>/`.

## Layout

| File | Area | Main ledger items |
|---|---|---|
| `test_01_concurrency.py` | 50-way parallel creates, replays, PATCH/move/create races, snapshot consistency, signup race | S1-005/006, S1-045, S1-067, S1-080, S1-105 |
| `test_02_idempotency.py` | missing/long keys, replay, reuse, per-user scope, per-path scope, failed keys | S1-037..S1-046 |
| `test_03_moves.py` | shape, 404/422/409 rules, swaps/chains, atomic rollback, precedence in input order, replay | S1-093..S1-105, A-12 |
| `test_04_dst.py` | Berlin/New York spring and fall transitions, absolute durations, closing time in absolute time | S1-081..S1-084, A-08 |
| `test_05_export_import.py` | round trip, replacement, snapshot semantics, invalid imports, second container | S1-085..S1-092 |
| `test_06_precedence.py` | request-level and rule precedence for create, PATCH, cancel, availability | A-01, A-02, A-04, A-05, A-11 |
| `test_07_cutoff.py` | cutoff against the real clock, including a boundary crossing (~1-2 min wait) | S1-071/072/076, A-03 |
| `test_10_runtime.py` | health, reset, content type, unknown routes, unknown fields, 64-char ids, garbage input | S1-001..S1-012, S1-019, S1-026 |
| `test_11_auth.py` | signup, login, validation, bearer enforcement, multiple tokens | S1-027..S1-036 |
| `test_12_restaurants_availability.py` | restaurants, slot grid, capacity filter, query validation | S1-047..S1-054 |
| `test_13_create.py` | create shape, references, overlap, grid, hours, capacity, field validation | S1-055..S1-067 |
| `test_14_read_cancel_amend.py` | list order, get, cancel, PATCH | S1-068..S1-079 |

`COVERAGE.md` maps every stage-1 ledger item to its tests. Regenerate it with
`.venv/Scripts/python.exe gen_coverage.py` after changing markers.

Tests tagged with an `A-xx` id check a Coordinator decision from the ledger, not literal spec text.
`test_unusual_characters_in_fixture_ids[slash-strict-reading]` checks the strict reading of S1-012
(any character, including `/`, in a fixture id used in a path).
