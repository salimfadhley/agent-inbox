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
