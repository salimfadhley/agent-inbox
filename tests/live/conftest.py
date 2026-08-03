"""What kind of hub is this, and what may we therefore assert?

The defect this mission fixes is a **missing entity**. `test_live_smoke.py` had no
representation of the hub's authentication posture, so the answer was hardcoded as an
assumption and every assertion inherited it — which is why pointing the suite at a
hub that enforces authentication made most of it fail for reasons unrelated to the
deployment being broken. Both of our hubs now enforce.

So: one probe, once per run, and everything else keys off it.

Deliberately stdlib-only, like the suite it serves — this module must import and skip
cleanly on a machine with none of the client extras installed.
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum

import pytest

HUB = os.environ.get("LIVE_HUB_URL")
TIMEOUT = 15


class AuthMode(StrEnum):
    """What the hub says it requires.

    **A closed set of two, not a boolean**, so a third state cannot arrive silently —
    and so a failure message can name the mode it assumed rather than print `False`.

    `warn` is deliberately absent. Its caller-facing semantics are an open question in
    `auth-mode-truthful-error-text-01KYJZ81`, and modelling it here would encode a guess
    that later has to be found and unpicked.
    """

    OPEN = "open"
    ENFORCING = "enforcing"


@dataclass(frozen=True, slots=True)
class HubDescriptor:
    """What the hub says about itself, fetched once from `GET /`."""

    name: str
    version: str
    authenticated: bool
    note: str

    @property
    def mode(self) -> AuthMode:
        return AuthMode.ENFORCING if self.authenticated else AuthMode.OPEN

    def assuming(self, what: str) -> str:
        """A failure message that says which hub, and what was assumed of it (NFR-002).

        A wrong assumption has to be diagnosable from the failure alone. Without it the
        output says an assertion failed and leaves the reader to work out whether the
        hub was broken or the suite was pointed at the wrong kind — precisely the
        confusion this mission exists to end.
        """
        return (
            f"{what}\n"
            # "an" is right for both members, and always will be while the set is
            # closed at open/enforcing — which `AuthMode` exists to keep it.
            f"  assumed: an {self.mode.value} hub "
            f"(GET / said authenticated={self.authenticated})\n"
            f"  hub:     {self.name} {self.version} at {HUB}"
        )


@pytest.fixture(scope="session")
def hub(pytestconfig: pytest.Config) -> HubDescriptor:
    """The hub's own account of itself. One fetch per run.

    **A failed probe stops the run**, naming the url it tried. It does not fall back to
    a default: a default is exactly the bug being fixed, and it would then be invisible,
    because the suite would look like it was working while asserting against a hub that
    might be nothing like the one it assumed.

    Stopping beats erroring every test. Eleven failures that each describe the wrong
    problem are worse than one line saying the hub could not be reached.
    """
    assert HUB, "LIVE_HUB_URL is unset; the suite should have skipped"
    request = urllib.request.Request(f"{HUB}/", method="GET")  # noqa: S310 - configured
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            body = json.loads(response.read() or b"{}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        pytest.exit(
            f"cannot read the hub descriptor at {HUB}/ — {exc}. "
            "Every live assertion needs it as its premise, so nothing here can run. "
            "Check LIVE_HUB_URL and that the hub is up.",
            returncode=1,
        )

    if not isinstance(body, dict):
        pytest.exit(f"{HUB}/ did not return a JSON object", returncode=1)

    return HubDescriptor(
        name=str(body.get("name", "")),
        version=str(body.get("version", "")),
        # Absent means open: a hub too old to advertise the field predates enforcement.
        authenticated=bool(body.get("authenticated", False)),
        note=str(body.get("note", "")),
    )


@pytest.fixture(scope="session")
def mode(hub: HubDescriptor) -> AuthMode:
    """Shorthand, because most tests want the mode rather than the whole descriptor."""
    return hub.mode


#: What an *anonymous* request to a protected route should get, per mode.
#:
#: This is the table the suite lacked. Every assertion that used to hardcode a success
#: code was asserting "this hub is open" without saying so, and inherited that belief
#: from nowhere in particular.
def anonymous_status(mode: AuthMode, when_open: int) -> int:
    """The status an uncredentialled caller should see on a protected route.

    On an enforcing hub a `401` is the hub **working**, not failing — which is the whole
    confusion this mission exists to remove.
    """
    return 401 if mode is AuthMode.ENFORCING else when_open


#: A credential for the enforcing case, when one has been supplied (WP03 provides it).
#: Absent is a legitimate state: the suite then asserts refusals rather than the loop.
TOKEN = os.environ.get("LIVE_TOKEN", "").strip()


def bearer(credential: str) -> dict[str, str]:
    """Headers for a credential, or nothing at all. One source, so a token that was
    obtained cannot fail to be used — which is how an enforcing pass silently becomes a
    duplicate of the open one."""
    return {"Authorization": f"Bearer {credential}"} if credential else {}


def pytest_sessionfinish(session, exitstatus) -> None:
    """A run where nothing ran must not report a pass (FR-006).

    This is the shape this project keeps paying for: a check that passed because it had
    nothing to look at. A smoke job whose credentials were missing, whose console url
    was unset, or which was pointed at a hub it could not use, reports green in the same
    words as one that proved the deployment works — and green is what a human reads.

    Only when `LIVE_HUB_URL` was set. Without it the suite is *meant* to skip, and an
    ordinary `pytest` run must stay silent.
    """
    if not HUB or exitstatus != 0:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:  # pragma: no cover - only without the terminal plugin
        # Refuse rather than disable silently. A guard that switches itself off when it
        # cannot see is the same failure it was written to catch.
        session.exitstatus = 1
        return
    passed = len(reporter.stats.get("passed", []))
    skipped = len(reporter.stats.get("skipped", []))
    # **A known limit, stated rather than papered over.** This counts any pass, so one
    # trivially-green test — `test_health_answers` answers on every hub — makes a run
    # look substantive even if everything meaningful skipped. Raising the bar reliably
    # means naming the tests that constitute a real exercise, which is a list that rots.
    # `LIVE_REQUIRE_AUTH` is the sharper instrument and is what CI uses; this remains
    # the floor. Found by an outside review.
    if passed:
        if skipped:
            reporter.write_line(
                f"live: {passed} ran, {skipped} skipped — set LIVE_CONSOLE_URL / "
                "LIVE_AUTH / LIVE_TOKEN to cover the rest",
                yellow=True,
            )
        return
    reporter.write_line(
        f"live: nothing ran against {HUB} — {skipped} skipped. Not a pass: "
        "the deployment was not exercised at all.",
        red=True,
    )
    session.exitstatus = 1


# -- WP03: a credential, obtained without a stored secret -------------------

#: The low-security override. Set on a *throwaway* hub, `admin` signs in with it and no
#: second factor, so CI needs neither a repository credential nor a configured secret.
ADMIN_PASSWORD = os.environ.get("LIVE_ADMIN_PASSWORD", "").strip()


def _form_post(path: str, fields: dict[str, str]) -> tuple[int, str, str]:
    """POST JSON and return (status, body, session-cookie)."""
    request = urllib.request.Request(  # noqa: S310 - configured hub url
        f"{HUB}{path}", data=json.dumps(fields).encode(), method="POST"
    )
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            cookie = response.headers.get("Set-Cookie", "") or ""
            return response.status, response.read().decode(errors="replace"), cookie
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read().decode(errors="replace"), ""


@pytest.fixture(scope="session")
def credential(hub: HubDescriptor) -> str:
    """A bearer token for an enforcing hub, or `""` when none is available.

    Three sources, in order of preference:

    1. **`LIVE_TOKEN`** — somebody already minted one. Used as given.
    2. **`LIVE_ADMIN_PASSWORD`** — the v0.23.0 override. Sign in as `admin` with no
       second factor and mint a token. This replaced a six-step chain (scrape the
       password from the container log, fetch a TOTP secret, compute a code, enrol,
       open a session, mint) and with it the whole class of risk that made this the
       mission's most dangerous package.
    3. **Nothing** — a legitimate state. The suite then asserts refusals rather than
       the loop, and says what it did not run.

    **Never a secret from the repository** (FR-005, FR-008). Both inputs are
    environment-only, and the hub CI uses them against is created for the run and
    destroyed with it.
    """
    if TOKEN:
        return TOKEN
    if hub.mode is not AuthMode.ENFORCING or not ADMIN_PASSWORD:
        return ""

    # FR-012: a hub running the override is **not** fully secured, and using it while
    # reporting the hub as enforcing would be exactly the false claim this mission
    # exists to stop. Assert the hub admits it before relying on it.
    assert _advertises_override(), (
        "LIVE_ADMIN_PASSWORD was supplied but the hub does not advertise "
        "adminPasswordSet. Either it is not the hub you think, or it is more secure "
        "than the credential assumes — and CI would be validating a different hub "
        "than the one it claims to test."
    )

    status, body, cookie = _form_post(
        "/auth/login", {"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert status == 200, hub.assuming(f"admin sign-in gave {status}: {body[:200]}")

    session = cookie.split(";")[0] if cookie else ""
    assert session, hub.assuming("sign-in returned no session cookie")

    minted = urllib.request.Request(  # noqa: S310 - configured hub url
        f"{HUB}/auth/tokens",
        data=json.dumps({"label": "live smoke suite"}).encode(),
        method="POST",
    )
    minted.add_header("Content-Type", "application/json")
    minted.add_header("Cookie", session)
    try:
        with urllib.request.urlopen(minted, timeout=TIMEOUT) as response:  # noqa: S310
            token = str(json.loads(response.read()).get("token", ""))
    except urllib.error.HTTPError as refused:
        raise AssertionError(
            hub.assuming(f"minting a token gave {refused.code}: {refused.read()[:200]}")
        ) from refused

    assert token, hub.assuming("the mint route returned no token")
    return token


def _advertises_override() -> bool:
    request = urllib.request.Request(f"{HUB}/", method="GET")  # noqa: S310
    request.add_header("Accept", "application/json")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        return bool(json.loads(response.read() or b"{}").get("adminPasswordSet"))


#: Set by CI's enforcing pass. Turns "we happened to run unauthenticated" from a quiet
#: outcome into a failure (FR-010).
REQUIRE_AUTH = os.environ.get("LIVE_REQUIRE_AUTH", "").strip()


@pytest.fixture(scope="session", autouse=True)
def _the_enforcing_pass_must_actually_enforce(
    hub: HubDescriptor, credential: str
) -> None:
    """FR-010. Without this the second CI pass could be a duplicate of the first.

    A credential that turns out not to be needed, or a hub that quietly came up open,
    would leave the enforcing pass asserting exactly what the open pass already proved —
    while its name, and its green tick, claim something more.

    Only when `LIVE_REQUIRE_AUTH` is set, so a human pointing the suite at whatever they
    have to hand is not nagged.
    """
    if not REQUIRE_AUTH:
        return
    assert hub.mode is AuthMode.ENFORCING, hub.assuming(
        "LIVE_REQUIRE_AUTH is set, but this hub does not enforce authentication — "
        "the pass would duplicate the open one while claiming to test enforcement"
    )
    assert credential, hub.assuming(
        "LIVE_REQUIRE_AUTH is set, but no credential was obtained — every "
        "authenticated assertion would skip and the run would still report green"
    )
