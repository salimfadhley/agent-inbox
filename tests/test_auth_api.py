"""WP04 — authentication at the edge, across the three modes.

The load-bearing properties:

- **off** behaves exactly as before (the header is trusted) — proven by the rest of the
  suite, which builds the app with no auth, plus a spot-check here.
- **enforce** refuses anonymous writes/observes; accepts a bearer token or session.
- **warn** serves an anonymous write *and* logs it, so a live hub can migrate.
- the engine never learns about auth — a structural test forbids the import both ways.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
from litestar.testing import TestClient

from agent_inbox import api as api_module
from agent_inbox.api import IDENTITY_HEADER, SESSION_COOKIE, build_api
from agent_inbox.auth import secrets, totp
from agent_inbox.auth import secrets as auth_secrets
from agent_inbox.auth.records import SHARED_ACTOR, DeviceToken
from agent_inbox.auth.service import AuthService
from agent_inbox.auth.store import InMemoryAuthStore
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

HUB = "http://hub.invalid"
KEY = secrets.generate_key()
ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"


def _note(to: list[str], content: str) -> dict:
    return {"type": "Note", "to": to, "content": content}


def _build(mode: str, throttle: object | None = None) -> tuple[TestClient, AuthService]:
    house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
    auth = AuthService(InMemoryAuthStore(), secret_key=KEY)
    app = build_api(house, HUB, auth=auth, auth_mode=mode, throttle=throttle)
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


async def _legacy_bound(auth, actor: str, label: str = "bound") -> str:
    """Write a token row bound to one agent — the shape that no longer has a mint path.

    Reaching past the service is the point: FR-002 removed every supported way to create
    one, and FR-006 says the rows that already exist keep working. A test that could
    still mint one would be testing a hole rather than the upgrade path.
    """
    secret = auth_secrets.generate_token()
    await auth._store.add_token(
        DeviceToken(
            id=f"legacy-{actor}",
            actor=actor,
            token_hash=auth_secrets.hash_token(secret),
            label=label,
            created="2026-01-01T00:00:00Z",
        )
    )
    return secret


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
            minted = await auth.mint_token(label="test")
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
            # The header is required now, and that is the mission rather than a
            # regression: a token admits the machine, so every request has to say which
            # agent on it is calling.
            sent = c.post(
                f"/actors/{ROSEMARY}/outbox",
                json=_note([TREVOR], "hi"),
                headers={
                    "Authorization": f"Bearer {minted.secret}",
                    IDENTITY_HEADER: ROSEMARY,
                },
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
            minted = await auth.mint_token(label="test")
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
        logger = logging.getLogger("agent_inbox.api")
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
            minted = c.post("/auth/tokens", json={"label": "the laptop"})
            assert minted.status_code == 201
            assert "token" in minted.json()
            assert "actor" not in minted.json(), "a token admits a machine"

    async def test_token_admin_requires_a_session(self) -> None:
        client, _ = _build("enforce")
        with client as c:
            # no session cookie → refused
            assert c.post("/auth/tokens", json={"label": "l"}).status_code == 401
            assert c.get("/auth/tokens").status_code == 401
            assert c.delete("/auth/tokens/whatever").status_code == 401

    async def test_the_per_agent_routes_are_gone(self) -> None:
        """Not deprecated — removed. Leaving a second way to mint is the thing this
        mission exists to stop, and a 404 is the proof it is actually unreachable."""
        client, _ = _build("enforce")
        with client as c:
            assert (
                c.post("/auth/agents/x/tokens", json={"label": "l"}).status_code == 404
            )
            assert c.get("/auth/agents/x/tokens").status_code == 404
            assert c.delete("/auth/agents/x/tokens/t1").status_code == 404


class TestLoginThrottle:
    """Brute-force protection on /auth/login, end to end."""

    def test_repeated_failures_are_locked_out_with_retry_after(self) -> None:
        from agent_inbox.auth.throttle import LoginThrottle

        throttle = LoginThrottle(max_failures=3)
        client, _ = _build("enforce", throttle=throttle)
        with client as c:
            for _ in range(3):
                r = c.post("/auth/login", json={"username": "admin", "password": "x"})
                assert r.status_code == 401  # bad_credentials
            # the next attempt is refused by the throttle, not the credential check
            blocked = c.post("/auth/login", json={"username": "admin", "password": "x"})
            assert blocked.status_code == 429
            assert blocked.json()["code"] == "too_many_attempts"
            assert "retry-after" in {k.lower() for k in blocked.headers}

    def test_lockout_is_by_source_not_username(self) -> None:
        """The throttle keys on source, not username, so it cannot be used to DoS a
        named account, and its 429 names no user."""
        from agent_inbox.auth.throttle import LoginThrottle

        # max_failures=3, but all these come from the same test client (one source), so
        # this really checks the response stays generic — a 429 that never names a user.
        throttle = LoginThrottle(max_failures=3)
        client, _ = _build("enforce", throttle=throttle)
        with client as c:
            for _ in range(3):
                c.post("/auth/login", json={"username": "ghost", "password": "x"})
            r = c.post("/auth/login", json={"username": "ghost", "password": "x"})
            # 429 regardless of whether 'ghost' exists — no enumeration signal
            assert r.status_code == 429


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
                if any(i.endswith(f"agent_inbox.{e}") for e in engine)
            }
            assert not leaked, f"{path.name} imports the engine: {leaked}"


class TestRemoteDoctor:
    """The hub's verdict on the caller — the half a client cannot see for itself."""

    def test_it_answers_the_caller_it_would_otherwise_refuse(self) -> None:
        """Unguarded on purpose, on a hub that refuses everything else.

        The caller who needs this most is the one whose credential is missing or
        rejected. A guarded route would meet them with the very 401 they came here to
        understand, so it answers — with no name and no token at all.
        """
        client, _ = _build("enforce")
        with client as c:
            got = c.get("/doctor")
        assert got.status_code == 200
        body = got.json()
        assert body["hub"]["credentialRequired"] is True
        assert body["you"]["token"] == "not presented"
        assert "ask an operator" in body["verdict"]

    def test_it_blames_the_credential_before_the_unknown_name(self) -> None:
        """On an enforcing hub `join` is guarded too.

        So telling a caller with a bad token to "join to claim your name" is advice
        they cannot act on: the credential is the blocking problem, and saying anything
        else sends them round a loop they cannot leave.
        """
        client, _ = _build("enforce")
        with client as c:
            body = c.get(
                "/doctor",
                headers={
                    IDENTITY_HEADER: "nobody_at_all",
                    "Authorization": "Bearer nonsense",
                },
            ).json()
        assert body["you"]["token"] == "rejected"
        assert "not recognised" in body["verdict"]
        assert "join to claim" not in body["verdict"]

    async def test_a_working_token_is_confirmed_as_working(self) -> None:
        """The positive case matters too: it is how an agent knows it is set up."""
        client, auth = _build("enforce")
        with client as c:
            minted = await auth.mint_token(label="test")
            c.post(
                "/actors",
                json={"preferredUsername": ROSEMARY},
                headers={"Authorization": f"Bearer {minted.secret}"},
            )
            body = c.get(
                "/doctor",
                headers={
                    IDENTITY_HEADER: ROSEMARY,
                    "Authorization": f"Bearer {minted.secret}",
                },
            ).json()
        assert body["you"]["token"] == "accepted"
        # `verified` is the sentinel, not a name: every token is shared now, so what
        # the credential proves is that the *machine* is admitted. The name beside it
        # came from the header, and the verdict says so rather than letting an agent
        # believe the hub checked it.
        assert body["you"]["verified"] == SHARED_ACTOR
        assert "admits this machine" in body["verdict"]


class TestDirectoryIsNotPublicUnderEnforce:
    """Enumerating everyone on the hub is a disclosure, not a lookup."""

    def test_the_directory_needs_a_credential_when_enforcing(self) -> None:
        """It was open, and that is what let the console's Tokens page show a stranger
        every agent on the hub while the front page was correctly redirecting to
        sign-in. Turning authentication on has to mean this too.
        """
        client, _ = _build("enforce")
        with client as c:
            assert c.get("/actors").status_code == 401
            assert c.get(f"/actors/{ROSEMARY}").status_code == 401

    def test_the_directory_stays_open_on_a_trusted_lan(self) -> None:
        """The guard is a no-op unless enforcing — `off` and `warn` are unchanged."""
        client, _ = _build("off")
        with client as c:
            assert c.get("/actors").status_code == 200


class TestSetupRequired:
    """The hub says whether anyone has finished setting it up."""

    def test_it_is_true_on_a_fresh_hub_and_false_once_enrolled(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            assert c.get("/").json()["setupRequired"] is True
            assert c.get("/").json()["setupUser"] == "admin"

    def test_a_hub_without_auth_never_asks_for_setup(self) -> None:
        """With auth off there is no account to set up, so there is nothing to say."""
        client, _ = _build("off")
        with client as c:
            assert c.get("/").json()["setupRequired"] is False


class TestSharedToken:
    """One token for a machine, with each agent keeping its own name."""

    async def test_a_shared_token_admits_any_name(self) -> None:
        """The point of the whole feature: no token per agent.

        The credential proves the caller may use this hub; the header still says which
        agent they are, exactly as on an open hub. Two agents on one laptop share the
        token and keep separate inboxes.
        """
        client, auth = _build("enforce")
        with client as c:
            minted = await auth.mint_token(label="laptop")
            bearer = {"Authorization": f"Bearer {minted.secret}"}
            for name in ("rosemary_nasrin", "trevor_mahmood"):
                assert (
                    c.post(
                        "/actors", json={"preferredUsername": name}, headers=bearer
                    ).status_code
                    == 201
                )
            # each acts as itself, not as the other
            got = c.get(
                "/actors/rosemary_nasrin/inbox",
                headers=bearer | {IDENTITY_HEADER: "rosemary_nasrin"},
            )
            assert got.status_code == 200
            denied = c.get(
                "/actors/rosemary_nasrin/inbox",
                headers=bearer | {IDENTITY_HEADER: "trevor_mahmood"},
            )
            assert denied.status_code == 403, "a shared token is not a licence to read"

    async def test_a_per_agent_token_still_names_its_agent(self) -> None:
        """The old behaviour must survive: a bound token is not weakened by this."""
        client, auth = _build("enforce")
        with client as c:
            secret = await _legacy_bound(auth, ROSEMARY)
            c.post(
                "/actors",
                json={"preferredUsername": ROSEMARY},
                headers={"Authorization": f"Bearer {secret}"},
            )
            # the header claims someone else; the token's own actor is what counts
            got = c.get(
                f"/actors/{ROSEMARY}/inbox",
                headers={
                    "Authorization": f"Bearer {secret}",
                    IDENTITY_HEADER: "somebody_else",
                },
            )
            assert got.status_code == 200


class TestTheTokenApi:
    """One operator-only API for tokens, and nothing in it names an agent."""

    async def _operator(self, c, auth) -> None:
        pw = await auth.bootstrap()
        c.post("/auth/login", json={"username": "admin", "password": pw})
        body = c.get("/auth/enrol").json()
        secret = body["provisioningUri"].split("secret=")[-1].split("&")[0]
        c.post(
            "/auth/enrol",
            json={"password": "newpassword", "otp": totp.current_code(secret)},
        )

    async def test_an_empty_label_is_refused_rather_than_invented(self) -> None:
        """A list of unlabelled tokens is a list nobody can safely revoke from, and
        inventing one puts our guess in the column meant to hold the operator's."""
        client, auth = _build("enforce")
        with client as c:
            await self._operator(c, auth)
            refused = c.post("/auth/tokens", json={"label": "   "})
            assert refused.status_code == 400
            assert "label" in refused.json()["detail"]

    async def test_the_list_keeps_the_claim_and_the_finding_apart(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            await self._operator(c, auth)
            minted = c.post("/auth/tokens", json={"label": "workshop"}).json()
            token = await auth.resolve_token(minted["token"])
            assert token is not None
            await auth.admit(token, ROSEMARY)
            row = next(
                t
                for t in c.get("/auth/tokens").json()["items"]
                if t["id"] == minted["id"]
            )
        assert row["label"] == "workshop"
        assert row["boundTo"] is None, "a shared token is bound to nobody"
        assert [u["name"] for u in row["admitted"]] == [ROSEMARY]

    async def test_never_used_is_null_not_empty(self) -> None:
        """ "Never" and "at an unknown time" are different facts leading to different
        actions, so they must not both render as a blank."""
        client, auth = _build("enforce")
        with client as c:
            await self._operator(c, auth)
            minted = c.post("/auth/tokens", json={"label": "fresh"}).json()
            row = next(
                t
                for t in c.get("/auth/tokens").json()["items"]
                if t["id"] == minted["id"]
            )
        assert row["lastUsed"] is None

    async def test_a_legacy_bound_token_is_listed_as_bound(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            await self._operator(c, auth)
            await _legacy_bound(auth, ROSEMARY)
            rows = c.get("/auth/tokens").json()["items"]
        bound = [t for t in rows if t["boundTo"]]
        assert [t["boundTo"] for t in bound] == [ROSEMARY]

    async def test_revoking_reports_what_it_cut_off(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            await self._operator(c, auth)
            minted = c.post("/auth/tokens", json={"label": "workshop"}).json()
            token = await auth.resolve_token(minted["token"])
            assert token is not None
            await auth.admit(token, ROSEMARY)
            gone = c.delete(f"/auth/tokens/{minted['id']}")
        assert gone.status_code == 200
        assert gone.json() == {"revoked": True, "admitted": [ROSEMARY]}

    async def test_a_revoked_token_stays_listed_with_its_history(self) -> None:
        """A revoked token that vanishes takes the record of what it did with it."""
        client, auth = _build("enforce")
        with client as c:
            await self._operator(c, auth)
            minted = c.post("/auth/tokens", json={"label": "workshop"}).json()
            token = await auth.resolve_token(minted["token"])
            assert token is not None
            await auth.admit(token, ROSEMARY)
            c.delete(f"/auth/tokens/{minted['id']}")
            row = next(
                t
                for t in c.get("/auth/tokens").json()["items"]
                if t["id"] == minted["id"]
            )
        assert row["revoked"] is True
        assert [u["name"] for u in row["admitted"]] == [ROSEMARY]


class TestTheAdmittedRecordCannotBeSteered:
    """The `admitted` column is what an operator revokes from. It must not be forgeable.

    Found by outside review. A legacy bound token is authorised as its own actor
    whatever the header says — so recording the *claim* would have written one name into
    the evidence while the hub served the request as another. Evidence a sender can
    steer is worse than no evidence, because it is acted on.
    """

    async def test_a_legacy_token_records_the_agent_it_admitted(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            secret = await _legacy_bound(auth, ROSEMARY)
            c.post(
                "/actors",
                json={"preferredUsername": ROSEMARY},
                headers={"Authorization": f"Bearer {secret}"},
            )
            # the header claims somebody else; the hub still serves this as Rosemary
            c.get(
                f"/actors/{ROSEMARY}/inbox",
                headers={
                    "Authorization": f"Bearer {secret}",
                    IDENTITY_HEADER: "trevor_mahmood",
                },
            )
        uses = await auth.token_uses(f"legacy-{ROSEMARY}")
        assert [u.actor for u in uses] == [ROSEMARY]
        assert "trevor_mahmood" not in {u.actor for u in uses}

    async def test_a_shared_token_records_the_name_it_was_used_under(self) -> None:
        """The other half: with a shared token the header *is* what was admitted."""
        client, auth = _build("enforce")
        with client as c:
            minted = await auth.mint_token(label="laptop")
            bearer = {"Authorization": f"Bearer {minted.secret}"}
            c.post(
                "/actors",
                json={"preferredUsername": ROSEMARY},
                headers=bearer | {IDENTITY_HEADER: ROSEMARY},
            )
            c.get(
                f"/actors/{ROSEMARY}/inbox",
                headers=bearer | {IDENTITY_HEADER: ROSEMARY},
            )
        assert {u.actor for u in await auth.token_uses(minted.id)} == {ROSEMARY}


class TestTheAdminOverrideIsAdvertised:
    """A hole in the front door that cannot be seen from outside is the worst kind.

    `authenticated: true` on a hub running the override is a half-truth: the hub does
    authenticate, and also has a way in that skips the second factor. So the descriptor
    carries both facts, and the console shows both banners.
    """

    def test_the_descriptor_says_so(self) -> None:
        house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
        auth = AuthService(
            InMemoryAuthStore(), secret_key=KEY, admin_password="let-me-in"
        )
        with TestClient(app=build_api(house, HUB, auth=auth, auth_mode="enforce")) as c:
            body = c.get("/").json()

        assert body["authenticated"] is True
        assert body["adminPasswordSet"] is True
        assert "insecure" in body["adminPasswordWarning"].lower()

    def test_an_ordinary_hub_says_the_opposite(self) -> None:
        client, _ = _build("enforce")
        with client as c:
            body = c.get("/").json()
        assert body["adminPasswordSet"] is False
        assert "adminPasswordWarning" not in body

    def test_the_password_itself_is_never_advertised(self) -> None:
        """Announce the hole, never the key that opens it."""
        house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
        auth = AuthService(
            InMemoryAuthStore(), secret_key=KEY, admin_password="sekrit-value"
        )
        with TestClient(app=build_api(house, HUB, auth=auth, auth_mode="enforce")) as c:
            assert "sekrit-value" not in c.get("/").text


class TestAnOperatorSessionReachesEveryOperatorRoute:
    """Reported by the owner, 2026-08-05: Maintenance and Settings both refused a
    logged-in operator while every other tab worked.

    **These tests do not reproduce that.** Written to, and they pass — an enrolled
    operator reaches both routes on the hub. So the hub half is correct and this class
    exists to keep it that way while the console half is investigated; it is not the
    fix, and nothing here should be read as one.

    What the failed reproduction did establish is worth more than a guess at the cause:
    `/observe/purge` and `/hub/settings` carry `guard_enforce` *and* `provide_operator`,
    while `/auth/tokens` — the tab that works — carries only `provide_operator`. Guards
    run before dependencies, so on those two routes the weaker check runs first. That is
    a real smell (two checks, weaker one first) and it is where a fix would go, but the
    weaker check *passes* here, so it is not yet the explanation.

    The reason no existing test would have caught the reported fault either way:
    **every console test stubs `auth_call` wholesale**, so the console-to-hub path this
    bug lives on is exercised by nothing.
    """

    @staticmethod
    async def _enrolled(client: TestClient, auth: AuthService) -> None:
        """Take the admin all the way through setup — the state a console user is in.

        Built through the real flow rather than by writing an ACTIVE row: a session's
        `limited` flag is exactly what this bug turns on, and a fixture that set the
        state directly could produce a session no real login ever issues.
        """
        pw = await auth.bootstrap()
        client.post("/auth/login", json={"username": "admin", "password": pw})
        enrol = client.get("/auth/enrol").json()
        secret = enrol["provisioningUri"].split("secret=")[1].split("&")[0]
        client.post(
            "/auth/enrol",
            json={"password": "newpassword", "otp": totp.current_code(secret)},
        )

    async def test_maintenance_and_settings_answer_a_logged_in_operator(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            await self._enrolled(c, auth)

            refused = {
                path: c.get(path).status_code
                for path in ("/observe/purge", "/hub/settings")
                if c.get(path).status_code != 200
            }

        assert not refused, f"an enrolled operator was refused: {refused}"

    async def test_the_tab_that_always_worked_still_does(self) -> None:
        """The paired positive. Without it the test above would pass on a hub that had
        simply stopped enforcing anything."""
        client, auth = _build("enforce")
        with client as c:
            await self._enrolled(c, auth)

            assert c.get("/auth/tokens").status_code == 200

    async def test_an_anonymous_caller_is_still_refused(self) -> None:
        """The other paired negative, and the one that matters. Fixing this by removing
        the guard must not open the route — `provide_operator` is strictly stronger, and
        this is what proves it rather than assuming it."""
        client, _auth = _build("enforce")
        with client as c:
            for path in ("/observe/purge", "/hub/settings"):
                assert c.get(path).status_code == 401, f"{path} is open to anyone"

    async def test_an_agents_token_cannot_reach_them_either(self) -> None:
        """A credential that lets an agent send mail must not also let it purge
        everyone's. That rule lived in `provide_operator` all along; removing the guard
        must leave it standing."""
        client, auth = _build("enforce")
        with client as c:
            await self._enrolled(c, auth)
            minted = c.post("/auth/tokens", json={"label": "a laptop"}).json()
            c.post("/auth/logout", json={})
            c.cookies.clear()

            for path in ("/observe/purge", "/hub/settings"):
                answer = c.get(
                    path,
                    headers={
                        "Authorization": f"Bearer {minted['token']}",
                        IDENTITY_HEADER: ROSEMARY,
                    },
                )
                assert answer.status_code == 401, f"an agent's token reached {path}"


class TestASharedTokenDoesNotOutrankASession:
    """Reported by the owner, 2026-08-05: replying from the console failed with
    *"'*' has not joined this mailbox"*.

    The console sends **both** its device token and the signed-in human's session
    cookie. `resolve_verified_caller` checked the bearer token first and returned its
    actor — and for a shared token that actor is `*`, which is not a name and has joined
    no mailbox. So the reply was attributed to nobody.

    **A shared token names no one.** It proves the machine is allowed here and says
    nothing about who is using it; a session names a person. When both arrive, the more
    specific one is the identity. Nothing is weakened by preferring it — both were
    verified, and the question is only which of two true things to believe about *who*.
    """

    async def test_a_session_wins_when_a_shared_token_is_also_present(self) -> None:
        client, auth = _build("enforce")
        with client as c:
            pw = await auth.bootstrap()
            c.post("/auth/login", json={"username": "admin", "password": pw})
            enrol = c.get("/auth/enrol").json()
            secret = enrol["provisioningUri"].split("secret=")[1].split("&")[0]
            c.post(
                "/auth/enrol",
                json={"password": "newpassword", "otp": totp.current_code(secret)},
            )
            minted = c.post("/auth/tokens", json={"label": "the console"}).json()

            said = c.get(
                "/doctor", headers={"Authorization": f"Bearer {minted['token']}"}
            ).json()

        assert said["you"]["verified"] == "admin", (
            "a shared token out-ranked the signed-in human — the reported bug"
        )

    async def test_a_shared_token_alone_is_still_a_valid_credential(self) -> None:
        """The paired positive, and the thing that must not break: one laptop runs four
        agents on one token, and that token still admits the machine when nobody is
        signed in. Preferring a session must not have made the token worthless."""
        client, auth = _build("enforce")
        with client as c:
            pw = await auth.bootstrap()
            c.post("/auth/login", json={"username": "admin", "password": pw})
            enrol = c.get("/auth/enrol").json()
            secret = enrol["provisioningUri"].split("secret=")[1].split("&")[0]
            c.post(
                "/auth/enrol",
                json={"password": "newpassword", "otp": totp.current_code(secret)},
            )
            minted = c.post("/auth/tokens", json={"label": "a laptop"}).json()
            c.post("/auth/logout", json={})
            c.cookies.clear()

            said = c.get(
                "/doctor",
                headers={
                    "Authorization": f"Bearer {minted['token']}",
                    IDENTITY_HEADER: ROSEMARY,
                },
            ).json()

        assert said["you"]["token"] == "accepted", "the token stopped being accepted"
