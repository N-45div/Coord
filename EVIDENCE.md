# EVIDENCE: every claim, and where to check it

Nothing in our README or video needs to be taken on trust. Each claim below points at the
file or commit that proves it, and the commands at the end reproduce the key results in a
few minutes.

## Claims → evidence

| Claim | Where to check |
|---|---|
| One human message, then none | [`room.json`](room.json): 142 text messages; exactly 1 from the human (the dispatch, verbatim in [`dispatch.md`](dispatch.md)); Coordinator 61, Gate 30, Verifier 26, Builder 24 |
| The work was shared, not carried by one seat | `room.json` tool calls: Gate 465, Builder 391, Verifier 320, Coordinator 188 (1,364 in total). Commits: `git log --format='%an' -- stage-1 stage-2 stage-3 stage-4 verification evidence \| sort \| uniq -c` |
| Mandates frozen before the run, generic | Commit `e2b6783` (the repository's first commit, before the dispatch). `harness check` passes the mandate-vocabulary gate for this track |
| All four stages accepted on exact commits | Gate audits: [`stage-1`](evidence/gate/stage-1/audit-e48a498.md) `e48a498` · [`stage-2`](evidence/gate/stage-2/audit-a87d4d1.md) `a87d4d1` · [`stage-3`](evidence/gate/stage-3/audit-0720c48.md) `0720c48` · [`stage-4`](evidence/gate/stage-4/audit-7ad0f29.md) `7ad0f29` |
| Accepted folders were never changed afterwards | `git diff --quiet <accepted> HEAD -- stage-N` returns 0 for all four (commands below) |
| Each folder claims exactly its own stage, graded isolated mode | Gate's runs in each audit, and the operator's independent re-run from a fresh clone: [`evidence/operator/`](evidence/operator) (`claimed: true`, share 1.0, for stages 1–4) |
| Review changed the code: the nested-JSON 500 | [`audit-105337a.md`](evidence/gate/stage-1/audit-105337a.md) (REJECTED, reproducer, root cause) → fix `e48a498` → [`audit-e48a498.md`](evidence/gate/stage-1/audit-e48a498.md) (no 5xx at depth 500–100,000) |
| Review changed the code: series adoption error order | [`audit-585e646.md`](evidence/gate/stage-3/audit-585e646.md) (REJECTED) → fix `0720c48` |
| Gate tests the tests | [`faultprobe-105337a.md`](evidence/gate/stage-1/faultprobe-105337a.md) (8/9 caught; survivor M8 became a test) and the fault-probe sections of every later audit |
| Requirements ledger and decisions | [`evidence/ledger/ledger.md`](evidence/ledger/ledger.md): 105 / 42 / 51 / 30 obligations for stages 1–4, decisions A-01..A-47, environment incidents E-01..E-04 |
| 2,173 independent tests | [`verification/stage-1`](verification/stage-1) … [`stage-4`](verification/stage-4): 404 / 492 / 598 / 679, each with a coverage table mapping ledger items to tests |
| Time, cost and incidents | [`evidence/reports/final.md`](evidence/reports/final.md) (Coordinator's report, with raw `band usage` output) and [`FACTORY.md`](FACTORY.md) |
| Live demo of the built product | https://coord-site.vercel.app (the real app at `a87d4d1`: a response dropped after commit, "Try again" returns the original reference, the server holds one booking) |

## Reproduce in a few minutes

From a clone of this repository, with the organisers' kickoff package checked out beside it
(`dark-factory-wearedevs/`, harness requirements installed; on Windows run from WSL2):

```sh
# The offline gates: layout, seats, room log, generic mandates, credentials
python -m harness check ../Coord --track tablekeeper

# Every folder builds and claims its own stage in graded isolated mode
python -m harness run --track tablekeeper --repo ../Coord --all --mode isolated

# Accepted folders are byte-identical at HEAD
cd ../Coord
for s in "1 e48a498" "2 a87d4d1" "3 0720c48" "4 7ad0f29"; do set -- $s
  git diff --quiet $2 HEAD -- stage-$1 && echo "stage-$1 = $2"; done

# Who wrote what
git log --format='%an' | sort | uniq -c

# The human said exactly one thing in the room
python -c "import json; r=json.load(open('room.json',encoding='utf-8')); print(sum(1 for m in r['messages'] if m['messageType']=='text' and m['senderType']=='User'))"
```

## Disclosed operator actions (none were messages to the room)

- Docker Desktop was restarted twice when the host's Docker engine stopped (22:10–23:14, cause:
  a full disk; and about 01:52). The band detected both outages itself, paused Docker work,
  and resumed when Docker answered. Details: [`FACTORY.md`](FACTORY.md) and ledger E-01..E-04.
- After the run, the operator committed `README.md`, `FACTORY.md`, this file, `dispatch.md`,
  `factory/`, `room.json` and `evidence/operator/`. Nothing under `stage-N/`, `verification/`
  or the band's `evidence/` folders was written by a human.
