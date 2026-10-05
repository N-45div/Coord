# FACTORY

Four Claude Code seats in one Band Desktop room. One human message per run. The seat that
builds never tests, the seat that tests never reads the code, and only one seat can accept,
on an exact commit, after reproducing the evidence itself.

This run: one dispatch at 21:25 IST, all four tablekeeper stages accepted by 02:44 IST
(5 h 19 m, about 75 min of it a Docker outage), no human message in the room after the
dispatch. The numbers below come from the room log, the git history, Gate's audit records
and `band usage`; the band's own account is [`evidence/reports/final.md`](evidence/reports/final.md).

## The seats

| Seat | Owns | Never | Mandate |
|---|---|---|---|
| **Coordinator** | the requirements ledger, routing, the state of every work item, the final report | writes product code, writes tests, accepts | [mandates/coordinator.md](mandates/coordinator.md) |
| **Builder** | product source, Dockerfile, RUN.md, repairs | reads check sources or the Verifier's suite, accepts its own work | [mandates/builder.md](mandates/builder.md) |
| **Verifier** | an independent black-box suite written from the ledger, run on exact commits | reads product source, accepts | [mandates/verifier.md](mandates/verifier.md) |
| **Gate** | acceptance: rebuilds the exact commit, runs every check, audits the ledger and the code, fault-probes the tests | edits product or suite | [mandates/gate.md](mandates/gate.md) |

All four: Band Desktop headless agents, Claude Code 2.1.289, `claude-opus-5-5`, Claude
subscription auth, Band's default Auto permission mode with Claude's safety checks on.

## How a run flows

```text
human task ─▶ Coordinator ── ledger: numbered obligations, each cited to a spec section ─┐
                  │                                                                     │
                  ├─▶ Builder ─── CANDIDATE <commit> ─────────────┐                      │
                  ├─▶ Verifier ── suite written from the ledger ──┼─▶ Gate ◀─────────────┘
                  │                                               │    │
                  │◀───────────────── RESULTS <commit> ───────────┘    │
                  │◀───────── REJECTED <commit> + minimal reproducer ──┤
                  │◀───────── ACCEPTED <commit> + committed audit ─────┘
                  └─▶ next stage starts as a byte-exact copy of the accepted folder
```

State words are literal in messages (ASSIGNED, CANDIDATE, RESULTS, REJECTED, ACCEPTED,
INCOMPLETE, BLOCKED) and always carry a full commit hash. A new commit voids earlier
evidence for whatever it touches. Handoffs are self-contained: Coordinator pasted the
verbatim task, every specification up to the current stage and the ledger into numbered
parts (stage 1: 7 parts, stage 2: 8, stage 3: 12, stage 4: 14), and every seat
acknowledged every part.

## Design choices, and what they cost

1. **A requirements ledger before any code.** Coordinator turns each spec into numbered
   obligations (105, 42, 51 and 30 for stages 1 to 4) with the section they come from and
   how each is observed, and records every reading of ambiguous text as a decision
   (A-01 to A-47). Tests, rejections and Gate's coverage audit all point at ledger numbers.
   *Why:* the shipped checks are a fraction of the graded ones; the ledger is how the band
   looks for what they never ask. *Cost:* about 6 minutes before stage 1's first handoff.
2. **Builder and Verifier start together, from the same ledger.** Verifier never opens
   product source and derives every expected value from the spec. *Why:* a test written
   after reading the code tests the code. *Cost:* duplicated spec reading, and a suite that
   sometimes misreads the spec: it did, 4 times in stage 2 and 3 in stage 4, each declared
   and fixed in the room. Independence is procedural (the repository is shared), and the
   mandate says so.
3. **Gate is the only acceptance, and it reproduces everything.** Clean no-cache build of
   the exact commit, the organisers' harness in graded isolated mode, the Verifier's suite
   re-run by Gate, its own probes (stage 1: 240, stage 2: 55 plus 83 Playwright UI checks,
   stage 3: 175, stage 4: 91), upgrades from the real earlier images, a line-by-line ledger
   audit and a read of the code that enforces invariants. *Cost:* Gate is the most
   expensive seat (about 38% of the run's estimated spend).
4. **Gate tests the tests.** After a passing baseline, Gate plants one bug per throwaway
   copy and runs the frozen suite. Results: stage 1 8/9 caught, stage 2 8/8, stage 3 7/8,
   stage 4 9/10. Every survivor went back to Verifier as a missing test, reported as
   tuned, never as first-time detection.
5. **Generic mandates; specifics live in one message.** The mandates name no endpoint,
   field or error code (`harness check` and our own scan against both tracks' vocabulary
   are clean). The track, paths, check commands, constraints and hard stop are all in
   [`dispatch.md`](dispatch.md). The same four files ran an unscored rehearsal on a
   different problem before this run.
6. **Every seat commits under its own name**, staging only its own paths: Verifier 20
   commits, Builder 11, Coordinator 12, Gate 9. `git log --format='%an %s'` is the
   division of labour.

## What it caught

| Where | What | How it was caught | What changed |
|---|---|---|---|
| Stage 1, `105337a` | A valid booking with an ignored field nested 1,000–1,600 deep returned 500 (spec §5: no 5xx) | Gate's probe. The shipped checks (Builder's run: 120/120) and Verifier's 377 tests passed | Builder replaced the recursive request fingerprint with an explicit stack and bounded import depth (`e48a498`); Gate re-tested depths 500 to 100,000 |
| Stage 1 fault probe | A rejected import wiped stored retry receipts, and the frozen suite missed it | Gate's planted bug M8 survived | Verifier added the test; M8, M10 and M11 then all caught |
| Stage 2, `ebbb856` | The restaurant list was still loading when the page fired its load event on 2 of 3 loads | Gate measured it after accepting | Coordinator ordered a re-candidate (decision A-46); `a87d4d1` embeds the list, re-accepted |
| Stage 3, `585e646` | Converting a booking into a recurring series reported a later occurrence's 422 instead of the first occurrence's 409 | Gate's probe and Verifier's draft suite, independently | Occupancy checked per occurrence in index order (`0720c48`) |
| Rehearsal | The organisers' harness collects 0 tests in graded isolated mode on native Windows (a backslash test path passed into its Linux runner) | Gate, in the toy rehearsal | Graded runs moved to WSL2, which the participant guide prescribes for Windows |

## Measured cost and time

| Stage | Dispatch → Gate ACCEPTED (IST) | Rejections | Accepted commit | Graded isolated harness |
|---|---|---|---|---|
| 1 | 21:32 → 23:41 (75 min of it the Docker hang) | 1 | `e48a498` | claimed stage 1 (120/120) |
| 2 | 23:47 → 00:23; re-candidate accepted 01:43 | 0 | `a87d4d1` | claimed stage 2 (120/120, 25/25) |
| 3 | 00:27 → 01:44 | 1 | `0720c48` | claimed stage 3 (120/120, 25/25, 7/7) |
| 4 | 01:47 → 02:44 | 0 | `7ad0f29` | claimed stage 4 (suites 1–4 pass) |

Independent tests at the end: 404 (stage 1), 492 (stage 2), 598 (stage 3), 679 (stage 4).
Ledger coverage: 105/105, 42/42, 51/51, 30/30.

Model use, from `band usage rooms` (estimated at list prices, not a bill; the seats ran on a
Claude subscription): **467,990,125 tokens, about $144.73** for this room. Gate $55.28,
Builder $42.39, Verifier $33.38, Coordinator $13.67. Tokens are dominated by cache reads.
The unscored toy rehearsal cost about $9.10.

## Failures and recoveries during the run

- **E-01, 21:59–23:14: the Docker daemon hung.** Gate reported a BLOCKER ("environment,
  not product"); Coordinator froze Docker work, set rules (seat-prefixed container names,
  timeouts on every docker call, one harness run per seat) and polled read-only. Its own
  attempt to restart Docker was refused by its runtime permissions. The operator (a human,
  outside the room) found the cause, the host disk full, and restarted Docker; no message
  was sent to the room. Coordinator detected the recovery and posted DOCKER READY at 23:14.
  The disk was being filled by the host's antivirus web-protection tracing, which wrote a
  133 MB log every few minutes while the seats worked (16 GB in total).
- **E-02:** a port collision voided one Gate run, so each seat got its own port range.
- **E-03, about 01:52–01:58: Docker Desktop and the WSL VMs stopped.** The operator started
  Docker Desktop again; every interrupted run was voided and repeated, and Coordinator
  added a load rule (at most 5 containers per seat, one harness run on the machine at a
  time). E-04 turned out to be a misattribution of the same event.
- Every interrupted check was rerun on the exact commit; no acceptance relied on a run that
  overlapped an outage.

## What we tried that failed

- Bare-context seats (to keep the operator's personal Claude Code instructions out of them)
  cannot use a Claude subscription. Seats run in `local_config` mode instead, and the
  operator's global CLAUDE.md is excluded with `claudeMdExcludes` in the seats' working
  directory ([`factory/claude-settings.local.json`](factory/claude-settings.local.json)).
- Band Desktop launches the `claude` found on PATH; an old global install failed the first
  rehearsal turn with a model-version error. Update Claude Code before creating seats.
- Creating seats with every permission check disabled was refused by the operator's own
  agent's safety check; we kept Band's default Auto mode and set Band's "Human approval
  wait" to auto-deny after 5 minutes, so nothing can stall on a human overnight.
- In rehearsal, seats took up to 18 minutes to acknowledge a handoff because a busy seat
  only reads new messages when its turn ends. Coordinator's handoffs ask for an
  acknowledgement but tell receivers to proceed without waiting for a reply, and Builder
  and Verifier never wait for each other, which kept the real run moving.

## Known gaps

From the band's final report: `null` `starts_at_local` is untested because the spec does
not decide between 400 and 422; pre-1893 local-mean-time offsets are rendered in UTC; four
low-risk readings (A-09, A-13, A-16, A-19) are untested by ledger decision; visual quality
and contrast were judged from screenshots, not measured; the planner returns
`planning_limit` beyond 6 tables, 4 pairs or 6 considered bookings, as the spec allows. The
organisers' held-back tests were not available, so green shipped checks are not proof of
the hidden suites.

## Stand it up yourself

1. Install Band Desktop, sign in, and enable the Claude Code integration. Update Claude Code.
2. Settings → Runtime: **Human approval wait** = auto-deny (we used 5 minutes); question
   timeout 300 s. A dark run must never wait on a human.
3. Create four headless Claude Code agents named Coordinator, Builder, Verifier and Gate,
   each with its file from `mandates/` as its role. We used
   [`factory/create-seats.ps1`](factory/create-seats.ps1) (`band agent create … --transport
   claude-code-cli --runtime-model claude-opus-5-5 --instructions-file mandates/<seat>.md`);
   give each a distinct `--session`.
4. Create a room with the four seats and an empty result repository with the mandates
   committed. Paste one task message to Coordinator naming: the specifications, the result
   repository, path ownership, the check commands, constraints and a hard stop (ours:
   [`dispatch.md`](dispatch.md)).
5. Do not type in the room again until Coordinator's final report.
