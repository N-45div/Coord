# Tablekeeper — final report (Coordinator)

Task dispatched by the human: Mon 5 Oct 2026 21:25 IST (the only human input).
Report written: Tue 6 Oct 2026 02:50 IST. Hard stop: Tue 6 Oct 2026 08:30 IST.
Repository: `C:/Users/DivijN/dark-factory/band-work/result`. Ledger: `evidence/ledger/ledger.md`
(final commit a4c5a27). Gate audit records: `evidence/gate/stage-N/`. Verifier suites and
coverage tables: `verification/stage-N/`. Coordinator timeline: `scratch/coordinator/tk/timeline.txt`
(outside the repository).

## Outcome

| Stage | Accepted commit | Gate audit record | Rejections | Dispatch → acceptance |
|---|---|---|---|---|
| 1 | `e48a498f699eb9f7dd4f5c08f1092b7821e69aef` | `7191654` `evidence/gate/stage-1/audit-e48a498.md` | 1 (105337a) | 21:32 → 23:41 (2h09m; 2h16m from the human's 21:25 dispatch). 75 min of it was the E-01 Docker hang. |
| 2 | `a87d4d1c87081338d435429761a58d640cae3178` (supersedes the first acceptance, ebbb856) | `8475e64` `evidence/gate/stage-2/audit-a87d4d1.md` (first: `049f0b3` `audit-ebbb856.md`) | 0 | 23:47 → 00:23 for ebbb856 (36 min); A-46 re-candidate accepted 01:43 (1h56m from stage dispatch; the re-candidate waited in Gate's queue alongside stage 3) |
| 3 | `0720c488269f26d60b6e4b640c9253a17c4de86a` | `809ba9e` `evidence/gate/stage-3/audit-0720c48.md` | 1 (585e646) | 00:27 → 01:44 (1h17m) |
| 4 | `7ad0f2981a9716ccb5167bb14d7ef25afbc84eb0` | `a01c994` `evidence/gate/stage-4/audit-7ad0f29.md` | 0 | 01:47 → 02:44 (57 min) |

Every accepted folder holds only its own stage: each Gate isolated run of stage-N claimed stage N, and the stage N+1
probe failed as expected. Accepted folders were never modified after acceptance (checked with `git diff --quiet` at
each later candidate).

## Per-stage evidence (Gate, measured on the exact commit, in containers at 2 vCPU / 2 GiB)

### Stage 1 — ACCEPTED e48a498
- Clean no-cache build (46.1 MB). Healthy in 545 ms (PORT=8080), 686 ms (PORT unset → 8080), 766 ms (PORT=9123).
- Organizers' harness, graded isolated mode via WSL: stage 1 pass 120/120, "claimed stage: 1 on the shipped checks"; stage-2 probe fails as expected. Host mode: 120/120.
- Verifier suite (Gate's run): 401 passed, 0 failed, 3 skipped. Verifier's own run (suite 64b510b, Docker): 404 passed, 0 failed, 1 skipped.
- Gate probe 240/0; deep-nesting edge probe with no 5xx from depth 500 to 100000; deep export/import round trip into a fresh container 42/0.
- Ledger: 105/105 stage-1 items with evidence.
- Fault probe: on the frozen suite at 105337a, 8/9 planted defects detected. The survivor M8 (a rejected import wipes receipts) was sent to Verifier, who added a tuned test (bab7c99). On e48a498, M8, M10 and M11 were all detected; no survivors.
- **Rejection REJECTED 105337a (D1, S1-006/S1-011, §5 and §3.4):** a valid body with an ignored field nested 1000–1600 deep gave 500, because the idempotency fingerprint recursed past Python's recursion limit. Fix e48a498: explicit-stack fingerprint with byte-identical canonical text; a sibling sweep found no other recursion over request JSON. Builder had also self-rejected an earlier commit (fc76163: it capped the fixture cutoff, failing 2 shipped checks) before declaring 105337a.

### Stage 2 — ACCEPTED a87d4d1
- First accepted at ebbb856 (00:23). After Gate measured that `restaurant-select` still showed only a "Loading restaurants…" option at the load event on 2 of 3 page loads, Coordinator ordered a re-candidate (A-46). Its only change is that the page shell embeds the restaurant list, plus Gate's two polish notes. Accepted at a87d4d1, which supersedes ebbb856.
- Clean build; healthy in 0.85 s / 1.35 s / 1.22 s. WSL isolated --stage 2: 120/120 and 25/25, "claimed stage: 2"; --stage 1 claimed 1.
- Verifier suites: Gate's run 490/0/3. Verifier's runs: stage-2 suite 492/0/1, stage-1 suite on the stage-2 build 404/0/1.
- Gate probes: s1 240/0, s2 combined tables 55/0, upgrade from the real stage-1 image 18/0, Playwright UI at 1280 and 375 px 83/0, A-46 7/0 (10/10 loads; held-back fetch; hostile name rendered as text).
- Product judgement (S2-022..S2-025, 21 screenshots): warm and coherent; pairs read as "Window 1 + Booth 2 · Seats 6 · joined"; available, unavailable, selected, loading, success, refused and uncertain states are distinct; no horizontal scroll at 375 px; visible focus; keyboard-operable.
- Fault probe: ebbb856 8/8 (frozen suite and Gate); a87d4d1 embed mutants 2/2 detected by Gate but 0/2 by the frozen suite. Verifier closed both gaps as tuned tests (61a1e4b).
- Rejections: none. Verifier's suite had 4 defects of its own (it required `table_id` on pairs; it read the select before load). Verifier fixed and declared them (c9e88ab, 1aecf08).

### Stage 3 — ACCEPTED 0720c48
- Clean build; healthy in 0.83 s / 0.97 s / 0.39 s. WSL isolated --stage 3: 120/120, 25/25 and 7/7, "claimed stage: 3"; --stage 2 and --stage 1 claimed.
- Verifier suites: Gate's run 595/0/3; Verifier's run 597/0/1.
- Gate probes: s3 175/0 (explain, history, policies, terms, revisions, a 10-way expected_revision race, decision, series, moves under policies); upgrade from real stage-1 and stage-2 images 26/0; s1 240/0, s2 55/0, ui 83/0, A-46 7/0.
- Ledger: S3 51/51, S2 42/42, S1 105/105. Fault probe: 8 planted, frozen suite 7/8, Gate 8/8. The survivor (A-31 imported cancelled booking at revision 2) was closed by Verifier as a tuned test.
- **Rejection REJECTED 585e646 (D1, S3-039/A-30):** series adoption judged occupancy after every occurrence's rules, so a later occurrence's 422 outside_opening_hours beat an earlier occurrence's 409 table_unavailable. Gate's probe and Verifier's draft suite both found it independently. Fix 0720c48: occupancy is checked per occurrence in index order, still all-or-nothing. Coordinator scoped the fix to adoption only; moves and series amend keep their spec'd order.
- Gate's accepted gap: the restaurant revision was verified by code reading only, because the stage-3 API does not expose it. It is tested end to end in stage 4.

### Stage 4 — ACCEPTED 7ad0f29
- Lineage: ee33b9b:stage-4 equals 0720c48:stage-3; at 7ad0f29, stage-1/2/3 equal their accepted commits.
- Clean build; healthy in 0.65 s / 1.36 s / 1.48 s. WSL isolated --stage 4 claimed 4 (stages 1–4 pass), with --stage 3, 2 and 1 claimed on the same worktree (stage 3 re-run after the E-03/E-04 events, claimed again).
- Verifier suites: Gate's run 673/3/3; Verifier's run 675/3/1 at 61a1e4b. The 3 failures were Verifier's own misreadings (a booking ending after closing; an infeasible plan scenario), fixed in 31be4e8, where the stage-4 modules pass 79/0 in both seats' runs.
- Gate probes: probe_s4 91/0. Plans equal Gate's independent brute-force oracle (own accepted terms, rank tie-break, unused seats beating rank); restaurant revision (S4-010) checked end to end on every write type; apply with stale, already-applied, replay and 6 concurrent applies → exactly 1×201, reassigned history; closures enforced in availability, pairs, explain, create and PATCH; series amend with 6 concurrent → 1×201. Upgrade from real stage-1/2/3 images 17/0. UI for S4-020 at 1280 and 375 px 12/0. Regression: s3 175/0, s2 55/0, s1 240/0, ui 83/0, A-46 7/0.
- Verifier's independent planning oracle agreed with the product on 4 hand-built and 10 seeded random scenarios. Builder's own oracle run found 0 mismatches across 150 random restaurants.
- Ledger: S4 30/30, S3 51/51, S2 42/42, S1 105/105. Fault probe: 10 planted defects; frozen suite 9/10, Gate 9/10, each survivor caught by the other. M62 (planner using fixture rather than accepted capacities) was sent to Verifier as a missing test.
- Rejections: none.

## Rejections and what they changed (all stages)
1. Stage 1, 105337a → e48a498: a recursive fingerprint caused 5xx on deep JSON; it became an explicit stack (same canonical text), and imports gained a depth bound validated before the swap.
2. Stage 3, 585e646 → 0720c48: the series adoption error order became per occurrence in index order.
3. (Decision, not a rejection) Stage 2, ebbb856 → a87d4d1: restaurant options are embedded at load (A-46) to remove a page-load race; plus two polish fixes.
4. Stage 4: no rejections. Verifier's 3 suite misreadings were declared and fixed (31be4e8).

## Environment incidents
- E-01 21:59–23:14 IST: the shared Docker daemon hung. Coordinator's restart attempt was refused by its runtime permissions; no seat restarted Docker on instruction. Docker recovered after a restart outside the band. Seats continued with native runs (preliminary only) and audits.
- E-02: a port collision voided one Gate run, so per-seat port ranges were set (Builder 181xx, Verifier 182xx, Gate 183xx).
- E-03 01:52–01:58 IST and E-04 02:03 IST: Docker Desktop/engine restarts killed every running container. Interrupted runs were voided and rerun. A load rule followed: at most 5 containers per seat, and one harness run on the machine at a time.
- The harness's isolated mode is used only through WSL (A-18); native-Windows isolated runs collect 0 tests.

## Collaboration and handoffs
- Every stage dispatch carried the verbatim task, the verbatim specifications of all stages up to N, and the ledger sections, sent from files in numbered parts with the last one marked FINAL: stage 1 in 7 parts, stage 2 in 8, stage 3 in 12, stage 4 in 14. Every seat ACKed every part.
- Builder drafted stages 2–4 in its scratch space from the specification files during the E-01 outage (permitted as design-ahead reading by the stage-1 dispatch). Each stage-N folder was still first committed as an exact copy of the accepted stage-(N-1) folder, after Gate's ACCEPTED (cb8bd83, 7a7488b, ee33b9b), then extended.
- Review changed things: Gate's two rejections, Gate's measurement that triggered A-46, Coordinator's import round-trip pointer, which became a Verifier test, and Gate's fault-probe survivors, which became Verifier tests. Verifier's own suite defects were declared and fixed openly.
- Coordinator decisions recorded in the ledger: A-01..A-47 (readings of ambiguous spec text, precedence orders, scope rulings) and E-01..E-04 (environment).
- Commits by seat: Verifier 20, Builder 11, Coordinator 11 (before this report), Gate 9.

## Known gaps and requirements nobody verified fully
- `null` `starts_at_local` (400 vs 422): the spec does not decide it, so it is untested by design.
- A-44 pre-1893 local-mean-time offsets: out of scope. The product renders them in UTC.
- A-09 list tie order, A-13 default seeded `created_at`, A-16 `party_size` 4.0, A-19 fixture IDs over 64 characters: not tested, by ledger decision.
- Partly covered by tests (the rest by Gate's code audit or product judgement): S1-036 password hashing (export-has-no-plaintext test plus a code audit of scrypt); S2-002 assets only from the image (a same-origin request test plus CSP 'self'); S2-017 server-authoritative UI (lost-response tests plus a code audit); S2-022..S2-025 visual quality (judged from screenshots, not automatable); colour contrast (judged, not measured).
- The organizers' held-back tests were not available. A green shipped-check run is not proof of the hidden suites.
- planning_limit is returned only beyond 6 tables / 4 pairs / 6 considered bookings (allowed by S4-004); larger inputs are budgeted, not exhaustively solved.
- M62 (accepted-terms capacity in the planner) is caught by Gate's probe; Verifier's suite test for it was still to be added when this report was written.

## Usage
Measured with `C:/Users/DivijN/AppData/Local/Band/band.exe usage` (after `usage refresh`) at 02:48 IST. This run's room is `df07a3f6-10f1-499b-a9fd-f79cf869c1fe`: **467,990,125 tokens, about $144.73 estimated at list prices** (Gate $55.28, Builder $42.39, Verifier $33.38, Coordinator $13.67). Room `194f348c-…` is an earlier rehearsal. The `(no room)` / unattributed rows are other usage on this machine, not attributable to this run. Tokens are dominated by cache reads. Raw output:

```text
$ band.exe usage rooms
Estimated at list prices — not a bill.
ROOM                                    SESSIONS         TOKENS   ESTIMATE  AGENTS
df07a3f6-10f1-499b-a9fd-f79cf869c1fe           4      467990125    $144.73  ndivij2004/verifier $33.38 · ndivij2004/builder $42.39 · ndivij2004/gate $55.28 · ndivij2004/coordinator $13.67
194f348c-5816-4341-8d8b-589ccd7b375c           4       14990722      $9.10  ndivij2004/verifier $1.98 · ndivij2004/builder $1.80 · ndivij2004/gate $3.27 · ndivij2004/coordinator $2.04
(no room)                                    299    31769155152  $24541.23  (unattributed) $24541.23

$ band.exe usage agents
Estimated at list prices — not a bill.
AGENT                     SESSIONS         TOKENS   ESTIMATE  LAST ACTIVITY
ndivij2004/gate                  2      198646135     $58.55  2026-10-05T21:16:22.842Z
ndivij2004/builder               2      140806832     $44.19  2026-10-05T21:16:34.622Z
ndivij2004/verifier              2       99591055     $35.37  2026-10-05T21:10:18.909Z
ndivij2004/coordinator           2       43936825     $15.72  2026-10-05T21:16:38.143Z
(unattributed)                 299    31769155152  $24541.23  2026-10-05T21:13:47.334Z
  token categories (non-additive): reasoning=2888089
TOTAL                          307    32252135999  $24695.06
  token categories (non-additive): reasoning=2888089

$ band.exe usage daily (last 2 rows + total)
Estimated at list prices — not a bill.
DATE                INPUT       OUTPUT  CACHE-WRITE    CACHE-READ   ESTIMATE  MODELS
2026-10-05*         14194      3392462     37404801    2134507810    $711.37  claude-opus-5-5, claude-sonnet-5-5, claude-haiku-4-5-20251001
2026-10-06*          1418       759495      2146879     393637570    $111.10  claude-opus-5-5
TOTAL           142476702    127298904    695393942   31286966451  $24695.14
  pricing: estimated_equivalent USD via usage_import (catalog metadata unavailable)
```

Wall clock: 21:25 IST human dispatch → 02:44 IST fourth acceptance = **5h19m**, of which about 75 min was the E-01 Docker hang.
