#!/usr/bin/env bash
# Gate stage-4 fault probe: mutants in mut6/Mn (copies of the candidate's stage-4/tablekeeper), native on Gate ports.
# Usage: bash faultprobe_s4.sh <verifier stage-4 suite dir>
cd C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk
S="$1"
export PYTHONTZPATH='C:\Users\DivijN\AppData\Local\Programs\Python\Python312\Lib\site-packages\tzdata\zoneinfo' PYTHONDONTWRITEBYTECODE=1
export TK_VERIFIER_VENV=C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk/vvenv2
start() { (cd mut6/$1 && PORT=$2 py -3.12 -m tablekeeper > ../../mut6-$1-$2.log 2>&1 &); for i in $(seq 1 100); do curl -s -m 1 http://127.0.0.1:$2/health >/dev/null && break; sleep 0.2; done; }
stop() { powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -LocalPort $1 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"; }
files=$(ls $S/test_5*.py $S/test_6*.py 2>/dev/null | tr '\n' ' ')
for m in $(ls mut6); do
  n=${m#M}; port=$((18300 + n)); port2=$((18320 + n))
  start $m $port; start $m $port2
  timeout 1500 py -3.12 $S/run.py --base-url http://127.0.0.1:$port --second-base-url http://127.0.0.1:$port2 -p no:cacheprovider -q -x -rf $files > mut6-$m-suite.log 2>&1
  srs=$(grep -E '[0-9]+ (passed|failed)' mut6-$m-suite.log | tail -1); first=$(grep -E '^FAILED' mut6-$m-suite.log | head -1 | cut -c1-120)
  stop $port; stop $port2; start $m $port; start $m $port2
  timeout 600 py -3.12 probe_s4.py http://127.0.0.1:$port http://127.0.0.1:$port2 > mut6-$m-own.log 2>&1
  echo "$m SUITE: ${first:-none failed} :: $srs || GATE: $(grep SUMMARY mut6-$m-own.log)"
  stop $port; stop $port2
done
