#!/usr/bin/env python3
"""Build and test an exact candidate commit from a clean worktree, never the live tree.

    py -3.12 verification/stage-1/candidate.py <commit> [--stage 1] [--port 18082] [--second-port 18092]
                                                [--repo <result repo>] [-- extra pytest args]

Steps: git worktree add --detach <scratch>/<short-sha> <commit>; docker build the stage folder
(tag tk-verifier-s<N>-<short>); start it limited to 2 vCPU / 2 GiB with -e PORT=9137 (a non-default
port) on --port, and a second container with PORT unset (default 8080) on --second-port; time
the first healthy /health; run the suite (run.py) against both; save logs and junit XML under
<scratch>/results/; stop the containers.
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
        print(f"! timed out after {timeout}s: {cmd[0]} {cmd[1] if len(cmd) > 1 else ''}", flush=True)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commit")
    ap.add_argument("--stage", default="1")
    ap.add_argument("--port", type=int, default=18082)
    ap.add_argument("--second-port", type=int, default=18092)
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--keep", action="store_true", help="leave containers running")
    ap.add_argument("--native", default=None,
                    help="fallback when Docker is unavailable: command run in the stage folder with PORT set, "
                         "e.g. 'python -m tablekeeper' (python = a fresh venv of py -3.12)")
    ap.add_argument("--native-pip", default="", help="space-separated pinned packages for the native venv")
    args, rest = ap.parse_known_args()
    if rest and rest[0] == "--":
        rest = rest[1:]

    sha = sh("git", "-C", args.repo, "rev-parse", args.commit + "^{commit}", capture=True).stdout.strip()
    short = sha[:7]
    wt = SCRATCH / f"{short}"
    if not wt.exists():
        sh("git", "-C", args.repo, "worktree", "add", "--detach", wt.as_posix(), sha)
    head = sh("git", "-C", wt.as_posix(), "rev-parse", "HEAD", capture=True).stdout.strip()
    assert head == sha, f"worktree {wt} is at {head}, not {sha}"
    dirty = sh("git", "-C", wt.as_posix(), "status", "--porcelain", capture=True).stdout.strip()
    assert not dirty, f"worktree {wt} is not clean:\n{dirty}"
    stage_dir = wt / f"stage-{args.stage}"
    tag = f"tk-verifier-s{args.stage}-{short}"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = SCRATCH / "results" / f"{short}-s{args.stage}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    summary = {"commit": sha, "stage": args.stage, "worktree": wt.as_posix(), "image": tag}

    procs = []
    for p_ in (args.port, args.second_port):
        assert not port_busy(p_), f"port {p_} already has a listener; refusing to run (results could be foreign)"
    if args.native:
        summary["mode"] = "native (no Docker): " + args.native
        nv = SCRATCH / f"native-venv-{short}"
        npy = nv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not npy.exists():
            sh("py", "-3.12", "-m", "venv", nv.as_posix())
            if args.native_pip.split():
                sh(npy, "-m", "pip", "install", "-q", "--disable-pip-version-check", *args.native_pip.split())
        argv = args.native.split()
        if argv[0] == "python":
            argv[0] = str(npy)
        main_name, second_name = f"native-main-{args.port}", f"native-second-{args.second_port}"

        def start(port, name):
            logf = open(out / f"{name}.log", "w", encoding="utf-8")
            env = dict(os.environ, PORT=str(port), PYTHONDONTWRITEBYTECODE="1")
            pr = subprocess.Popen(argv, cwd=stage_dir.as_posix(), env=env, stdout=logf, stderr=subprocess.STDOUT)
            procs.append((pr, logf))
        t0 = time.monotonic()
        start(args.port, main_name)
        base = f"http://127.0.0.1:{args.port}"
        up = wait_healthy(base)
        summary["startup_seconds_main"] = None if up is None else round(time.monotonic() - t0, 1)
        start(args.second_port, second_name)
        second = f"http://127.0.0.1:{args.second_port}"
        up2 = wait_healthy(second)
        summary["startup_seconds_second"] = None if up2 is None else round(time.monotonic() - t0, 1)
    else:
        summary["mode"] = "docker"
        t0 = time.monotonic()
        sh("docker", "build", "-t", tag, stage_dir.as_posix())
        summary["build_seconds"] = round(time.monotonic() - t0, 1)

        main_name, second_name = f"tk-verifier-main-{args.port}", f"tk-verifier-second-{args.second_port}"
        for n in (main_name, second_name):
            sh("docker", "rm", "-f", n, check=False, capture=True, timeout=60)
        t0 = time.monotonic()
        sh("docker", "run", "-d", "--name", main_name, "--cpus", "2", "--memory", "2g",
           "-e", "PORT=9137", "-p", f"{args.port}:9137", tag)
        base = f"http://127.0.0.1:{args.port}"
        up = wait_healthy(base)
        summary["startup_seconds_main"] = None if up is None else round(time.monotonic() - t0, 1)
        t1 = time.monotonic()
        sh("docker", "run", "-d", "--name", second_name, "--cpus", "2", "--memory", "2g",
           "-p", f"{args.second_port}:8080", tag)
        second = f"http://127.0.0.1:{args.second_port}"
        up2 = wait_healthy(second)
        summary["startup_seconds_second_default_port"] = None if up2 is None else round(time.monotonic() - t1, 1)

    rc = 99
    try:
        if up is None:
            print("main container never became healthy", file=sys.stderr)
        else:
            env = dict(os.environ, TK_CANDIDATE_DIR=stage_dir.as_posix())
            if not args.native:  # container startup and default-port evidence only from the Docker mode
                sec = summary["startup_seconds_second_default_port"]
                env.update(TK_STARTUP_SECONDS=str(summary["startup_seconds_main"]),
                           TK_SECOND_STARTUP_SECONDS="never" if sec is None else str(sec))
            cmd = [sys.executable, str(HERE / "run.py"), "--base-url", base,
                   "--junitxml", (out / "junit.xml").as_posix(), *rest]
            if up2 is not None:
                cmd[4:4] = ["--second-base-url", second]
            print("+", " ".join(cmd), flush=True)
            t2 = time.monotonic()
            with open(out / "pytest.txt", "w", encoding="utf-8") as log:
                p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace")
                for line in p.stdout:
                    sys.stdout.write(line)
                    log.write(line)
                rc = p.wait()
            summary["suite_seconds"] = round(time.monotonic() - t2, 1)
    finally:
        if args.native:
            for pr, logf in procs:
                summary[f"exit_{pr.pid}"] = pr.poll()
                pr.terminate()
                try:
                    pr.wait(10)
                except subprocess.TimeoutExpired:
                    pr.kill()
                logf.close()
        else:
            for n in (main_name, second_name):
                st = sh("docker", "inspect", "-f", "{{.State.Status}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}",
                        n, check=False, capture=True, timeout=60).stdout.strip()
                summary[f"state_{n}"] = st
                logs = sh("docker", "logs", n, check=False, capture=True, timeout=60)
                (out / f"{n}.log").write_text((logs.stdout or "") + (logs.stderr or ""), encoding="utf-8")
                if not args.keep:
                    sh("docker", "rm", "-f", n, check=False, capture=True, timeout=60)
        summary["pytest_exit"] = rc
        summary["results_dir"] = out.as_posix()
        (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(json.dumps(summary, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
