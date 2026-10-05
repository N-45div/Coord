"""Create stage-4 fault-probe mutants from a stage-4 source tree. Usage: py mkmut6.py <src stage-4 dir>"""
import pathlib, shutil, sys
src = pathlib.Path(sys.argv[1]) / "tablekeeper"
root = pathlib.Path("mut6")
shutil.rmtree(root, ignore_errors=True)
M = {
 "M60": [("replan.py", "least_unused[i] = least_unused[i + 1] + min(o.unused for o in candidates[i])", "least_unused[i] = 0"),
         ("replan.py", "search(i + 1, moved + option.changed, unused + option.unused)", "search(i + 1, moved + option.changed, unused + 0)")],
 "M61": [("replan.py", "if r.confirmed and r.overlaps(start, end)), key=lambda r: r.reference)",
          "if r.confirmed and r.overlaps(start, end) and table_id in r.table_ids), key=lambda r: r.reference)")],
 "M62": [("replan.py", 'capacity = res.terms["capacities"]', "capacity = {t.id: t.capacity for t in restaurant.tables}")],
 "M63": [("replan.py", "    if state.restaurant_revision[restaurant.id] != plan.restaurant_revision:\n", "    if False:\n")],
 "M64": [("replan.py", "            moved.append(res)\n", "            moved.append(res)\n            state.bump_restaurant(restaurant.id)\n")],
 "M65": [("replan.py", "    state.plans[plan.id] = plan\n", "    state.plans[plan.id] = plan\n    state.closures.append(Closure(restaurant.id, table_id, start, end, plan.id))\n")],
 "M66": [("series.py", "apply_change(state, restaurant, state.reservations[res_id], placement, now, exception=False)",
          "apply_change(state, restaurant, state.reservations[res_id], placement, now, exception=True)")],
 "M67": [("series.py", "if occurrence.index < from_index or occurrence.exception or not res.confirmed:",
          "if occurrence.index < from_index or not res.confirmed:")],
 "M68": [("model.py", "return self.table_id in table_ids and self.start < end and start < self.end",
          "return self.table_id in list(table_ids)[:1] and self.start < end and start < self.end")],
 "M69": [("replan.py", "    res.table_ids = list(table_ids)\n    res.revision += 1\n", "    res.table_ids = list(table_ids)\n")],
}
for m, patches in M.items():
    dst = root / m / "tablekeeper"
    shutil.copytree(src, dst)
    for f, old, new in patches:
        p = dst / f; s = p.read_text(encoding="utf-8")
        assert old in s, (m, f, old[:60]); p.write_text(s.replace(old, new, 1), encoding="utf-8")
    print(m, "ok")
