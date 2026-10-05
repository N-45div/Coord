"""Authentication (spec §6) and bearer-token enforcement."""
import pytest

import tk
from tk import THU, body, expect


@pytest.mark.ledger("S1-027", "S1-028", "A-15")
def test_signup_then_login(w, api):
    r = api.signup("new@example.com", "correct horse", "Neo")
    expect(r, 201)
    assert set(r.json) >= {"user_id", "display_name", "token"}
    assert r.json["display_name"] == "Neo"
    assert isinstance(r.json["token"], str) and r.json["token"]
    assert api.list(r.json["token"]) == []  # token works immediately
    lg = api.login("new@example.com", "correct horse")
    expect(lg, 200)
    assert lg.json["user_id"] == r.json["user_id"] and lg.json["display_name"] == "Neo"
    assert isinstance(lg.json["token"], str) and lg.json["token"]
    api.book(lg.json["token"], "r_anker", "t_1", f"{THU}T19:00")
    assert len(api.list(r.json["token"])) == 1


@pytest.mark.ledger("S1-014")
def test_seeded_users_log_in_with_fixture_password(w, api):
    for u in (tk.ADA, tk.BOB, tk.CY):
        lg = api.login(u["email"], u["password"])
        expect(lg, 200)
        assert lg.json["user_id"] == u["id"] and lg.json["display_name"] == u["display_name"]


@pytest.mark.ledger("S1-029")
def test_duplicate_email_409(w, api):
    expect(api.signup("dup@example.com", "password1", "D"), 201)
    expect(api.signup("dup@example.com", "password2", "E"), 409, "email_taken")
    expect(api.signup(tk.ADA["email"], "password3", "F"), 409, "email_taken")


@pytest.mark.ledger("S1-029", "A-10")
def test_email_uniqueness_and_login_case_insensitive(w, api):
    expect(api.signup("ADA@Example.COM", "password3", "Ada2"), 409, "email_taken")
    lg = api.login("Ada@EXAMPLE.com", tk.ADA["password"])
    expect(lg, 200)
    assert lg.json["user_id"] == "u_ada"


@pytest.mark.ledger("S1-030")
def test_password_length(w, api):
    expect(api.signup("short@example.com", "1234567", "S"), 422, "validation_failed")
    expect(api.signup("short@example.com", "", "S"), 422, "validation_failed")
    expect(api.signup("short@example.com", "12345678", "S"), 201)


@pytest.mark.ledger("S1-031", "A-10")
@pytest.mark.parametrize("email", ["plainaddress", "@example.com", "user@", "a@b@c.com", "a b@example.com",
                                   "ab@exa mple.com", "", " ada2@example.com"])
def test_invalid_email_422(w, api, email):
    expect(api.signup(email, "long enough pw", "E"), 422, "validation_failed")


@pytest.mark.ledger("S1-032")
def test_login_failures_401(w, api):
    expect(api.login(tk.ADA["email"], "wrong password"), 401, "unauthenticated")
    expect(api.login("nobody@example.com", "whatever pw"), 401, "unauthenticated")


@pytest.mark.ledger("S1-033", "S1-021", "S1-020", "A-10")
@pytest.mark.parametrize("path,b,status", [
    ("/auth/signup", {"password": "long enough", "display_name": "X"}, 422),
    ("/auth/signup", {"email": "m@example.com", "display_name": "X"}, 422),
    ("/auth/signup", {"email": "m@example.com", "password": "long enough"}, 422),
    ("/auth/signup", {"email": "m@example.com", "password": "long enough", "display_name": ""}, 422),
    ("/auth/signup", {"email": 5, "password": "long enough", "display_name": "X"}, 400),
    ("/auth/signup", {"email": "m@example.com", "password": 12345678, "display_name": "X"}, 400),
    ("/auth/signup", {"email": "m@example.com", "password": "long enough", "display_name": 7}, 400),
    ("/auth/login", {"email": "ada@example.com"}, 422),
    ("/auth/login", {"password": "correct horse"}, 422),
    ("/auth/login", {"email": ["ada@example.com"], "password": "correct horse"}, 400),
    ("/auth/login", {"email": "ada@example.com", "password": True}, 400),
], ids=["su-no-email", "su-no-password", "su-no-display", "su-empty-display", "su-email-int", "su-pw-int",
        "su-display-int", "li-no-password", "li-no-email", "li-email-list", "li-pw-bool"])
def test_missing_vs_wrong_type_fields(w, api, path, b, status):
    r = api.call("POST", path, body=b)
    expect(r, status, "validation_failed" if status == 422 else "malformed_request")


@pytest.mark.ledger("S1-020")
@pytest.mark.parametrize("path", ["/auth/signup", "/auth/login"])
@pytest.mark.parametrize("raw", ["not json", "[]", "", '{"email": '])
def test_auth_unparseable_body_400(w, api, path, raw):
    expect(api.call("POST", path, raw=raw), 400, "malformed_request")


PROTECTED = [
    ("GET", "/reservations"),
    ("GET", "/reservations/{ref}"),
    ("POST", "/reservations"),
    ("POST", "/reservations/{ref}/cancel"),
    ("PATCH", "/reservations/{ref}"),
    ("POST", "/reservation-moves"),
]
BAD_AUTH = [None, "", "Bearer", "Bearer  x y", "Basic YWRhOmNvcnJlY3QgaG9yc2U=", "Bearer not-a-token", "Token {tok}", "{tok}"]


@pytest.mark.ledger("S1-034")
@pytest.mark.parametrize("method,path", PROTECTED, ids=[f"{m} {p}" for m, p in PROTECTED])
def test_protected_endpoints_401(w, api, method, path):
    tok = w.ada
    ref = api.book(tok, "r_anker", "t_1", f"{THU}T19:00")["reference"]
    p = path.format(ref=ref)
    b = {"party_size": 1} if method == "PATCH" else (
        {"moves": [{"reference": ref}]} if p == "/reservation-moves" else body("r_anker", "t_2", f"{THU}T19:00"))
    for auth in BAD_AUTH:
        headers = {} if auth is None else {"Authorization": auth.format(tok=tok)}
        r = api.call(method, p, headers=headers, key=tk.new_key(),
                     **({"body": b} if method in ("POST", "PATCH") else {}))
        expect(r, 401, "unauthenticated")
    cur = api.get_ok(tok, ref)
    assert cur["status"] == "confirmed" and cur["party_size"] == 2
    assert len(api.list(tok)) == 1


@pytest.mark.ledger("S1-034", "S1-047", "S1-048", "S1-049")
def test_public_endpoints_need_no_token(w, api):
    expect(api.call("GET", "/restaurants"), 200)
    expect(api.call("GET", "/restaurants/r_anker"), 200)
    expect(api.avail("r_anker", THU, 2), 200)
    expect(api.call("GET", "/health"), 200)


@pytest.mark.ledger("S1-035")
def test_multiple_tokens_all_valid(w, api):
    t1 = api.token(tk.ADA["email"], tk.ADA["password"])
    t2 = api.token(tk.ADA["email"], tk.ADA["password"])
    su = api.signup("multi@example.com", "long enough", "M")
    t3 = su.json["token"]
    t4 = api.token("multi@example.com", "long enough")
    for t in (t1, t2, t3, t4):
        expect(api.call("GET", "/reservations", token=t), 200)
    made = api.book(t1, "r_anker", "t_1", f"{THU}T19:00")
    expect(api.cancel(t2, made["reference"]), 200)
    assert api.list(t1)[0]["status"] == "cancelled"


@pytest.mark.ledger("S1-069", "S1-034")
def test_tokens_are_per_user(w, api):
    a = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00")
    assert api.list(w.bob) == []
    expect(api.get(w.bob, a["reference"]), 404, "not_found")
