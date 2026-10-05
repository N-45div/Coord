@ndivij2004/coordinator This is the band's task. It is the only message a human will send in this room. Run all four stages to the end, coordinating @ndivij2004/builder, @ndivij2004/verifier and @ndivij2004/gate, and do not ask me anything.

ROSTER (use these literal handles): @ndivij2004/coordinator (Coordinator), @ndivij2004/builder (Builder), @ndivij2004/verifier (Verifier), @ndivij2004/gate (Gate).

WHAT TO BUILD
Track: tablekeeper, a clean-room restaurant reservation service. Build it in four stages, in order. Each stage's specification is authoritative and complete; read it in full and paste it in full into every handoff:
  1. C:/Users/DivijN/dark-factory/kickoff/tablekeeper/spec/stage-1.md
  2. C:/Users/DivijN/dark-factory/kickoff/tablekeeper/spec/stage-2.md
  3. C:/Users/DivijN/dark-factory/kickoff/tablekeeper/spec/stage-3.md
  4. C:/Users/DivijN/dark-factory/kickoff/tablekeeper/spec/stage-4.md
Build from these requirements only. Do not use source code, API docs or schemas from existing products in this domain.

RESULT REPOSITORY (the only place anyone commits): C:/Users/DivijN/dark-factory/band-work/result
- stage-1/ to stage-4/: each one is a complete, buildable service with its own Dockerfile, RUN.md and source. It holds the solution to its own stage, not a later one, and must still pass every earlier stage.
- Start stage-N+1/ as a copy of the accepted stage-N/ (no nested .git), then extend the copy. Never change an accepted stage folder again.
- Paths and owners: Builder owns stage-N/. Verifier owns verification/stage-N/ (the independent suite and its coverage table). Gate owns evidence/gate/. Coordinator owns evidence/ledger/ and evidence/reports/. Nobody edits mandates/, README.md or FACTORY.md, and nobody writes anything into the kickoff package.
- Commit under your own seat name, staging only your own paths explicitly: git -c user.name="<Seat>" -c user.email="<seat>@band.local" commit ... Never amend, rebase, squash or force anything.
- Scratch space outside the repository: C:/Users/DivijN/dark-factory/band-work/scratch/<seat>/

EXTERNAL CHECKS (the organizers' harness; any seat may run it, and Gate runs it for acceptance)
- Graded (isolated) mode must run from WSL. On native Windows the harness passes backslash test paths into its Linux runner and collects zero tests, so a native-Windows isolated run proves nothing:
  wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /mnt/c/Users/DivijN/dark-factory/kickoff && ~/harness-venv/bin/python -m harness run --track tablekeeper --repo /mnt/c/<repo-or-worktree path> --stage N --mode isolated --out /mnt/c/Users/DivijN/dark-factory/band-work/checks/<new-unique-name>'
- Faster host-mode runs while iterating work from Windows directly:
  cd C:/Users/DivijN/dark-factory/kickoff && .venv/Scripts/python.exe -m harness run --track tablekeeper --repo <repo> --stage N --out C:/Users/DivijN/dark-factory/band-work/checks/<new-unique-name>
- To check an exact commit, export it first: git -C C:/Users/DivijN/dark-factory/band-work/result worktree add --detach C:/Users/DivijN/dark-factory/band-work/scratch/<seat>/<short-sha> <commit>, then use that path as <repo>.
- --mode isolated means no outbound network, 2 vCPU and 2 GiB, the way judging runs it. Every --out directory must be new.
- A correct stage-N/ prints "claimed stage: N". A failing line for the stage after N is expected and correct.
- These checks ship only part of each stage's tests; the rest are held back and every one of them is written in the specification. A green run is not evidence that a stage is done. Do not copy, adapt or read the shipped test files to drive the product: build to the specification. Treat any failing check as a pointer into the specification.

CONSTRAINTS
- The stack is the band's choice. The image must build with docker build, start healthy within 60 s, serve 50 concurrent requests within 2 vCPU and 2 GiB, and run with no outbound network: every dependency, font, script and stylesheet ships in the image.
- The stage-2 browser product is judged on its own merits (coherent, presentation-ready, responsive at 375 px, keyboard-usable, distinct states) over maintainable code.
- Host: all seats run on the same Windows machine with Git Bash, git, docker and Python 3.12 (py -3.12). Use forward-slash absolute paths.
- Measure as you go: record wall-clock times per stage. Run `C:/Users/DivijN/AppData/Local/Band/band.exe usage` at the end for token usage and estimated cost, and put the output in the final report.

TIME
Dispatched Mon 5 Oct 2026 21:25 IST. Hard stop for the final report: Tue 6 Oct 2026 08:30 IST. If a stage is not accepted by then, stop, keep every accepted stage folder intact, delete nothing, and report that stage INCOMPLETE with its outstanding requirements. Submit only stages Gate accepted.

DONE
Every stage folder Gate accepted is committed, and Gate's acceptance for each names the exact commit. evidence/reports/final.md is committed, and your final report, mentioning every seat, is posted here.
