# Gate fault probe, stage 1 (base 105337a, frozen Verifier suite becaddb with its 2 known-bad tests deselected, -x)
Native runs, one disposable copy per mutant in scratch/gate/tk/mut/Mn, ports 18211-18219.
| Mutant | Planted defect (invariant) | Frozen suite | First failing test | Gate probe |
|---|---|---|---|---|
| M1 | moves: no overlap check among listed bookings (S1-100) | DETECTED | test_03_moves::test_moves_overlap_among_resulting_bookings | detected |
| M2 | moves applied item by item, not all-or-nothing (S1-102) | DETECTED | test_01_concurrency::test_parallel_batches_never_observed_half_applied | detected |
| M3 | failed first use consumes the idempotency key (S1-043) | DETECTED | test_02_idempotency::test_key_scoped_per_user | detected |
| M4 | lock released between occupancy check and insert (S1-067) | DETECTED | test_01_concurrency::test_50_parallel_creates_same_table_same_slot_one_winner | detected |
| M5 | fall-back resolves to second occurrence (S1-082) | DETECTED | test_04_dst::test_berlin_fall_back_repeated_times_appear_once_first_offset | detected |
| M6 | cutoff boundary off by 90 s (A-03, S1-072) | DETECTED | test_07_cutoff::test_crossing_the_cutoff_boundary | SURVIVED (probe gap) |
| M7 | occupancy as closed interval, back-to-back rejected (S1-058) | DETECTED | test_01_concurrency::test_parallel_overlapping_creates_never_overlap_and_rejections_are_justified | detected |
| M8 | rejected import wipes idempotency receipts (S1-087 destination unchanged, S1-088) | SURVIVED (376 passed) | - | SURVIVED (probe gap) |
| M9 | replay re-renders the current reservation instead of the original response (S1-044) | DETECTED | test_02_idempotency::test_same_key_on_different_path_is_independent | detected |
Score: frozen suite 8/9 detected, 1 survivor (M8). No invalid mutants.

Comparison with Verifier RESULTS 105337a (suite 3102b28, native): 380 passed / 0 failed / 3 skipped. Gate's run at becaddb:
377 passed / 2 failed (the two suite misreadings Verifier fixed in bf8f5d3) / 4 skipped (Gate ran without candidate.py,
so the delivery-files test also skipped). Consistent.
Coverage gaps sent to Verifier as missing tests (behaviour only, no patch): (1) M8 survivor: a rejected import must leave
idempotency receipts unchanged (S1-087/S1-088); (2) D1 was not caught by the suite: its garbage bodies used ~5000-deep JSON
(400), not the 1000-1600 band that yields 500 on idempotent writes.
Gate probe tool updated after the fault probe: receipts are re-checked after rejected imports (closes the M8 gap in Gate's
own probe); the cutoff boundary (M6) is left to the Verifier suite's boundary-crossing test.
