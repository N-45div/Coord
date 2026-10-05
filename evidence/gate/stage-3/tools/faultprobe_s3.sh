#!/usr/bin/env bash
# Gate stage-3 fault probe: mutants in mut5/Mn (copies of 0720c48 stage-3/tablekeeper), native on Gate ports.
cd C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk
export PYTHONTZPATH='C:\Users\DivijN\AppData\Local\Programs\Python\Python312\Lib\site-packages\tzdata\zoneinfo' PYTHONDONTWRITEBYTECODE=1
export TK_VERIFIER_VENV=C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk/vvenv2 TK_STAGE1_BASE_URL=http://127.0.0.1:18368 TK_STAGE2_BASE_URL=http://127.0.0.1:18369
S=C:/Users/DivijN/dark-factory/band-work/scratch/gate/suite3-head/verification/stage-3
timeout 60 docker rm -f tk-gate-s1m tk-gate-s2m >/dev/null 2>&1
timeout 60 docker run -d --name tk-gate-s1m --cpus 2 --memory 2g -p 18368:8080 tk-gate-s1-e48a498 >/dev/null
timeout 60 docker run -d --name tk-gate-s2m --cpus 2 --memory 2g -p 18369:8080 tk-gate-s2-ebbb856 >/dev/null
for p in 18368 18369; do for i in $(seq 1 100); do curl -s -m 1 http://127.0.0.1:$p/health >/dev/null && break; sleep 0.2; done; done
start() { (cd mut5/$1 && PORT=$2 py -3.12 -m tablekeeper > ../../mut5-$1-$2.log 2>&1 &); for i in $(seq 1 100); do curl -s -m 1 http://127.0.0.1:$2/health >/dev/null && break; sleep 0.2; done; }
stop() { powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -LocalPort $1 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"; }
for m in M40 M41 M42 M43 M44 M45 M46 M47; do
  n=${m#M}; port=$((18320 + n)); port2=$((18340 + n))
  start $m $port; start $m $port2
  if [ $m = M47 ]; then files="$S/test_45_upgrade.py"; own="py -3.12 upgrade_s3.py http://127.0.0.1:18368 http://127.0.0.1:18369 http://127.0.0.1:$port http://127.0.0.1:$port2"
  else files="$S/test_40_explain.py $S/test_41_history.py $S/test_42_policies.py $S/test_43_series.py $S/test_44_moves_policies.py"; own="py -3.12 probe_s3.py http://127.0.0.1:$port http://127.0.0.1:$port2"; fi
  timeout 1500 py -3.12 $S/run.py --base-url http://127.0.0.1:$port --second-base-url http://127.0.0.1:$port2 -p no:cacheprovider -q -x -rf $files > mut5-$m-suite.log 2>&1
  srs=$(grep -E '[0-9]+ (passed|failed)' mut5-$m-suite.log | tail -1); first=$(grep -E '^FAILED' mut5-$m-suite.log | head -1 | cut -c1-120)
  stop $port; stop $port2; start $m $port; start $m $port2
  timeout 600 $own > mut5-$m-own.log 2>&1; ors=$(grep SUMMARY mut5-$m-own.log)
  echo "$m SUITE: ${first:-none failed} :: $srs || GATE: $ors"
  stop $port; stop $port2
done
timeout 60 docker rm -f tk-gate-s1m tk-gate-s2m >/dev/null 2>&1
