"""No deployment-specific hosts, addresses or credentials in the repository.

`agent-inbox` is generic, releasable infrastructure. Anything naming one particular
installation is two faults at once: it tells a reader about somebody's private network,
and it makes a general-purpose project read as though it were written for one site.

**Attention does not scale, which is why this is a test.** On 2026-08-03 two real
hostnames went into a `console.py` docstring and survived four gates, two outside model
reviews and a release. They were found by auditing the charter against the code by hand
— an act nobody performs on a schedule.

## How it works, and why this way round

It does not try to recognise a *bad* hostname; there is no such list. It finds every
host-shaped string on the shipped surfaces and requires each one to be **reserved for
documentation, or the project's own**. Anything else fails, and adding a genuinely new
example means adding it here — one line, and a moment's thought about whether it should
be `example.com` instead.

**Agent handles need no exemption.** They are not host-shaped, so the charter's
carve-out for `ludmila_coe` and friends costs nothing here: never matched.
"""

import ipaddress
import re
from contextlib import suppress
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: What ships, or is read by somebody deciding how to run this.
#:
#: Dated narrative — session logs, handovers, mission write-ups — is deliberately out of
#: scope. Those are records of what happened on particular days, and a record that named
#: a host at the time is evidence rather than instruction. They are also, today, clean.
SURFACES = (
    "src",
    "tests",
    "doc/decisions",
    "doc/runbook",
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "Dockerfile",
    "pyproject.toml",
)

#: Reserved for documentation and examples, by RFC 2606 and RFC 6761. These can never
#: belong to anybody, which is the entire point of using them.
RESERVED = (
    ".invalid",
    ".example",
    "example.com",
    "example.org",
    "example.net",
    ".localhost",
    "localhost",
    ".test",
)


#: Addresses that identify nobody: a bind address is not a deployment, link-local is
#: not routable, and RFC 5737 reserves three ranges precisely so documentation has
#: addresses it may print.
def _identifies_nobody(address: ipaddress.IPv4Address) -> bool:
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or any(
            address in ipaddress.IPv4Network(net)
            for net in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
        )
    )


#: The project's own published locations, and the specifications it implements. These
#: name *agent-inbox*, not anybody's installation of it — the same reason the repository
#: url has always been in the console footer.
OURS = (
    "github.com/salimfadhley/agent-inbox",
    "salimfadhley.github.io/agent-inbox",
    "pypi.org",
    "hub.docker.com",
    "ghcr.io",
    "docs.astral.sh",
    "astral.sh",
    "w3.org",
    "www.w3.org",
    "nodeinfo.diaspora.software",
    "docs.github.com",
    "json-schema.org",
    "schema.org",
    "creativecommons.org",
    "gnu.org",
    "www.gnu.org",
    "spdx.org",
    "python.org",
    "docs.python.org",
    "packaging.python.org",
    "peps.python.org",
    "datatracker.ietf.org",
    "www.rfc-editor.org",
    "rfc-editor.org",
    "docs.pytest.org",
    "fly.io",
    "litestar.dev",
    "modelcontextprotocol.io",
    # README badges. A service the project's own README renders through, not a
    # deployment of anything.
    "img.shields.io",
)

#: Addresses that illustrate an attack rather than name a host.
#:
#: `peers.py` explains SSRF by describing a peer that answers
#: `302 Location: http://10.0.0.5:8080/` and so "reaches whatever is on the internal
#: network". **That has to be a private address** — the danger is precisely that it is
#: routable inside and not outside, and RFC 5737's documentation ranges are neither.
#: Substituting one would make the example wrong in order to make this test quiet.
#:
#: Listed literally rather than by range, so a *new* private address still fails.
ILLUSTRATIONS = {"10.0.0.5"}

#: Documented placeholders. A worked example needs *a* name, and these are the ones this
#: project has chosen to use where a reader must substitute their own.
PLACEHOLDERS = ("mail-host.local", "your-hub", "<host>", "<your-hub>", "hub.example")

#: Top-level domains a leaked hostname plausibly ends in, plus `.local` for mDNS.
#:
#: A list rather than "any dotted string", because the alternative flags every filename
#: in the repository — `client.py`, `pyproject.toml`, `README.md` all look like hosts to
#: a naive pattern, and a guard that reports those is one nobody reads.
#: Deliberately excludes the short ones that collide with ordinary Python attribute
#: access — `record.to`, `logger.info`, `client.app`, `guard.sh` all read as hostnames
#: to a pattern that accepts `.to`, `.info`, `.app` or `.sh`. Thirteen such false
#: positives appeared the first time this ran, which is how a guard becomes noise.
#: A leak using one of those TLDs would be missed; a guard nobody reads misses all of
#: them.
_TLDS = (
    "com|org|net|io|dev|cloud|xyz|biz|site|online|tech"
    "|uk|de|fr|nl|eu|us|ca|au|nz|ie|es|se|fi|pl|ch"
    "|local|localhost|internal|lan|home|invalid|example|test"
)

#: A url's host, or a bare hostname in prose.
#:
#: **Prose matters as much as code.** The leak that prompted this was two hostnames in a
#: docstring — `hub.stodge.org` and `api.hub.stodge.org` — written as ordinary words
#: rather than as urls. A guard that only read `https://…` would have passed it, which
#: is to say it would have been decoration.
#:
#: **Only multi-label names are judged.** A single label — `http://new:8081`,
#: `http://agent-mailbox:8080` — is a test fixture or a container service name, and
#: flagging every one would bury the real thing. That is a deliberate hole: a hub
#: genuinely called `halob`, with no domain, passes. The names worth leaking are the
#: ones that resolve.
_HOST = re.compile(
    r"https?://(?P<url>[A-Za-z0-9._~-]*\.[A-Za-z0-9._~-]+)"
    rf"|(?<![\w./-])(?P<bare>[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:{_TLDS}))(?![\w-])"
)

_IPV4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])")


def _allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    with suppress(ValueError):
        return _identifies_nobody(ipaddress.IPv4Address(host)) or host in ILLUSTRATIONS
    if any(host == r.lstrip(".") or host.endswith(r) for r in RESERVED):
        return True
    if any(host.startswith(p.lower()) or p.lower() in host for p in PLACEHOLDERS):
        return True
    return any(host == o or host.endswith("." + o) or o.startswith(host) for o in OURS)


def _files() -> list[Path]:
    found: list[Path] = []
    for entry in SURFACES:
        path = ROOT / entry
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found += [
                p
                for p in path.rglob("*")
                if p.is_file()
                and p.suffix in {".py", ".md", ".toml", ".yml", ".yaml", ""}
                and "__pycache__" not in p.parts
                and p.name != Path(__file__).name
            ]
    return found


def _offences(text: str) -> list[str]:
    bad: list[str] = []
    for match in _HOST.finditer(text):
        host = match.group("url") or match.group("bare")
        if host and not _allowed(host):
            bad.append(host)
    for match in _IPV4.finditer(text):
        raw = match.group(1)
        try:
            address = ipaddress.IPv4Address(raw)
        except ValueError:
            continue  # a version number, a percentage, something that is not an address
        if _identifies_nobody(address) or raw in ILLUSTRATIONS:
            continue
        if address.is_private or address.is_global:
            bad.append(raw)
    return bad


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_deployment_specific_host_or_address(path: Path) -> None:
    """One test per file, so a failure names the file rather than the haystack."""
    offences = sorted(
        set(_offences(path.read_text(encoding="utf-8", errors="replace")))
    )
    assert not offences, (
        f"{path.relative_to(ROOT)} names {', '.join(offences)}.\n"
        "This project is generic, releasable infrastructure: no deployment-specific "
        "hostnames, addresses, organisation names or credentials in code, docs or "
        "tests.\n"
        "Use a reserved name — example.com, *.invalid, *.localhost — or a documented "
        "placeholder. If this really is the project's own published location, add "
        "it to OURS in this file and say why."
    )


def test_the_guard_can_actually_fail() -> None:
    """The guard's own premise. A detector that matches nothing passes everything.

    Every other test here asserts an absence, and an absence is exactly what a broken
    regex produces. This is the paired positive for all of them.
    """
    assert _offences("see https://internal-hub.corp.example-company.io"), (
        "a real-looking host was not detected"
    )
    # The founding case, in prose rather than as a url — a docstring, which is where it
    # actually happened. A guard that only read `https://…` would have passed it.
    assert _offences("an operator looking at hub.stodge.org is told about api.x.org"), (
        "the leak this guard exists to catch was not detected"
    )
    assert _offences("connect to 192.168.86.31"), "a private address was not detected"
    assert _offences("the box at nas.local"), "a .local hostname was not detected"


def test_it_permits_what_the_project_legitimately_uses() -> None:
    """The paired negative. A guard that flags everything is switched off."""
    for benign in (
        "https://github.com/salimfadhley/agent-inbox",
        "https://salimfadhley.github.io/agent-inbox/",
        "http://mail-host.local:8080",
        "http://alpha.localhost:9000",
        "https://elsewhere.example/actors/ludmila_coe",
        "http://hub.invalid",
        "acct:alice@beta.localhost",
        "bind to 127.0.0.1 or 0.0.0.0",
        "the metadata endpoint at 169.254.169.254",
        "documentation uses 192.0.2.10",
        "ludmila_coe, pablo_fantomas and jed_smith walk into a bar",
    ):
        assert not _offences(benign), f"false positive on {benign!r}"
