#!/usr/bin/env python3
"""Build and test an exact candidate commit from a clean worktree, never the live tree.

    py -3.12 verification/stage-2/candidate.py <commit> [--stage 2] [--with-stage1 <accepted stage-1 commit>]
        [--port 18082] [--second-port 18092] [--stage1-port 18062]
        [--native "python -m tablekeeper" --native-pip "tzdata==2025.3"] [-- extra pytest args]

For each service: `git worktree add --detach <scratch>/<short-sha> <commit>` (clean, HEAD checked), then
either `docker build` the stage folder and run it with --cpus 2 --memory 2g, or (--native, for a Docker
outage) start the command in the stage folder from a fresh py -3.12 venv. Main runs with PORT=9137
(docker; non-default port) or PORT=<port> (native); the second instance (docker) has PORT unset, so
8080 is used. --with-stage1 starts the accepted stage-1 build as the upgrade source. The ports must
be free beforehand. Results go to <scratch>/results/<short>-s<N>-<time>/ (pytest.txt, junit.xml,
screenshots, logs, summary.json).
"""
import argparse
import datetime
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_REPO = HERE.parent.parent
SCRATCH = pathlib.Path(os.environ.get("TK_VERIFIER_SCRATCH", "C:/Users/DivijN/dark-factory/band-work/scratch/verifier"))


def sh(*cmd, check=True, capture=False, timeout=None):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    try:
        return subprocess.run([str(c) for c in cmd], check=check, text=True, encoding="utf-8", errors="replace",
                              capture_output=capture, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"! timed out after {timeout}s: {' '.join(str(c) for c in cmd[:3])}", flush=True)
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def wait_healthy(url, limit=90.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        try:
            with urllib.request.urlopen(url + "/health", timeout=2) as r:
                if r.status == 200:
                    return time.monotonic() - t0
        except Exception:
            pass
        time.sleep(0.25)
    return None


def port_busy(port):
    """True if anything accepts on the port (IPv4 or IPv6 loopback). On Windows a second process can bind a
    port that is already in use (SO_REUSEADDR) and a hung Docker proxy can keep listening, so a busy port
    means results could come from a foreign listener."""
    for fam, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        with socket.socket(fam) as s:
            s.settimeout(0.5)
            try:
                if s.connect_ex((host, port)) == 0:
                    return True
            except OSError:
                pass
    return False


def worktree(repo, commit):
    sha = sh("git", "-C", repo, "rev-parse", commit + "^{commit}", capture=True).stdout.strip()
    wt = SCRATCH / sha[:7]
    if not wt.exists():
        sh("git", "-C", repo, "worktree", "add", "--detach", wt.as_posix(), sha)
    head = sh("git", "-C", wt.as_posix(), "rev-parse", "HEAD", capture=True).stdout.strip()
    assert head == sha, f"worktree {wt} is at {head}, not {sha}"
    dirty = sh("git", "-C", wt.as_posix(), "status", "--porcelain", capture=True).stdout.strip()
    assert not dirty, f"worktree {wt} is not clean:\n{dirty}"
    return sha, wt


class Service:
    def __init__(self, name, stage_dir, sha, stage, port, out, native, native_pip, env_port=None):
        self.name, self.stage_dir, self.sha, self.port, self.out = name, stage_dir, sha, port, out
        self.native, self.native_pip, self.env_port = native, native_pip, env_port
        self.tag = f"tk-verifier-s{stage}-{sha[:7]}"
        self.proc = self.logf = None
        self.base = f"http://127.0.0.1:{port}"
        self.info = {"commit": sha, "dir": stage_dir.as_posix(), "port": port}

    def start(self):
        assert not port_busy(self.port), f"port {self.port} is already in use; refusing to test a foreign listener"
        if self.native:
            nv = SCRATCH / f"native-venv-{self.sha[:7]}"
            npy = nv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if not npy.exists():
                sh("py", "-3.12", "-m", "venv", nv.as_posix())
                if self.native_pip.split():
                    sh(npy, "-m", "pip", "install", "-q", "--disable-pip-version-check", *self.native_pip.split())
            argv = self.native.split()
            if argv[0] == "python":
                argv[0] = str(npy)
            self.logf = open(self.out / f"{self.name}.log", "w", encoding="utf-8")
            env = dict(os.environ, PORT=str(self.port), PYTHONDONTWRITEBYTECODE="1")
            t0 = time.monotonic()
            self.proc = subprocess.Popen(argv, cwd=self.stage_dir.as_posix(), env=env, stdout=self.logf,
                                         stderr=subprocess.STDOUT)
            self.info["mode"] = "native: " + self.native
            self.info["pid"] = self.proc.pid
        else:
            t0 = time.monotonic()
            sh("docker", "build", "-t", self.tag, self.stage_dir.as_posix())
            self.info["build_seconds"] = round(time.monotonic() - t0, 1)
            sh("docker", "rm", "-f", self.cname, check=False, capture=True, timeout=60)
            t0 = time.monotonic()
            run = ["docker", "run", "-d", "--name", self.cname, "--cpus", "2", "--memory", "2g"]
            if self.env_port:
                run += ["-e", f"PORT={self.env_port}", "-p", f"{self.port}:{self.env_port}"]
            else:
                run += ["-p", f"{self.port}:8080"]
            sh(*run, self.tag)
            self.info["mode"] = "docker" + (f" PORT={self.env_port}" if self.env_port else " PORT unset (8080)")
        up = wait_healthy(self.base)
        self.info["startup_seconds"] = None if up is None else round(time.monotonic() - t0, 1)
        return up is not None

    @property
    def cname(self):
        return f"tk-verifier-{self.name}-{self.port}"

    def stop(self):
        if self.native:
            if self.proc:
                self.info["exit_before_stop"] = self.proc.poll()
                self.proc.terminate()
                try:
                    self.proc.wait(10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            if self.logf:
                self.logf.close()
        else:
            st = sh("docker", "inspect", "-f", "{{.State.Status}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}",
                    self.cname, check=False, capture=True, timeout=60).stdout.strip()
            self.info["state"] = st
            logs = sh("docker", "logs", self.cname, check=False, capture=True, timeout=60)
            (self.out / f"{self.name}.log").write_text((logs.stdout or "") + (logs.stderr or ""), encoding="utf-8")
            sh("docker", "rm", "-f", self.cname, check=False, capture=True, timeout=60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commit")
    ap.add_argument("--stage", default="2")
    ap.add_argument("--with-stage1", default=None, help="accepted stage-1 commit to export from (upgrade tests)")
    ap.add_argument("--port", type=int, default=18082)
    ap.add_argument("--second-port", type=int, default=18092)
    ap.add_argument("--stage1-port", type=int, default=18062)
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--native", default=None)
    ap.add_argument("--native-pip", default="")
    args, rest = ap.parse_known_args()
    if rest and rest[0] == "--":
        rest = rest[1:]

    sha, wt = worktree(args.repo, args.commit)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = SCRATCH / "results" / f"{sha[:7]}-s{args.stage}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    stage_dir = wt / f"stage-{args.stage}"
    services = [Service("main", stage_dir, sha, args.stage, args.port, out, args.native, args.native_pip,
                        env_port=9137),
                Service("second", stage_dir, sha, args.stage, args.second_port, out, args.native, args.native_pip)]
    if args.with_stage1:
        s1sha, s1wt = worktree(args.repo, args.with_stage1)
        services.append(Service("stage1", s1wt / "stage-1", s1sha, "1", args.stage1_port, out, args.native,
                                args.native_pip, env_port=9138))
    summary = {"candidate": sha, "stage": args.stage, "started": stamp}
    rc = 99
    try:
        ok = [s.start() for s in services]
        env = dict(os.environ, TK_CANDIDATE_DIR=stage_dir.as_posix(), TK_SCREENSHOT_DIR=(out / "screens").as_posix())
        if not args.native:
            env["TK_STARTUP_SECONDS"] = str(services[0].info["startup_seconds"])
            env["TK_SECOND_STARTUP_SECONDS"] = "never" if not ok[1] else str(services[1].info["startup_seconds"])
        if args.with_stage1 and ok[2]:
            env["TK_STAGE1_BASE_URL"] = services[2].base
        if ok[0]:
            cmd = [sys.executable, str(HERE / "run.py"), "--base-url", services[0].base]
            if ok[1]:
                cmd += ["--second-base-url", services[1].base]
            cmd += ["--junitxml", (out / "junit.xml").as_posix(), *rest]
            print("+", " ".join(cmd), flush=True)
            t0 = time.monotonic()
            with open(out / "pytest.txt", "w", encoding="utf-8") as log:
                p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace")
                for line in p.stdout:
                    sys.stdout.write(line)
                    log.write(line)
                rc = p.wait()
            summary["suite_seconds"] = round(time.monotonic() - t0, 1)
        else:
            print("main service never became healthy", file=sys.stderr)
    finally:
        for s in services:
            s.stop()
            summary[s.name] = s.info
        summary["pytest_exit"] = rc
        summary["results_dir"] = out.as_posix()
        (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(json.dumps(summary, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
