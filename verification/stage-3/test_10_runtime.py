"""Runtime contract (spec §2, §3), error envelope (§5), robustness (no 5xx)."""
import json
import os

import pytest

import tk
from tk import THU, body, expect, expect_no_5xx


@pytest.mark.ledger("S1-004")
def test_health(api):
    r = api.call("GET", "/health")
    expect(r, 200)
    assert r.json == {"status": "ok"}


@pytest.mark.ledger("S1-004", "S1-005")
def test_startup_within_60s():
    s = os.environ.get("TK_STARTUP_SECONDS")
    if not s:
        pytest.skip("TK_STARTUP_SECONDS not provided (set by candidate.py)")
    assert float(s) <= 60.0, f"first healthy response after {s} s (> 60 s)"


@pytest.mark.ledger("S1-001")
def test_delivery_files_present():
    d = os.environ.get("TK_CANDIDATE_DIR")
    if not d:
        pytest.skip("TK_CANDIDATE_DIR not provided (set by candidate.py)")
    assert os.path.isfile(os.path.join(d, "Dockerfile")), "Dockerfile missing"
    assert os.path.isfile(os.path.join(d, "RUN.md")), "RUN.md missing"


@pytest.mark.ledger("S1-007", "S1-013", "S1-047")
def test_reset_replaces_state_and_is_repeatable(api):
    api.reset(tk.fixture())
    r = api.call("GET", "/restaurants")
    expect(r, 200)
    assert [x["id"] for x in r.json["restaurants"]] == [x["id"] for x in tk.fixture()["restaurants"]]
    second = tk.fixture(users=(tk.BOB,), restaurants=(tk.HARBOR,))
    rr = api.call("POST", "/_test/reset", body=second, timeout=tk.CTL_TIMEOUT)
    assert rr.status == 204 and rr.content == b"", rr
    r = api.call("GET", "/restaurants")
    assert r.json == {"restaurants": [{"id": "r_harbor", "name": "Harbor House", "timezone": "America/New_York"}]}
    expect(api.call("GET", "/restaurants/r_anker"), 404, "not_found")
    expect(api.login(tk.ADA["email"], tk.ADA["password"]), 401, "unauthenticated")
    expect(api.login(tk.BOB["email"], tk.BOB["password"]), 200)
    api.reset(second)
    api.reset(second)
    expect(api.login(tk.BOB["email"], tk.BOB["password"]), 200)


@pytest.mark.ledger("S1-008")
def test_reset_clears_accounts_tokens_reservations_and_receipts(api):
    w = tk.World(api)
    su = api.signup("new@example.com", "new password", "New")
    expect(su, 201)
    ada = w.ada
    key = tk.new_key()
    made = expect(api.create(ada, body("r_anker", "t_1", f"{THU}T19:00"), key=key), 201)
    api.reset(tk.fixture())
    expect(api.call("GET", "/reservations", token=ada), 401, "unauthenticated")
    expect(api.call("GET", "/reservations", token=su.json["token"]), 401, "unauthenticated")
    expect(api.login("new@example.com", "new password"), 401, "unauthenticated")
    ada2 = api.token(tk.ADA["email"], tk.ADA["password"])
    assert api.list(ada2) == []
    assert "t_1" in api.free_tables("r_anker", f"{THU}T19:00")
    # the receipt is gone: same key + different body is a first use
    r = api.create(ada2, body("r_anker", "t_2", f"{THU}T19:00"), key=key)
    expect(r, 201)
    assert r.json["table_id"] == "t_2"
    expect(api.signup("new@example.com", "new password", "New"), 201)
    assert made["reference"]


@pytest.mark.ledger("S1-007", "S1-015", "S1-014", "A-13")
def test_reset_seeds_reservations_and_users(api):
    fx = tk.fixture(reservations=[tk.seed("res_s1", "SEEDA1", "u_ada", "r_anker", "t_2", f"{THU}T19:00", 3)])
    w = tk.World(api, fx)
    lg = api.login(tk.ADA["email"], tk.ADA["password"])
    expect(lg, 200)
    assert lg.json["user_id"] == "u_ada" and lg.json["display_name"] == "Ada"
    mine = api.list(w.ada)
    assert len(mine) == 1
    tk.assert_res(mine[0], tk.ANKER, "t_2", f"{THU}T19:00", 3, "confirmed")
    assert mine[0]["reservation_id"] == "res_s1" and mine[0]["reference"] == "SEEDA1"
    assert api.free_tables("r_anker", f"{THU}T19:00") == ["t_1", "t_3"]
    expect(api.create(w.bob, body("r_anker", "t_2", f"{THU}T19:30")), 409, "table_unavailable")
    expect(api.get(w.bob, "SEEDA1"), 404, "not_found")


def _ctype_ok(r):
    ct = r.headers.get("content-type", "")
    parts = [p.strip().lower() for p in ct.split(";")]
    return parts[0] == "application/json" and any(p.replace(" ", "") == "charset=utf-8" for p in parts[1:])


@pytest.mark.ledger("S1-009")
def test_content_type_json_utf8_on_success_and_error(w, api):
    made = api.create(w.ada, body("r_anker", "t_1", f"{THU}T19:00"))
    responses = [
        api.call("GET", "/health"),
        api.call("GET", "/restaurants"),
        api.call("GET", "/restaurants/r_anker"),
        api.avail("r_anker", THU, 2),
        made,
        api.call("GET", "/reservations", token=w.ada),
        api.login(tk.ADA["email"], tk.ADA["password"]),
        api.call("GET", "/restaurants/nope"),
        api.call("GET", "/reservations"),
        api.create(w.ada, raw="garbage"),
        api.avail("r_anker"),
    ]
    bad = [f"{r.method} {r.url}: {r.headers.get('content-type')!r}" for r in responses if not _ctype_ok(r)]
    assert not bad, "responses without 'application/json; charset=utf-8':\n" + "\n".join(bad)


@pytest.mark.ledger("S1-026", "A-14", "S1-019")
@pytest.mark.parametrize("method,path", [
    ("GET", "/nope"), ("GET", "/reservations/ABC123/extra"), ("POST", "/restaurants/r_anker/tables"),
    ("GET", "/api/restaurants"),
])
def test_unknown_route_404_with_error_body(w, api, method, path):
    r = api.call(method, path, token=w.ada, **({"body": {}} if method == "POST" else {}))
    expect(r, 404, "not_found")


@pytest.mark.ledger("S1-026", "A-14")
def test_known_path_wrong_method_404_or_405(w, api):
    r = api.call("DELETE", "/restaurants", token=w.ada)
    assert r.status in (404, 405), r
    tk.assert_error_body(r)


@pytest.mark.ledger("S1-011")
def test_unknown_fields_and_query_params_ignored(w, api):
    su = api.signup("x@example.com", "long enough", "X", nickname="xx", role="admin")
    expect(su, 201)
    expect(api.login("x@example.com", "long enough", remember_me=True), 200)
    r = api.create(w.ada, {**body("r_anker", "t_1", f"{THU}T19:00"), "status": "cancelled",
                           "reference": "HACKED1", "user_id": "u_bob", "comment": {"x": [1]}})
    expect(r, 201)
    assert r.json["status"] == "confirmed" and r.json["reference"] != "HACKED1"
    assert api.get_ok(w.ada, r.json["reference"])["status"] == "confirmed"
    p = api.patch(w.ada, r.json["reference"], {"party_size": 1, "restaurant_id": "r_harbor", "status": "cancelled"})
    expect(p, 200)
    assert p.json["restaurant_id"] == "r_anker" and p.json["status"] == "confirmed" and p.json["party_size"] == 1
    a = api.avail("r_anker", THU, 2, extra={"foo": "bar", "page": "2"})
    expect(a, 200)
    assert a.json["slots"] == api.slots("r_anker", THU, 2)
    expect(api.call("GET", "/restaurants", params={"limit": "x"}), 200)
    expect(api.call("GET", "/reservations", token=w.ada, params={"status": "weird"}), 200)


ID64 = "r" + "x" * 62 + "Z"
TID64 = "T-" + "9" * 60 + ".a"
UID64 = "U_" + "u" * 62
RID64 = "R." + "r" * 61 + "~"


@pytest.mark.ledger("S1-012")
def test_64_character_fixture_ids_work_everywhere(api):
    rest = {**tk.ANKER, "id": ID64, "tables": [{"id": TID64, "label": "Long", "capacity": 4}]}
    user = {**tk.ADA, "id": UID64}
    seeded = tk.seed(RID64, "LONGID1", UID64, ID64, TID64, f"{THU}T18:00", 2)
    for x in (ID64, TID64, UID64, RID64):
        assert len(x) == 64
    w = tk.World(api, tk.fixture(users=(user,), restaurants=(rest,), reservations=[seeded]))
    assert api.login(user["email"], user["password"]).json["user_id"] == UID64
    d = api.call("GET", f"/restaurants/{ID64}")
    expect(d, 200)
    assert d.json["tables"] == rest["tables"]
    assert api.free_tables(ID64, f"{THU}T21:00", 2) == [TID64]
    tok = w.tok(UID64)
    made = api.book(tok, ID64, TID64, f"{THU}T21:00")
    assert made["restaurant_id"] == ID64 and made["table_id"] == TID64
    got = api.get_ok(tok, "LONGID1")
    assert got["reservation_id"] == RID64
    m = api.moves(tok, {"moves": [{"reference": "LONGID1", "party_size": 3}]})
    expect(m, 201)


@pytest.mark.ledger("S1-012")
@pytest.mark.parametrize("rid,tid", [("r ünï cøde?&=#", "t ö+1%"), ("r/with/slash", "t/slash")],
                         ids=["unicode-reserved", "slash-strict-reading"])
def test_unusual_characters_in_fixture_ids(api, rid, tid):
    rest = {**tk.HARBOR, "id": rid, "tables": [{"id": tid, "label": "x", "capacity": 4}]}
    w = tk.World(api, tk.fixture(restaurants=(rest,)))
    from urllib.parse import quote
    d = api.call("GET", f"/restaurants/{quote(rid, safe='')}")
    expect(d, 200)
    assert d.json["id"] == rid
    assert api.free_tables(rid, f"{THU}T12:10", 2) == [tid]
    made = api.book(w.ada, rid, tid, f"{THU}T12:10")
    assert made["restaurant_id"] == rid and made["table_id"] == tid


@pytest.mark.ledger("S1-012", "S1-027")
def test_generated_ids_at_most_64_chars(w, api):
    su = api.signup("gen@example.com", "long enough", "Gen")
    expect(su, 201)
    assert isinstance(su.json["user_id"], str) and 1 <= len(su.json["user_id"]) <= 64
    r = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00")
    assert 1 <= len(r["reservation_id"]) <= 64


GARBAGE = [
    b"", b"null", b"[]", b"123", b'"str"', b"{", b'{"a":}', b"\xff\xfe\x00", b"{" * 5000 + b"}" * 5000,
    b"[" * 5000 + b"]" * 5000, b'{"party_size": 1e999}', b'{"party_size": 100000000000000000000000000000}',
    b'{"party_size": -0.0}', b'{"restaurant_id": "' + b"a" * 100000 + b'"}', b'{"email": {"$gt": ""}}',
    b'{"moves": [' + b'{"reference": "X"},' * 2000 + b'{"reference": "Y"}]}', b"\x00",
]


@pytest.mark.ledger("S1-006", "S1-019")
@pytest.mark.parametrize("i", range(len(GARBAGE)))
def test_garbage_bodies_never_5xx(w, api, i):
    raw = GARBAGE[i]
    ref = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00")["reference"] if i == 0 else "NOSUCH1"
    targets = [
        ("POST", "/auth/signup", None, None),
        ("POST", "/auth/login", None, None),
        ("POST", "/reservations", w.ada, tk.new_key()),
        ("PATCH", f"/reservations/{ref}", w.ada, None),
        ("POST", "/reservation-moves", w.ada, tk.new_key()),
        ("POST", "/_test/import", None, None),
    ]
    for method, path, tok, key in targets:
        r = api.call(method, path, token=tok, key=key, raw=raw, timeout=tk.CTL_TIMEOUT)
        expect_no_5xx(r)
        assert r.status >= 400, f"garbage accepted: {r!r}"
    expect(api.call("GET", "/health"), 200)


@pytest.mark.ledger("S1-006", "S1-024")
@pytest.mark.parametrize("q", [
    {"restaurant_id": "r_anker", "date": THU, "party_size": "99999999999999999999999999"},
    {"restaurant_id": "r_anker", "date": "99999-01-01", "party_size": "2"},
    {"restaurant_id": "r_anker", "date": "0000-00-00", "party_size": "2"},
    {"restaurant_id": "\u0000", "date": THU, "party_size": "2"},
    {"restaurant_id": "r_anker", "date": THU, "party_size": "２"},
])
def test_odd_query_values_never_5xx(w, api, q):
    r = api.call("GET", "/availability", params=q)
    expect_no_5xx(r)


@pytest.mark.ledger("S1-024", "S1-052")
def test_huge_plain_digit_party_size_is_valid_with_no_tables(w, api):
    r = api.avail("r_anker", THU, "99999999999999999999999999")
    if r.status == 200:
        assert all(s["available_table_ids"] == [] for s in r.json["slots"]) and len(r.json["slots"]) == 8
    else:
        expect(r, 422, "validation_failed")  # a stated maximum is not given; 422 also acceptable (§5)


@pytest.mark.ledger("S1-003", "S1-002", "S1-004")
def test_port_env_and_default_port(api):
    """candidate.py starts the main container with PORT=9137 (mapped) and a second one with PORT unset (8080)."""
    second = os.environ.get("TK_SECOND_STARTUP_SECONDS")
    if second is None:
        pytest.skip("needs candidate.py (TK_SECOND_STARTUP_SECONDS)")
    expect(api.call("GET", "/health"), 200)  # main container: listening on $PORT=9137
    assert second != "never", "container started without PORT never answered /health on default port 8080 within 90 s"
    assert float(second) <= 60.0, f"default-port container healthy only after {second} s"
    other = tk.Api(tk.SECOND_BASE_URL)
    try:
        expect(other.call("GET", "/health"), 200)
    finally:
        other.close()
