# Coord: Tablekeeper, built by a four-seat dark factory

**Track:** tablekeeper (restaurant reservations) · **Team:** N Divij (solo) ·
**Event:** WeAreDevelopers × BAND, Dark Factory (lablab.ai) · **Demo:** https://coord-site.vercel.app

Four Claude Code seats in one Band Desktop room (Coordinator, Builder, Verifier and Gate)
built this service from one human message, with no human input after it. The seat that
builds never tests, the seat that tests never reads the code, and only Gate accepts, on an
exact commit, after reproducing every check itself.

**Result:** all four stages accepted by Gate in 5 h 19 m. Every stage folder claims its own
stage in the organisers' graded isolated mode. The band wrote 2,173 independent tests
(404, 492, 598 and 679 per stage), rejected two candidates for real defects the shipped
checks never caught, and cost about $145 at list prices.

## How to read this repository

| Path | What it is |
|---|---|
| [`FACTORY.md`](FACTORY.md) | The factory: seats, flow, design choices and their cost, measured time and spend, what it caught, how to stand it up |
| [`mandates/`](mandates) | The four seats' standing instructions. Generic: no track names, endpoints, fields or error codes. Committed before the run |
| [`dispatch.md`](dispatch.md) | The one human message that started the run, verbatim |
| [`room.json`](room.json) | The full Band room, downloaded unchanged: every handoff, rejection, acceptance and tool call |
| `stage-1/` to `stage-4/` | One complete, buildable service per stage (Dockerfile, RUN.md, source), each a copy of the previous accepted stage, extended |
| [`evidence/ledger/`](evidence/ledger) | Coordinator's numbered requirements ledger and every recorded decision |
| [`verification/`](verification) | Verifier's black-box suites and coverage tables, written from the ledger without reading product code |
| [`evidence/gate/`](evidence/gate) | Gate's audit record for every verdict, with its probes and fault-probe results |
| [`evidence/reports/final.md`](evidence/reports/final.md) | Coordinator's final report |
| [`factory/`](factory) | The script that created the seats and the seats' Claude Code settings |

## Run a stage

Each folder's `RUN.md` has the exact commands. For the final stage:

```sh
docker build -t tablekeeper-s4 stage-4
docker run --rm -p 8080:8080 -e PORT=8080 tablekeeper-s4
# open http://localhost:8080/
```

The service is Python 3.12's standard library plus a pinned timezone database: no web
framework, nothing fetched at run time. State starts empty; seed it with
`POST /_test/reset` and a fixture as described in the specification.

## Who did what

Every commit under `stage-N/`, `verification/` and `evidence/` was made by a seat under its
own name (`git log --format='%an %s'`): Verifier 20, Builder 11, Coordinator 12, Gate 9. The
human commits are the frozen mandates before the run and this documentation after it.
