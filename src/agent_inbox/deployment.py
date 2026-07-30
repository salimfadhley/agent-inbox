"""Proving a deployment actually took — the checks, with no deployment in them.

**A deploy is not successful until the running service proves it.**

That sentence is the whole of this module, and it was written after two consecutive
releases went wrong in ways nothing reported:

- `v0.31.0` — the deploy API returned `200` while the hub kept running a version **five
  releases old**. Success and failure were indistinguishable.
- `v0.31.1` — the deploy returned `500`, left both containers *created but not started*,
  and took the hub **down** while still looking deployed.

Both were caught by a human remembering to check afterwards. A runbook would not have
helped: nobody skipped a step, and a perfect checklist still reads that `200` and moves
on. What was missing is a definition of "succeeded" that does not come from the thing
being
asked to deploy.

**Nothing here knows how to deploy anything**, deliberately. How a particular hub is
deployed — the platform, the host, the app names — is deployment-specific and belongs
outside this project. What belongs *in* it is the question every operator has to answer
afterwards: is the service actually running what I just released, and is it telling the
truth about itself?
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

#: How long to wait for a hub that may be starting up.
TIMEOUT_SECONDS = 20

#: The two openers of the onboarding prompt's auth caution. These are a **contract**,
#: not
#: incidental prose: a host checking that a hub's prompt agrees with its descriptor has
#: nothing else stable to match on, and `tests/test_prompts.py` pins them so they cannot
#: drift silently.
OPEN_OPENER = "**This mailbox does not authenticate.**"
AUTHENTICATED_OPENER = "**This mailbox authenticates.**"


@dataclass
class Check:
    """One thing that had to be true."""

    name: str
    ok: bool
    #: What was actually observed. Shown either way — it is the evidence.
    found: str = ""
    #: Why it failed. Shown **only** on failure: printing "why this is wrong" beside a
    #: passing check reads as a contradiction, which the first version of this did.
    detail: str = ""

    def __str__(self) -> str:
        mark = "ok  " if self.ok else "FAIL"
        line = f"  {mark}  {self.name}"
        if self.found:
            line += f" — {self.found}"
        if not self.ok and self.detail:
            line += f" ({self.detail})"
        return line


@dataclass
class Report:
    """What a target proved, or failed to."""

    target: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, found: str = "", detail: str = "") -> None:
        self.checks.append(Check(name, ok, found, detail))


def _get(url: str, timeout: int = TIMEOUT_SECONDS) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read(512 * 1024)
    except urllib.error.HTTPError as refused:
        return refused.code, b""
    except OSError as unreachable:
        raise ConnectionError(str(unreachable)) from unreachable


def verify(
    hub_url: str,
    expect_version: str = "",
    prompt_url: str = "",
) -> Report:
    """Ask a running hub to prove what it is.

    *expect_version* is the release that was supposed to land. Empty means "do not
    care",
    which is useful for checking a hub is healthy without asserting which version — but
    a
    deploy should always pass it, because **the version check is the one that catches a
    deploy that silently did nothing**.

    *prompt_url* is where the onboarding prompt is served, usually the console rather
    than
    the hub. Given, it adds the invariant that the prompt's auth caution agrees with the
    hub's own `authenticated` field — the disagreement that shipped undetected in
    v0.31.0
    and was found from live use rather than by any test.
    """
    report = Report(target=hub_url)

    try:
        status, body = _get(hub_url.rstrip("/") + "/")
    except ConnectionError as unreachable:
        # The failure that matters most, and the one a deploy API will not report: the
        # hub is not there at all. v0.31.1 left it in exactly this state.
        report.add("reachable", False, detail=str(unreachable))
        return report

    if status != 200:
        report.add("reachable", False, detail=f"HTTP {status}")
        return report
    report.add("reachable", True)

    try:
        descriptor = json.loads(body or b"{}")
    except ValueError:
        report.add(
            "descriptor is JSON", False, detail="the hub answered, but not with JSON"
        )
        return report

    version = str(descriptor.get("version", ""))
    authenticated = bool(descriptor.get("authenticated"))
    report.add("reports a version", bool(version), version or "none given")

    if expect_version:
        report.add(
            f"running {expect_version}",
            version == expect_version,
            detail=f"found {version or 'unknown'}",
        )

    if prompt_url:
        try:
            prompt_status, prompt_body = _get(prompt_url)
        except ConnectionError as unreachable:
            report.add("prompt reachable", False, detail=str(unreachable))
            return report
        if prompt_status != 200:
            report.add("prompt reachable", False, detail=f"HTTP {prompt_status}")
            return report

        prompt = prompt_body.decode("utf-8", "replace")
        wanted = AUTHENTICATED_OPENER if authenticated else OPEN_OPENER
        unwanted = OPEN_OPENER if authenticated else AUTHENTICATED_OPENER

        # **The invariant, not a word search.** "Does the caution mention
        # authentication"
        # would pass on a hub whose descriptor had drifted the other way; what must hold
        # is that the prompt and the descriptor *agree*.
        report.add(
            f"prompt caution matches authenticated={authenticated}",
            wanted in prompt and unwanted not in prompt,
            detail="the prompt contradicts the hub's own descriptor",
        )

    return report


def verify_all(
    targets: list[tuple[str, str]],
    expect_version: str = "",
) -> tuple[list[Report], bool]:
    """Verify several hubs, and say whether **every** one proved itself.

    *targets* is a list of `(hub_url, prompt_url)`; an empty prompt_url skips that
    check.

    Returns every report rather than stopping at the first failure, because "which of my
    hubs is wrong" is the question an operator actually has, and a run that stops early
    answers a different one.
    """
    reports = [verify(hub, expect_version, prompt) for hub, prompt in targets]
    return reports, all(r.ok for r in reports)
