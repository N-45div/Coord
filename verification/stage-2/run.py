#!/usr/bin/env python3
"""Run the stage-2 verifier suite against a running service. One command:

    py -3.12 verification/stage-2/run.py --base-url http://127.0.0.1:18282 [extra pytest args]

Creates <suite>/.venv (or $TK_VERIFIER_VENV) with the pinned requirements and Playwright's Chromium
on first use. Optional: --second-base-url <url> of a second, freshly started instance (cross-instance
import); TK_STAGE1_BASE_URL=<url> of the accepted stage-1 service (upgrade tests); TK_SCREENSHOT_DIR.
"""
import argparse
import hashlib
import os
import pathlib
import subprocess
import sys
import venv

HERE = pathlib.Path(__file__).resolve().parent


def ensure_venv():
    root = pathlib.Path(os.environ.get("TK_VERIFIER_VENV", HERE / ".venv"))
    py = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    req = (HERE / "requirements.txt").read_bytes()
    stamp = root / "requirements.sha256"
    digest = hashlib.sha256(req).hexdigest()
    if not py.exists():
        venv.create(root, with_pip=True)
    if not stamp.exists() or stamp.read_text().strip() != digest:
        subprocess.check_call([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                               "-r", str(HERE / "requirements.txt")])
        subprocess.check_call([str(py), "-m", "playwright", "install", "chromium"])
        stamp.write_text(digest)
    return py


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("TK_BASE_URL", "http://127.0.0.1:18282"))
    ap.add_argument("--second-base-url", default=os.environ.get("TK_SECOND_BASE_URL", ""))
    args, rest = ap.parse_known_args()
    py = ensure_venv()
    env = dict(os.environ, TK_BASE_URL=args.base_url, TK_SECOND_BASE_URL=args.second_base_url,
               PYTHONDONTWRITEBYTECODE="1")
    return subprocess.call([str(py), "-m", "pytest", str(HERE), "--base-url", args.base_url, *rest],
                           env=env, cwd=str(HERE))


if __name__ == "__main__":
    sys.exit(main())
