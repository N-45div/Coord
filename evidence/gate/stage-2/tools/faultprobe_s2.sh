#!/usr/bin/env bash
# Gate stage-2 fault probe: each mutant in mut3/Mn runs natively on its own Gate port; the FROZEN Verifier
# stage-2 suite (ec1e588, its 4 known-bad tests deselected, -x) and Gate's own probes run against it.
cd C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk
export PYTHONTZPATH='C:\Users\DivijN\AppData\Local\Programs\Python\Python312\Lib\site-packages\tzdata\zoneinfo' PYTHONDONTWRITEBYTECODE=1
export TK_VERIFIER_VENV=C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk/vvenv2 TK_STAGE1_BASE_URL=http://127.0.0.1:18368
S=C:/Users/DivijN/dark-factory/band-work/scratch/gate/suite-ec1e588/verification/stage-2
DESEL=(--deselect test_20_combined.py::test_create_pair_response_shape --deselect test_20_combined.py::test_patch_single_to_pair_and_back
       --deselect test_20_combined.py::test_moves_with_table_ids --deselect test_30_browser.py::test_grid_matches_availability_api)
timeout 60 docker rm -f tk-gate-s1m >/dev/null 2>&1
timeout 60 docker run -d --name tk-gate-s1m --cpus 2 --memory 2g -p 18368:8080 tk-gate-s1-e48a498 >/dev/null
for m in M20 M21 M22 M23 M24 M25 M26 M27; do
  n=${m#M}; port=$((18340 + n))
  (cd mut3/$m && PORT=$port py -3.12 -m tablekeeper > ../../mut3-$m-server.log 2>&1 &)
  for i in $(seq 1 100); do curl -s -m 1 http://127.0.0.1:$port/health >/dev/null && break; sleep 0.2; done
  case $m in
    M20|M21|M22) files="$S/test_30_browser.py"; own="uivenv/Scripts/python.exe ui_s2.py http://127.0.0.1:$port mut3-$m-shots" ;;
    M26) files="$S/test_21_upgrade.py"; own="py -3.12 upgrade_s2.py http://127.0.0.1:18368 http://127.0.0.1:$port" ;;
    *) files="$S/test_20_combined.py"; own="py -3.12 probe_s2.py http://127.0.0.1:$port" ;;
  esac
  timeout 1200 py -3.12 $S/run.py --base-url http://127.0.0.1:$port -p no:cacheprovider -q -x -rf "${DESEL[@]}" $files > mut3-$m-suite.log 2>&1
  srs=$(grep -E '[0-9]+ (passed|failed)' mut3-$m-suite.log | tail -1); first=$(grep -E '^FAILED' mut3-$m-suite.log | head -1 | cut -c1-120)
  timeout 900 $own > mut3-$m-own.log 2>&1; ors=$(grep SUMMARY mut3-$m-own.log)
  echo "$m port=$port SUITE: ${first:-none failed} :: $srs || GATE: $ors"
  powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
done
timeout 60 docker rm -f tk-gate-s1m >/dev/null 2>&1
