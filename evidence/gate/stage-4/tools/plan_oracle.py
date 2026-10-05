"""Gate's independent brute-force oracle for the stage-4 seating replan (spec stage-4.md "Seating changes").

best_plan(tables, pairs, considered, fixed, closures) -> (assignments, moved_count, unused_seats) or None
  tables:     [table_id, ...] in fixture order
  pairs:      [[a, b], ...] in declared (combinable) order
  considered: [{"reference", "party_size", "table_ids", "start", "end", "capacities": {table_id: cap}}]
              (start/end are comparable instants; capacities are the booking's OWN accepted terms)
  fixed:      [{"table_ids", "start", "end"}]  confirmed bookings that keep their assignment
  closures:   [{"table_id", "from", "to"}]     previously applied closures plus the proposed one
Objective (lexicographic): moved count, total unused seats, vector of option ranks in ascending reference order.
Option ranks: singles in fixture order first, then pairs in declared order, starting at 0.
"""
from itertools import product


def _overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def options_for(tables, pairs, booking, fixed, closures):
    opts = [[t] for t in tables] + [list(p) for p in pairs]
    out = []
    for rank, tids in enumerate(opts):
        cap = sum(booking["capacities"].get(t, 0) for t in tids)
        if cap < booking["party_size"]:
            continue
        if any(set(tids) & set(f["table_ids"]) and _overlap(booking["start"], booking["end"], f["start"], f["end"])
               for f in fixed):
            continue
        if any(c["table_id"] in tids and _overlap(booking["start"], booking["end"], c["from"], c["to"]) for c in closures):
            continue
        out.append((rank, tids, cap))
    return out


def best_plan(tables, pairs, considered, fixed, closures):
    cons = sorted(considered, key=lambda b: b["reference"])
    per = [options_for(tables, pairs, b, fixed, closures) for b in cons]
    if any(not o for o in per):
        return None
    best = None
    for combo in product(*per):
        ok = True
        for i in range(len(cons)):
            for j in range(i + 1, len(cons)):
                if set(combo[i][1]) & set(combo[j][1]) and _overlap(cons[i]["start"], cons[i]["end"],
                                                                     cons[j]["start"], cons[j]["end"]):
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue
        moved = sum(1 for b, c in zip(cons, combo) if set(c[1]) != set(b["table_ids"]))
        unused = sum(c[2] - b["party_size"] for b, c in zip(cons, combo))
        key = (moved, unused, [c[0] for c in combo])
        if best is None or key < best[0]:
            best = (key, combo)
    if best is None:
        return None
    (moved, unused, _), combo = best
    assignments = [{"reference": b["reference"], "table_ids": c[1], "changed": set(c[1]) != set(b["table_ids"])}
                   for b, c in zip(cons, combo)]
    return assignments, moved, unused


if __name__ == "__main__":
    # self-test: t_2 closes; A on t_2 (party 3) must move; t_3 (cap 4) beats pair t_1+t_2 and wastes 1 seat
    T = ["t_1", "t_2", "t_3"]
    P = [["t_1", "t_2"]]
    caps = {"t_1": 2, "t_2": 4, "t_3": 4}
    A = {"reference": "AAA111", "party_size": 3, "table_ids": ["t_2"], "start": 0, "end": 90, "capacities": caps}
    B = {"reference": "BBB222", "party_size": 2, "table_ids": ["t_1"], "start": 0, "end": 90, "capacities": caps}
    r = best_plan(T, P, [A], [B], [{"table_id": "t_2", "from": 0, "to": 300}])
    assert r and r[0][0]["table_ids"] == ["t_3"] and r[1] == 1 and r[2] == 1, r
    r = best_plan(T, P, [A, dict(B, reference="CCC333", table_ids=["t_3"], party_size=4)], [],
                  [{"table_id": "t_2", "from": 0, "to": 300}])
    assert r is None or r[1] >= 1
    print("oracle self-test ok", r)
