from tests.conftest import register


async def test_register_login_me_logout(client) -> None:  # type: ignore[no-untyped-def]
    user = await register(client)
    assert user["email"] == "user@example.com" and user["role"] == "user"
    assert "hashed_password" not in user

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200

    out = await client.post("/api/v1/auth/logout")
    assert out.status_code == 200
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    login = await client.post("/api/v1/auth/login", json={"email": "USER@example.com", "password": "s3cure-passw0rd"})
    assert login.status_code == 200
    assert "ti_session" in login.cookies
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_logout_revokes_token_server_side(client) -> None:  # type: ignore[no-untyped-def]
    await register(client)
    token = client.cookies.get("ti_session")
    await client.post("/api/v1/auth/logout")
    client.cookies.clear()
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_duplicate_and_weak_password(client) -> None:  # type: ignore[no-untyped-def]
    await register(client)
    dup = await client.post("/api/v1/auth/register", json={"email": "user@example.com", "password": "s3cure-passw0rd", "full_name": "X"})
    assert dup.status_code == 409
    weak = await client.post("/api/v1/auth/register", json={"email": "b@example.com", "password": "short", "full_name": "X"})
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "validation_failed"


async def test_wrong_password_rejected(client) -> None:  # type: ignore[no-untyped-def]
    await register(client)
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "wrong-passw0rd"})
    assert resp.status_code == 401
    unknown = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-passw0rd"})
    assert unknown.status_code == 401
    assert resp.json()["error"]["message"] == unknown.json()["error"]["message"]  # no user enumeration


async def test_role_based_access(client) -> None:  # type: ignore[no-untyped-def]
    await register(client)
    assert (await client.get("/api/v1/admin/users")).status_code == 403
    client.cookies.clear()
    admin = await register(client, email="admin@example.com")
    assert admin["role"] == "admin"
    users = await client.get("/api/v1/admin/users")
    assert users.status_code == 200 and len(users.json()) == 2
    logs = await client.get("/api/v1/admin/audit-logs")
    assert any(entry["action"] == "user.register" for entry in logs.json())


async def test_change_password(client) -> None:  # type: ignore[no-untyped-def]
    await register(client)
    bad = await client.post("/api/v1/auth/change-password", json={"current_password": "nope", "new_password": "an0ther-passw0rd"})
    assert bad.status_code == 401
    ok = await client.post("/api/v1/auth/change-password", json={"current_password": "s3cure-passw0rd", "new_password": "an0ther-passw0rd"})
    assert ok.status_code == 200
    client.cookies.clear()
    login = await client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "an0ther-passw0rd"})
    assert login.status_code == 200


async def test_unauthenticated_endpoints_protected(client) -> None:  # type: ignore[no-untyped-def]
    for path in ("/api/v1/dashboard", "/api/v1/paper/portfolio", "/api/v1/strategies", "/api/v1/market/overview"):
        assert (await client.get(path)).status_code == 401, path
