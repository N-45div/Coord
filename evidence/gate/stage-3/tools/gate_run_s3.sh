#!/usr/bin/env bash
# Gate acceptance driver: clean worktree build + start timing + probe (+ fresh second container).
# Usage: bash gate_run.sh <full-sha> <stage-number>
set -u
SHA="$1"; N="${2:-1}"; SHORT="${SHA:0:7}"
REPO=C:/Users/DivijN/dark-factory/band-work/result
WT=C:/Users/DivijN/dark-factory/band-work/scratch/gate/$SHORT
OUT=C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk/run-$SHORT-s$N
mkdir -p "$OUT"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/driver.log"; }

if [ ! -d "$WT" ]; then git -C "$REPO" worktree add --detach "$WT" "$SHA" >>"$OUT/driver.log" 2>&1; fi
log "worktree HEAD $(git -C "$WT" rev-parse HEAD) status: '$(git -C "$WT" status --porcelain | head -3)'"
IMG=tk-gate-s$N-$SHORT
timeout 60 docker rm -f tk-gate-a tk-gate-b tk-gate-c >/dev/null 2>&1
t0=$(date +%s)
timeout 900 docker build --no-cache -t "$IMG" "$WT/stage-$N" >"$OUT/build.log" 2>&1; rc=$?
log "docker build rc=$rc in $(( $(date +%s) - t0 ))s (image $IMG)"
[ $rc -ne 0 ] && exit 1
timeout 60 docker image inspect "$IMG" --format 'image size {{.Size}} bytes' | tee -a "$OUT/driver.log"

wait_health() { # port name
  local s=$(date +%s%N) code
  for i in $(seq 1 1200); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$1/health")
    if [ "$code" = "200" ]; then log "$2 healthy after $(( ($(date +%s%N) - s) / 1000000 )) ms: $(curl -s -i http://127.0.0.1:$1/health | tr -d '\r' | grep -i -E 'content-type|status' | tr '\n' ' ')"; return 0; fi
    sleep 0.05
  done
  log "$2 NOT healthy within 60s"; return 1
}
timeout 60 docker run -d --name tk-gate-a --cpus 2 --memory 2g -e PORT=8080 -p 18383:8080 "$IMG" >/dev/null; wait_health 18383 "A(PORT=8080,2cpu,2g)"
timeout 60 docker run -d --name tk-gate-b --cpus 2 --memory 2g -p 18384:8080 "$IMG" >/dev/null; wait_health 18384 "B(no PORT env -> default 8080)"
timeout 60 docker run -d --name tk-gate-c --cpus 2 --memory 2g -e PORT=9123 -p 18385:9123 "$IMG" >/dev/null; wait_health 18385 "C(PORT=9123)"
log "probe start"
py -3.12 C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk/probe_s1.py http://127.0.0.1:18383 http://127.0.0.1:18385 >"$OUT/probe.log" 2>&1; timeout 60 docker restart tk-gate-c >/dev/null; for i in $(seq 1 100); do curl -s -m 1 http://127.0.0.1:18385/health >/dev/null && break; sleep 0.2; done; py -3.12 C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk/probe_s2.py http://127.0.0.1:18383 http://127.0.0.1:18385 >"$OUT/probe_s2.log" 2>&1; log "probe_s2 rc=$? :: $(grep SUMMARY "$OUT/probe_s2.log")"; timeout 60 docker restart tk-gate-c >/dev/null; for i in $(seq 1 100); do curl -s -m 1 http://127.0.0.1:18385/health >/dev/null && break; sleep 0.2; done; py -3.12 C:/Users/DivijN/dark-factory/band-work/scratch/gate/tk/probe_s3.py http://127.0.0.1:18383 http://127.0.0.1:18385 >"$OUT/probe_s3.log" 2>&1; log "probe_s3 rc=$? :: $(grep SUMMARY "$OUT/probe_s3.log")"
log "probe rc=$? :: $(grep SUMMARY "$OUT/probe.log")"
timeout 60 docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' tk-gate-a tk-gate-b tk-gate-c | tee -a "$OUT/driver.log"
timeout 60 docker logs tk-gate-a >"$OUT/container-a.log" 2>&1
grep -c . "$OUT/container-a.log" | xargs -I{} echo "container-a log lines: {}" | tee -a "$OUT/driver.log"
timeout 60 docker rm -f tk-gate-a tk-gate-b tk-gate-c >/dev/null 2>&1; log "containers removed"
