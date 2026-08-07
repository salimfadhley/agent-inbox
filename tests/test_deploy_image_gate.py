"""A release must not report success over a registry it never wrote (issue #39).

The image workflow treated Docker Hub as a bonus — missing credentials skipped the push
rather than failing it — while `docker-compose.yml` pulls from exactly that registry. So
a release could pass every gate, report success, and leave every deploy pulling a stale
image, with nothing red at any point.

Found by an outside model review during the Python 3.14 floor move, and reproduced by
reading. It had not bitten yet, which is the only reason it was an issue rather than an
incident — the same shape had already produced one, when a deploy reported success over
a hub five releases behind.

The lesson each time is the same and is what these tests hold: **a step that cannot run
must fail, not pass.**
"""

import pytest

from agent_inbox.exceptions import ReleaseGateError
from agent_inbox.release_gate import (
    ALL_CHECKS,
    CHECK_DEPLOY_IMAGE,
    DEFAULT_CHECKS,
    main,
    verify_deploy_image,
)

REPO = "an-account/an-image"


def _answers(*statuses: int) -> tuple[object, list[str]]:
    """A registry that returns each status in turn, then repeats the last."""
    seen: list[str] = []
    remaining = list(statuses)

    def fetch(url: str, timeout: float) -> int:
        seen.append(url)
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return fetch, seen


class TestTheTagMustActuallyBeServed:
    def test_a_served_tag_passes(self) -> None:
        """The paired positive. A gate that failed regardless would block every release
        and be removed within a day, which is not the same as being correct."""
        fetch, seen = _answers(200)

        verify_deploy_image(REPO, "1.2.3", timeout=5, fetch=fetch)  # type: ignore[arg-type]

        assert seen and "1.2.3" in seen[0]

    def test_a_missing_tag_fails(self) -> None:
        """The bug, stated: the push did not land, and the release must not be green."""
        fetch, _ = _answers(404)

        with pytest.raises(ReleaseGateError, match="not being served"):
            verify_deploy_image(
                REPO,
                "1.2.3",
                timeout=5,
                attempts=2,
                delay=0,
                sleep=lambda _: None,
                fetch=fetch,  # type: ignore[arg-type]
            )

    def test_the_failure_says_what_it_would_cost(self) -> None:
        """ "Not found" is a fact; "a deploy would silently get an older image" is the
        reason anybody should care, and the reason not to re-run until it goes green."""
        fetch, _ = _answers(404)

        with pytest.raises(ReleaseGateError) as raised:
            verify_deploy_image(
                REPO,
                "1.2.3",
                timeout=5,
                attempts=1,
                delay=0,
                sleep=lambda _: None,
                fetch=fetch,  # type: ignore[arg-type]
            )

        assert "older image" in str(raised.value)

    def test_a_tag_that_appears_late_still_passes(self) -> None:
        """A push is not instantly visible: the registry accepts a manifest and takes a
        moment to serve it. A gate that failed on that would be a flake, and a flaky
        gate teaches everyone to re-run gates until they go green — which is how a real
        failure gets waved through."""
        fetch, seen = _answers(404, 404, 200)

        verify_deploy_image(
            REPO,
            "1.2.3",
            timeout=5,
            attempts=5,
            delay=0,
            sleep=lambda _: None,
            fetch=fetch,  # type: ignore[arg-type]
        )

        assert len(seen) == 3

    def test_an_unreachable_registry_is_retried_not_believed(self) -> None:
        """A DNS blip mid-release is a not-yet, not a verdict. Reporting the image
        missing because the network hiccuped would fail a good release; reporting it
        present would be far worse, and neither happens — it is simply asked again."""
        fetch, seen = _answers(0, 200)

        verify_deploy_image(
            REPO,
            "1.2.3",
            timeout=5,
            attempts=3,
            delay=0,
            sleep=lambda _: None,
            fetch=fetch,  # type: ignore[arg-type]
        )

        assert len(seen) == 2


class TestTheGateRefusesToGuess:
    def test_it_is_not_a_default_check(self) -> None:
        """It needs an image reference, which is deployment-specific. Defaulting it
        would put a registry name in this repository, which the charter forbids — and
        would make the gate check whichever one somebody guessed."""
        assert CHECK_DEPLOY_IMAGE in ALL_CHECKS
        assert CHECK_DEPLOY_IMAGE not in DEFAULT_CHECKS

    def test_asking_for_it_without_an_image_fails(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Refused rather than skipped — which is the entire point of the issue. A
        deploy-image check that quietly did nothing when unconfigured would be the same
        bug wearing the costume of its own fix.

        **Asserted on the message, not only the exit code**, and that distinction was
        earned: the first version of this test checked `code != 0` alone, and the
        removal proof showed it still passing with the guard deleted — because the
        gate then formatted a URL containing `None`, asked a real registry ten times
        over four minutes, got 404 and returned 1. Right answer, wrong reason, and it
        would have gone on passing after the refusal was removed.
        """
        with caplog.at_level("ERROR"):
            code = main(["--check", CHECK_DEPLOY_IMAGE, "--version", "1.2.3"])

        assert code == 1
        assert "--image is required" in caplog.text

    def test_the_refusal_costs_no_network_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half of the same lesson. A guard that refuses *after* asking the
        registry is not a guard, and the exit code cannot tell the two apart."""
        from agent_inbox import release_gate

        def _never(url: str, timeout: float) -> int:
            raise AssertionError(f"the registry was asked about {url!r}")

        monkeypatch.setattr(release_gate, "_tag_status", _never)

        assert main(["--check", CHECK_DEPLOY_IMAGE, "--version", "1.2.3"]) == 1


class TestTheWorkflowRequiresItOnARelease:
    """The gate is only half of it: something has to fail when the credentials are
    absent, because with no credentials there is no push to verify."""

    def _workflow(self) -> str:
        from pathlib import Path

        return Path(".github/workflows/docker.yml").read_text()

    def test_a_release_without_dockerhub_credentials_fails(self) -> None:
        text = self._workflow()

        assert "Docker Hub is required for a release" in text
        assert (
            "steps.kind.outputs.release == 'true' && env.HAS_DOCKERHUB != 'true'"
            in (text)
        )

    def test_a_main_build_may_still_skip(self) -> None:
        """The paired positive, and a deliberate asymmetry: nothing deploys `:edge`,
        so requiring credentials on every merge would block contributors and buy
        nothing."""
        text = self._workflow()

        guard = text.split("Docker Hub is required for a release", 1)[1]
        assert "release == 'true'" in guard.split("run:", 1)[0]

    def test_the_release_proves_the_tag_afterwards(self) -> None:
        text = self._workflow()

        assert "--check deploy-image" in text
        assert "Prove the registry a deploy pulls is serving this release" in text
