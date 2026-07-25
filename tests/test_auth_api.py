"""WP04 — authentication at the edge, across the three modes.

The load-bearing properties:

- **off** behaves exactly as before (the header is trusted) — proven by the rest of the
  suite, which builds the app with no auth, plus a spot-check here.
- **enforce** refuses anonymous writes/observes; accepts a bearer token or session.
- **warn** serves an anonymous write *and* logs it, so a live hub can migrate.
- the engine never learns about auth — a structural test forbids the import both ways.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
from litestar.testing import TestClient

from agent_mailbox import api as api_module
from agent_mailbox.api import IDENTITY_HEADER, SESSION_COOKIE, build_api
from agent_mailbox.auth import secrets, totp
from agent_mailbox.auth.service import AuthService
from agent_mailbox.auth.store import InMemoryAuthStore
from agent_mailbox.house import House
from agent_mailbox.mailbox import Mailbox
from agent_mailbox.store import InMemoryStore

HUB = "http://hub.invalid"
KEY = secrets.generate_key()
ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"


def _note(to: list[str], content: str) -> dict:
    return {"type": "Note", "to": to, "content": content}


def _build(mode: str) -> tuple[TestClient, AuthService]:
    house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
    auth = AuthService(InMemoryAuthStore(), secret_key=KEY)
    app = build_api(house, HUB, auth=auth, auth_mode=mode)
    return TestClient(app=app), auth


@pytest.fixture
def enforce() -> Iterator[tuple[TestClient, AuthService]]:
    client, auth = _build("enforce")
    with client as c:
        # actors exist; the question is whether a caller is authenticated
        c.post(
            "/actors",
            json={"preferredUsername": ROSEMARY},
            headers={IDENTITY_HEADER: "x"},
        )
        yield c, auth


class TestHubDescriptor:
    def test_off_reports_unauthenticated(self) -> None:
        client, _ = _build("off")
        with client as c:
            assert c.get("/").json()["authenticated"] is False

    def test_enforce_reports_authenticated(self) -> None:
        client, _ = _build("enforce")
        with client as c:
            body = c.get("/").json()
            assert body["authenticated"] is True
            assert "requires authentication" in body["note"]


class TestEnforce:
    def test_anonymous_write_is_refused(self) -> None:
        client, _ = _build("enforce")
        with client as c:
            # join is gated too under enforce
            r = c.post("/actors", json={"preferredUsername": "x"})
            assert r.status_code == 401
            assert r.json()["code"] == "not_authenticated"

    def test_anonymous_observe_is_refused(self) -> None:
        client, _ = _build("enforce")
        with client as c:
            assert c.get("/observe/stats").status_code == 401
            assert c.get("/observe/mailbox/admin").status_code == 401

    async def test_a_bearer_token_is_accepted(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            # mint a token out of band (operator flow is exercised elsewhere)
            minted = await auth.mint_token(ROSEMARY, label="test")
            c.post(
                "/actors",
                json={"preferredUsername": ROSEMARY},
                headers={"Authorization": f"Bearer {minted.secret}"},
            )
            c.post(
                "/actors",
                json={"preferredUsername": TREVOR},
                headers={"Authorization": f"Bearer {minted.secret}"},
            )
            sent = c.post(
                f"/actors/{ROSEMARY}/outbox",
                json=_note([TREVOR], "hi"),
                headers={"Authorization": f"Bearer {minted.secret}"},
            )
            assert sent.status_code == 201, sent.text
            # observe now works with the credential
            assert (
                c.get(
                    "/observe/stats",
                    headers={"Authorization": f"Bearer {minted.secret}"},
                ).status_code
                == 200
            )

    async def test_a_revoked_token_is_refused(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            minted = await auth.mint_token(ROSEMARY, label="test")
            await auth.revoke_token(minted.id)
            r = c.get(
                "/observe/stats",
                headers={"Authorization": f"Bearer {minted.secret}"},
            )
            assert r.status_code == 401
            assert r.json()["code"] == "token_revoked"


class TestWarn:
    def test_anonymous_write_is_served_and_logged(self) -> None:
        import logging

        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture()
        logger = logging.getLogger("agent_mailbox.api")
        logger.addHandler(handler)
        try:
            client, _ = _build("warn")
            with client as c:
                for name in (ROSEMARY, TREVOR):
                    c.post(
                        "/actors",
                        json={"preferredUsername": name},
                        headers={IDENTITY_HEADER: name},
                    )
                sent = c.post(
                    f"/actors/{ROSEMARY}/outbox",
                    json=_note([TREVOR], "hi"),
                    headers={IDENTITY_HEADER: ROSEMARY},
                )
            assert sent.status_code == 201, sent.text
            assert any("warn mode" in r.getMessage() for r in records)
        finally:
            logger.removeHandler(handler)


class TestLoginFlow:
    async def test_bootstrap_login_enrol_cycle(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            pw = await auth.bootstrap()
            assert pw is not None
            # login with the bootstrap password → enrol required, limited session
            r = c.post("/auth/login", json={"username": "admin", "password": pw})
            assert r.status_code == 200 and r.json()["next"] == "enrol"
            assert SESSION_COOKIE in r.cookies
            # begin enrolment → get a QR and recovery codes
            enrol = c.get("/auth/enrol").json()
            assert enrol["qrSvg"].startswith("<svg") or "<svg" in enrol["qrSvg"]
            secret = enrol["provisioningUri"].split("secret=")[1].split("&")[0]
            # complete enrolment → active, full session
            done = c.post(
                "/auth/enrol",
                json={"password": "newpassword", "otp": totp.current_code(secret)},
            )
            assert done.status_code == 200 and done.json()["next"] == "ok"
            # the session now authorises an operator action: mint a token
            minted = c.post(f"/auth/agents/{ROSEMARY}/tokens", json={"label": "l"})
            assert minted.status_code == 201
            assert "token" in minted.json()

    async def test_token_admin_requires_a_session(self) -> None:
        client, _ = _build("enforce")
        with client as c:
            # no session cookie → refused
            assert (
                c.post("/auth/agents/x/tokens", json={"label": "l"}).status_code == 401
            )


class TestStructuralBoundary:
    """NFR-002: the engine and the auth layer do not import each other."""

    def _imports(self, module_path: Path) -> set[str]:
        tree = ast.parse(module_path.read_text())
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
        return names

    def test_engine_does_not_import_auth(self) -> None:
        src = Path(api_module.__file__).parent
        for name in ("rules", "mailbox", "house", "store", "sqlite_store", "records"):
            imports = self._imports(src / f"{name}.py")
            assert not any("auth" in i for i in imports), (
                f"{name}.py imports auth — the engine must not know auth"
            )

    def test_auth_does_not_import_the_engine(self) -> None:
        auth_dir = Path(api_module.__file__).parent / "auth"
        engine = {"mailbox", "rules", "house", "sqlite_store"}
        for path in auth_dir.glob("*.py"):
            imports = self._imports(path)
            leaked = {
                i
                for i in imports
                if any(i.endswith(f"agent_mailbox.{e}") for e in engine)
            }
            assert not leaked, f"{path.name} imports the engine: {leaked}"
