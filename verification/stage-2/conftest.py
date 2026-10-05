import json
import os

import pytest

import tk


def pytest_addoption(parser):
    parser.addoption("--base-url", default=None, help="service base URL (default $TK_BASE_URL or http://localhost:18082)")
    parser.addoption("--dump-ledger", default=None, help="write {test id: [ledger ids]} JSON and exit after collection")


def pytest_configure(config):
    config.addinivalue_line("markers", "ledger(*ids): ledger items (S1-xxx, A-xx) this test checks")
    config.addinivalue_line("markers", "slow: waits on the real clock")
    url = config.getoption("--base-url")
    if url:
        tk.BASE_URL = url.rstrip("/")
        os.environ["TK_BASE_URL"] = tk.BASE_URL


def pytest_collection_modifyitems(session, config, items):
    out = config.getoption("--dump-ledger")
    if not out:
        return
    mapping = {}
    for item in items:
        ids = []
        for m in item.iter_markers("ledger"):
            ids.extend(m.args)
        mapping[item.nodeid] = sorted(set(ids))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=1)


@pytest.fixture
def api():
    a = tk.Api()
    yield a
    a.close()


@pytest.fixture
def w(api):
    return tk.World(api)


def pytest_report_header(config):
    return (f"tablekeeper stage-2 verifier suite; base URL {tk.BASE_URL}; second {tk.SECOND_BASE_URL or '-'}; "
            f"stage-1 {os.environ.get('TK_STAGE1_BASE_URL') or '-'}")
