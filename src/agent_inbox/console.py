"""The human console — a browser client of the same API.

Server-rendered HTML, no JavaScript framework, no build step. It is a *client*
(ADR 0005): it holds no messaging semantics and reaches the hub over HTTP exactly as the
CLI does. If a screen ever needs to decide something about messaging, the API is missing
a route — and twice now it was, which is how the `/observe/*` routes came to exist.

Two kinds of screen, and the difference is the whole design:

* **Observing** (dashboard, a mailbox, a thread) reads the hub's `/observe/*` routes.
  Those take no caller and consume nothing, so the operator can watch any mailbox
  without marking a single message read and without pretending to be anyone. This
  replaces the old console's trick of *impersonating* the agent it wanted to look at,
  which worked only because nothing authenticates (M2 FR-010).
* **Acting** (compose, the operator's own inbox) happens as the console's *own*
  identity — an ordinary agent that joined like any other. Sending and reading its own
  mail needs no special power, so it uses the plain agent routes. The operator is a
  participant here, not a watcher.

Deliberately plain. An operator wants to see what is happening at a glance; a stylesheet
and a handful of tables do that, and there is nothing to build or install.
"""

import html
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from litestar import Litestar, MediaType, Request, get, post
from litestar.datastructures import Cookie
from litestar.enums import RequestEncodingType
from litestar.exceptions import NotFoundException
from litestar.params import Body
from litestar.response import Redirect, Response

from agent_inbox import __version__
from agent_inbox.auth.service import INSECURE_ADMIN_WARNING
from agent_inbox.client import SESSION_COOKIE, ClientError, HubClient
from agent_inbox.exceptions import MailboxError
from agent_inbox.peers import identify
from agent_inbox.prompts import bootstrap, onboarding, role_note

#: A browser form arrives URL-encoded, not as JSON. Naming the type once keeps the
#: three POST handlers from each repeating the annotation.
Form = Annotated[dict[str, Any], Body(media_type=RequestEncodingType.URL_ENCODED)]

#: Vendored, same-origin assets — vis-network (the flow graph library) and our own
#: console.js. Serving them from the package, never a CDN, is what lets the CSP below
#: lock scripts to 'self': nothing is ever fetched off-box (charter), and an injected
#: script from any other origin is refused by the browser.
STATIC_DIR = Path(__file__).parent / "static"

#: Where this came from. In the footer because an operator looking at an unfamiliar
#: hub should be one click from what it is — and because the project's true name is
#: agent-inbox, which the console's own hostname will rarely tell them.
PROJECT_URL = "https://github.com/salimfadhley/agent-inbox"

#: What this *is*, for a reader who wants prose rather than a source tree. Beside the
#: repository rather than instead of it: someone who has just been handed a hub url and
#: is trying to work out what they are looking at wants the homepage, and someone
#: debugging it wants the code. Guessing which is unnecessary — both fit on one line.
HOMEPAGE_URL = "https://salimfadhley.github.io/agent-inbox/"

#: What this application is called, for the page title and `application-name`. A
#: self-hosted hub answers to whatever the homelab box is called — `examplehub`, `nas`,
#: `vm3` — and that name says nothing about what the site is. Bitwarden itself will
#: not read this (it names saved items after the hostname, full stop), but browser
#: tabs, history and other managers do.
APP_NAME = "agent-inbox"

#: Reachable without signing in, once the hub authenticates. Each earns it by being
#: needed *before* anyone can sign in: the way in, the way out, the container's health
#: probe, and the onboarding prompt — which is how a new agent is set up in the first
#: place and holds nothing secret. Everything else is behind the gate.
#: `/prompts*` and `/static/*` are matched by prefix alongside this set.
OPEN_PATHS = frozenset(
    {
        "/login",
        "/login/submit",
        "/logout/submit",
        "/health",
        # Probed by password managers before anyone signs in; it only points at a page
        # that is itself gated, so answering costs nothing.
        "/.well-known/change-password",
    }
)

#: A genuine Content-Security-Policy — stricter than the nothing that shipped before.
#: Scripts may load only from this origin (the vendored lib + console.js) and never
#: inline, so a reflected-script injection cannot execute. Inline *styles* and inline
#: SVG (the TOTP QR, the console's stylesheet) are permitted — style injection is not
#: code execution — which avoids nonce-ing every page for no security gain.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

STYLE = """
:root { color-scheme: light dark; --line: #8884; --accent: #4a90d9; }
* { box-sizing: border-box; }
body { font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; margin: 0;
       padding: 1.5rem clamp(1rem, 4vw, 3rem); max-width: 64rem; }
h1 { font-size: 1.3rem; margin: 0 0 .25rem; }
h1 a { text-decoration: none; color: inherit; }
h2 { font-size: 1rem; margin: 1.75rem 0 .6rem; }
.sub { opacity: .65; font-size: .85rem; margin-bottom: 1.25rem; }
nav { margin: 0 0 1.5rem; display: flex; gap: 1rem; flex-wrap: wrap; }
nav a { text-decoration: none; border-bottom: 2px solid transparent;
        padding-bottom: 2px; }
nav a:hover, nav a.on { border-color: currentColor; }
a { color: var(--accent); }
table { border-collapse: collapse; width: 100%; margin: 0 0 1rem; }
th, td { text-align: left; padding: .5rem .75rem .5rem 0;
         border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; font-size: .78rem; text-transform: uppercase;
     letter-spacing: .04em; opacity: .6; }
td.dim, .dim { opacity: .6; }
tr.unread td { font-weight: 600; }
code { font: 13px ui-monospace, monospace; }
.warn { border: 1px solid var(--line); border-left-width: 4px; padding: .75rem 1rem;
        margin: 0 0 1.5rem; font-size: .9rem; }
.empty { opacity: .6; font-style: italic; }
.foot { margin: 2.5rem 0 0; padding-top: .75rem; border-top: 1px solid var(--line);
        font-size: .8rem; opacity: .6; }
.wrap { overflow-x: auto; }
.cards { display: flex; gap: 1rem; flex-wrap: wrap; margin: 0 0 1rem; }
.card { border: 1px solid var(--line); border-radius: 6px; padding: .75rem 1rem;
        min-width: 7rem; }
.card .n { font-size: 1.6rem; font-weight: 600; }
.card .l { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em;
           opacity: .6; }
.bars { display: flex; align-items: flex-end; gap: 3px; height: 60px; margin: .5rem 0; }
.bars span { flex: 1; background: var(--accent); min-height: 2px;
             border-radius: 2px 2px 0 0; }
.dot { display: inline-block; width: .55rem; height: .55rem; border-radius: 50%;
       background: #3c3; margin-right: .35rem; }
.dot.warm { background: #d90; }
.dot.off { background: var(--line); }
textarea, input[type=text], input[type=password] { width: 100%;
           font: 13px/1.45 ui-monospace, monospace;
           padding: .6rem; border: 1px solid var(--line); border-radius: 4px;
           background: transparent; color: inherit; resize: vertical; }
label { display: block; font-size: .8rem; opacity: .7; margin: .8rem 0 .25rem; }
button { font: inherit; padding: .4rem .9rem; border: 1px solid var(--line);
         border-radius: 4px; background: transparent; color: inherit; cursor: pointer; }
button:hover { border-color: currentColor; }
.msg { border: 1px solid var(--line); border-radius: 6px; padding: .75rem 1rem;
       margin: 0 0 .75rem; }
.msg .h { font-size: .82rem; opacity: .7; margin-bottom: .4rem; }
.msg .b { white-space: pre-wrap; }
.mine { border-left: 3px solid var(--accent); }
"""


def _footer(hub: dict[str, Any] | None) -> str:
    """Both versions, on every page.

    The console and the hub are separate deployments of one package and can be on
    different versions — during a rolling upgrade they always are, and the whole
    question "what am I actually running?" is asked precisely when something looks
    wrong. Reading it off a page beats going to find the container.

    The console's version is its own `__version__`; the hub's is whatever it reports
    now, so a hub that cannot be reached says so rather than inheriting ours.
    """
    theirs = html.escape(str((hub or {}).get("version", "")) or "unreachable")
    return (
        f'<footer class="foot">console <code>{html.escape(__version__)}</code>'
        f" · hub <code>{theirs}</code> · "
        f'<a href="{HOMEPAGE_URL}">about agent-inbox</a> · '
        f'<a href="{PROJECT_URL}">source on GitHub</a></footer>'
    )


def _page(title: str, body: str, hub: dict[str, Any] | None, here: str = "") -> str:
    name = html.escape(str((hub or {}).get("name", APP_NAME)))
    version = html.escape(str((hub or {}).get("version", "")))
    unauthenticated = (hub or {}).get("authenticated") is False
    warning = (
        '<p class="warn"><strong>This hub does not authenticate.</strong> '
        "Anyone who can reach it can claim to be anyone, and this console can watch "
        "every mailbox. Suitable for a trusted network only.</p>"
        if unauthenticated
        else ""
    )
    # Shown *in addition* to the above, never instead of it: a hub can be enforcing
    # authentication and still have the override open, and that combination is exactly
    # the one where a single banner would tell a reassuring half-truth.
    if (hub or {}).get("adminPasswordSet"):
        warning += (
            f'<p class="warn"><strong>{html.escape(INSECURE_ADMIN_WARNING)}.</strong> '
            "<code>AGENT_MAILBOX_ADMIN_PASSWORD</code> is set, so <code>admin</code> "
            "can sign in with it <strong>without a second factor</strong> and then "
            "reset passwords and issue or revoke tokens. Anyone who can read "
            "this hub's environment controls it. Intended for manual testing and for "
            "recovering a hub whose password or authenticator is lost — unset it "
            "afterwards.</p>"
        )

    def link(href: str, text: str) -> str:
        cls = " class='on'" if href == here else ""
        return f"<a href='{href}'{cls}>{text}</a>"

    nav = (
        link("/", "Overview")
        + link("/agents", "Agents")
        + link("/graph", "Graph")
        + link("/tokens", "Tokens")
        + link("/inbox", "Inbox")
        + link("/compose", "Compose")
        + link("/prompts", "Prompt")
        + link("/maintenance", "Maintenance")
        + link("/settings", "Settings")
        + link("/account", "Account")
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="application-name" content="{APP_NAME}">
<link rel="icon" href="/static/icon.svg">
<title>{html.escape(title)} — {APP_NAME} ({name})</title>
<style>{STYLE}</style></head>
<body>
<h1><a href="/">{name}</a></h1>
<p class="sub">{html.escape(title)}{f" · v{version}" if version else ""}</p>
<nav>{nav}</nav>
{warning}
{body}
{_footer(hub)}
<script src="/static/console.js" defer></script>
</body></html>"""


def _add_csp(response: Response) -> Response:
    """Attach the security headers to every response, from one place.

    An `after_request` hook rather than a per-handler header, so these cannot be
    forgotten on a single route — which is exactly how a script-injection hole opens.

    **`no-store` is here rather than on the one page that needs it**, and that is the
    point. An outside review found the freshly minted token — which the hub itself
    cannot recover, since it keeps only a hash — sitting in a page a browser was free to
    keep in its cache, its history and its back-forward cache. Marking only the mint
    page would work until somebody adds the next page that shows something once.

    Nothing here is worth caching anyway: every screen is a live view of a hub that
    changes under it, so a cached console page is a *wrong* console page even when it
    holds no secret.
    """
    response.headers["Content-Security-Policy"] = CSP
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


def _table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f'<p class="empty">{html.escape(empty)}</p>'
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        f'<div class="wrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _leaf(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _mbox_link(name: Any) -> str:
    """A link to an agent's mailbox, rendered as code. Used all over the tables."""
    safe = html.escape(str(name or ""))
    return f'<a href="/mailbox/{safe}"><code>{safe}</code></a>'


def _when(note: dict[str, Any]) -> str:
    return (
        f'<span class="dim">{html.escape(_shortdate(note.get("published", "")))}</span>'
    )


def _advertised(hub: dict[str, Any], fallback: str) -> str:
    """The address the hub publishes for itself, for putting in front of a human.

    Prefer the hub's `id` over however this console reaches it: as a sidecar those
    differ, and only one of them is any use to an agent on the network.
    """
    return str(hub.get("id") or "").rstrip("/") or fallback


def _version(hub: dict[str, Any]) -> str:
    """What the hub says it is running — the floor an agent checks its tool against.

    The hub's answer, never this console's own ``__version__``: the two are separate
    containers and a rolling upgrade moves one before the other. An empty string means
    the hub was unreachable, and the prompt then omits the comparison rather than
    quoting a number nobody stands behind.
    """
    return str(hub.get("version") or "").strip()


def _console_base(request: Request) -> str:
    """Where *this console* is reachable, for putting inside the pasted prompt.

    The hub is told its own address (``AGENT_MAILBOX_PUBLIC_URL``) because it stamps
    it into every identifier it emits. A console sidecar is never told, and it cannot
    use the hub's answer: they are different services on different ports. It needs
    the address for one link, and the best evidence available is the address the
    human is looking at right now — if the page reached them here, an agent they
    paste it to can reach it here too.

    ``AGENT_MAILBOX_CONSOLE_URL`` overrides that, for a proxy that rewrites the host
    without setting the forwarded headers.
    """
    if override := os.environ.get("AGENT_MAILBOX_CONSOLE_URL", "").strip():
        return override.rstrip("/")
    headers = request.headers
    scheme = headers.get("x-forwarded-proto") or request.url.scheme
    host = headers.get("x-forwarded-host") or headers.get("host") or ""
    if host:
        return f"{scheme}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _freshness(last: str, now: datetime | None = None) -> tuple[str, str]:
    """How recently an actor was seen, as a dot class and a plain-words title.

    Green within the hour, amber within the day, grey after that.

    This replaces a comparison against a **hardcoded date**, under a comment claiming a
    green dot meant "seen today". It did not: it meant "seen at any point since a fixed
    date in the past", so every dot went green and stayed green, and the display grew
    more wrong every day it ran. A roster where everyone looks present is worse than no
    dot at all, because it is believed.

    Unparseable or missing is grey, never green. The failure of a freshness check should
    not look like freshness.
    """
    now = now or datetime.now(UTC)
    try:
        seen = datetime.fromisoformat(str(last))
    except ValueError:
        return "off", "never seen"
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    age = now - seen
    if age < timedelta(hours=1):
        return "", "seen within the hour"
    if age < timedelta(hours=24):
        return "warm", "seen within the day"
    return "off", "not seen for over a day"


def _shortdate(value: str) -> str:
    """A timestamp trimmed to what a human reads at a glance."""
    text = str(value or "")
    return text[:16].replace("T", " ") if text else ""


def _subject(note: dict[str, Any]) -> str:
    """A subject to show — the real one, or the first words of the body."""
    summary = (note.get("summary") or "").strip()
    if summary:
        return summary
    body = " ".join((note.get("content") or "").split())
    return (body[:60] + "…") if len(body) > 60 else (body or "(no subject)")


def _needs_login(exc: Exception) -> bool:
    """Is this the hub saying "who are you?" rather than "something broke"?

    Matched on the stable error code the API attaches to every failure, which exists
    for exactly this: a caller switching on the cause without parsing prose.
    """
    return "not_authenticated" in str(exc) or "enrolment_required" in str(exc)


#: `scheme://user:password@` — the credential some urls carry, wherever it appears.
_URL_CREDENTIAL = re.compile(r"(?<=://)[^/\s@]+@")


def _no_credentials(text: str) -> str:
    """Strip `user:password@` from every url in a string. Applied to *all* of it.

    A url may legitimately carry a credential, and this error page renders **before
    sign-in** on the login route — so anything printed here must be fit for a stranger
    to read.

    **Prose, not just the url field**, and that is the whole point of doing it here
    rather than at the one place a url is printed. An outside review caught the first
    version of this doing exactly half the job: the configured url was redacted where
    the page names it, while `client.py` builds *"cannot reach the mailbox at
    {config.base}: …"* and the page then printed that message intact. The credential
    walked back in through the sentence next to the one it had been removed from.
    """
    return _URL_CREDENTIAL.sub("", text)


def _err(
    exc: Exception,
    hub: dict[str, Any] | None,
    title: str,
    *,
    api: str = "",
    signed_in: bool = False,
) -> Response:
    """Every screen either renders or explains — never a blank page.

    An operator staring at nothing cannot tell "hub down" from "nothing here", so a
    failure says which it was rather than falling through to an empty table.

    **It names the hub it asked.** "The hub did not answer" is only useful to someone
    who already knows which hub that was, and the console's whole job is to front one
    that lives at a different address than itself — an operator looking at
    `hub.example.org` is being told about `api.hub.example.org`, which is a distinction
    they cannot make from the prose alone. Naming the URL also catches the commonest
    misconfiguration of all, a console pointed at the wrong hub, which otherwise
    presents as an unexplained refusal.

    A hub that refuses for want of a credential is not a fault to report but a door to
    open: on an enforcing hub *every* page fails this way until someone signs in, and
    meeting a first-time operator with a 502 about their own hub would be absurd. So
    that one case redirects to the sign-in page instead.

    **Unless they are already signed in.** Then the refusal is about something else —
    a page acting as the console's own identity, which has no token of its own — and
    bouncing them to a login they have already passed reads as a random logout and
    hides the real cause. Signed in, they get the message, and with it the door as a
    *link* rather than as a redirect: an expired session looks exactly like this, and
    the one thing that fixes it should not have to be found from the navigation.
    """
    if _needs_login(exc) and not signed_in:
        return Redirect("/login")
    # Named to whoever is entitled to know. An operator needs the address to tell "the
    # console is pointed at the wrong hub" from "the hub is down"; a stranger who has
    # not signed in needs neither, and on a self-hosted deployment that address is
    # often an internal hostname worth not advertising. So: the url to them, the plain
    # noun to everyone else.
    asked = html.escape(_no_credentials(api)) if api and signed_in else "The hub"
    body = (
        f'<p class="warn">{asked} did not answer this request: '
        f"{html.escape(_no_credentials(str(exc)))}</p>"
    )
    if _needs_login(exc):
        # Reaching here means they are signed in, so "sign in" on its own would read
        # as nonsense. Say which of the two things it is before offering the fix.
        body += (
            "<p>You are signed in, so this is the hub refusing a request the console "
            "makes as <em>itself</em> rather than as you — or your session has since "
            'expired. <a href="/login">Sign in again</a> to rule out the second.</p>'
        )
    return Response(_page(title, body, hub), media_type=MediaType.HTML, status_code=502)


def build_console(client: HubClient) -> Litestar:
    """A window onto one hub: watch anyone, act as yourself."""

    def _signed_in(request: Request) -> bool:
        """Does this browser carry a session at all? Not whether it is a valid one —
        that is the hub's call, and this only decides how to report a refusal."""
        return bool(request.cookies.get(SESSION_COOKIE))

    def acting_for(request: Request) -> tuple[HubClient, str]:
        """The client and name to *act* as — the signed-in operator, or the console.

        Observation borrows the operator's session; acting has to go further and use
        their **name**, because the hub resolves a session to that human and every
        mailbox route checks the path against the caller. Reading `/actors/console/…`
        with an admin's session is refused, which is what left Inbox and Compose broken
        on an authenticating hub even after the session was being forwarded.

        With no session — an open hub — nothing changes: the console acts as itself,
        the ordinary agent it joined as.
        """
        session = request.cookies.get(SESSION_COOKIE)
        if not session:
            return client, client.config.name
        borrowed = client.with_session(session)
        who = borrowed.whoami()
        if not who:
            return borrowed, client.config.name
        return borrowed.acting_as(who, session), who

    def seen_by(request: Request) -> HubClient:
        """The hub client to use for one request, carrying the operator's session.

        Observation is done *on behalf of* whoever is signed in. The console holds no
        credential of its own under enforce — and must not, or anyone who reached it
        would see every mailbox without logging in — so it borrows the human's session
        and lets the hub decide. Without this the overview called `/observe/stats` as
        nobody, got a 401, and the "not authenticated" redirect sent the operator back
        to the login form they had just successfully used: a loop that looked exactly
        like a rejected password.
        """
        return client.with_session(request.cookies.get(SESSION_COOKIE))

    def hub_or_none() -> dict[str, Any] | None:
        """The hub descriptor, or ``None`` if it cannot be reached.

        Fetched on every page so the unauthenticated banner and version are always
        current, and so a hub that has gone away is reported rather than papered over.
        """
        try:
            return client.hub_info()
        except ClientError:
            return None

    async def ensure_own_mailbox(_: Litestar) -> None:
        """Claim the console's own name, so compose and inbox have somewhere to work.

        The console acts as an ordinary agent for the things it *does* (as opposed to
        the things it *watches*), which means it must have joined like any other. Done
        at startup and tolerant of already-existing: a restart re-claiming its own name
        is the normal case, not an error. If the hub is down we say nothing here and let
        the pages report it — a console that refused to start because the hub was
        briefly unreachable would be worse than one that explains the outage.
        """
        try:
            client.join()
        except ClientError:
            # Already joined (the restart case) or hub unreachable (the pages will say).
            pass

    @get("/.well-known/change-password", sync_to_thread=False)
    def change_password_url() -> Redirect:
        """The W3C well-known URL, so a password manager can offer "change password".

        Safari has honoured it since 2019 and Chrome since 86: they probe for a 2xx/3xx
        here and, if they find one, offer to take the user straight to the form. It is
        two lines and it is the one piece of password-manager integration that is a
        real standard rather than a heuristic.
        """
        return Redirect("/account")

    @get("/health", sync_to_thread=False)
    def health() -> dict[str, str]:
        """Is this console process up — nothing more.

        Deliberately does not ask the hub. A console that is serving pages perfectly
        well is healthy even while the hub is down; conflating the two would have the
        orchestrator restart the console over an outage it cannot fix, and hide the
        real fault behind the wrong red light. The pages already report an unreachable
        hub, which is where that belongs.
        """
        return {"status": "ok"}

    # -- observing (no caller; consumes nothing) ---------------------------

    @get("/", media_type=MediaType.HTML, sync_to_thread=True)
    def overview(request: Request) -> Response:
        hub = hub_or_none()
        try:
            stats = seen_by(request).survey()
            actors = seen_by(request).list_agents().get("items", [])
        except ClientError as exc:
            return _err(
                exc,
                hub,
                "Overview",
                api=client.config.base,
                signed_in=_signed_in(request),
            )

        cards = "".join(
            f'<div class="card"><div class="n">{n}</div>'
            f'<div class="l">{html.escape(label)}</div></div>'
            for label, n in (
                ("agents", stats.get("actors", 0)),
                ("messages", stats.get("messages", 0)),
                ("threads", stats.get("threads", 0)),
            )
        )
        per_day = list(stats.get("per_day", []))
        peak = max((n for _, n in per_day), default=1) or 1
        bars = "".join(
            f'<span style="height:{max(2, round(100 * n / peak))}%" '
            f'title="{html.escape(str(day))}: {n}"></span>'
            for day, n in per_day
        )
        chart = (
            f'<h2>Traffic</h2><div class="bars">{bars}</div>'
            f'<p class="dim">{len(per_day)} active day(s), busiest {peak}.</p>'
            if per_day
            else ""
        )

        flow_rows = [
            [_mbox_link(frm), _mbox_link(to), str(count)]
            for frm, to, count in list(stats.get("flow", []))[:10]
        ]
        flow = "<h2>Who is talking to whom</h2>" + _table(
            ["From", "To", "Messages"], flow_rows, "No messages yet."
        )

        online_rows = _agent_rows(actors)
        who = "<h2>Agents</h2>" + _table(
            ["", "Who", "Role", "Project", "Last seen"],
            online_rows,
            "Nobody has joined yet.",
        )
        return Response(
            _page("Overview", cards + chart + flow + who, hub, "/"),
            media_type=MediaType.HTML,
        )

    def _agent_rows(actors: list[dict[str, Any]]) -> list[list[str]]:
        rows = []
        for a in actors:
            name = a.get("preferredUsername", "")
            profile = a.get("profile") or {}
            last = a.get("lastSeen") or ""
            # No heartbeat exists, so this is recency, never "online": the dot says when
            # the hub last heard from an agent, and nothing about whether it is running.
            state, why = _freshness(str(last))
            dot = (
                f'<span class="dot{" " + state if state else ""}" '
                f'title="{html.escape(why)}"></span>'
            )
            # Self-declared and free-form, like everything else in a profile — an agent
            # says what it is working on, and the hub takes its word. Blank for the
            # standing residents and for anyone who joined without describing
            # themselves, which is most of a fresh hub and not a fault.
            #
            # Clipped, because these run long in practice: real values on this hub
            # include "5g_arg (Project DEVCON / ULEZ-DC)", and one wrapped cell makes
            # every other row taller for no gain. The full text stays in the tooltip.
            project = str(profile.get("project", "") or "").strip()
            shown = (project[:28] + "…") if len(project) > 28 else project
            rows.append(
                [
                    dot,
                    _mbox_link(name),
                    html.escape(str(profile.get("role", "") or "")),
                    f'<span title="{html.escape(project)}">{html.escape(shown)}</span>'
                    if project
                    else '<span class="dim">—</span>',
                    f'<span class="dim">{html.escape(_shortdate(last))}</span>',
                ]
            )
        return rows

    @get("/agents", media_type=MediaType.HTML, sync_to_thread=True)
    def agents(request: Request) -> Response:
        hub = hub_or_none()
        try:
            actors = seen_by(request).list_agents().get("items", [])
        except ClientError as exc:
            return _err(
                exc,
                hub,
                "Agents",
                api=client.config.base,
                signed_in=_signed_in(request),
            )
        rows = []
        for a in actors:
            name = a.get("preferredUsername", "")
            profile = a.get("profile") or {}
            facts = ", ".join(
                f"{html.escape(str(k))}: {html.escape(str(v))}"
                for k, v in profile.items()
                if k not in {"purpose", "standing"}
            )
            rows.append(
                [
                    _mbox_link(name),
                    html.escape(str(a.get("type", ""))),
                    html.escape((a.get("summary") or "")[:80]),
                    f'<span class="dim">{facts}</span>',
                ]
            )
        # No Tokens column. A token belongs to no agent, so a per-agent link into one
        # was describing a relationship that does not exist — and the Tokens screen it
        # pointed at is now a list of tokens, which this table cannot usefully filter.
        body = _table(["Who", "Type", "About", "Profile"], rows, "Nobody yet.")
        return Response(
            _page("Agents", body, hub, "/agents"), media_type=MediaType.HTML
        )

    @get("/mailbox/{name:str}", media_type=MediaType.HTML, sync_to_thread=True)
    def mailbox(name: str, request: Request) -> Response:
        """Everything addressed to one agent — read or not, **without consuming it**.

        Reads `/observe/mailbox/{name}`, which takes no caller. The operator looks; the
        agent still has all of its mail. This is the route that replaced impersonation.
        """
        hub = hub_or_none()
        try:
            items = seen_by(request).observe_mailbox(name).get("items", [])
            info = seen_by(request).whois(name)
        except ClientError as exc:
            return _err(
                exc,
                hub,
                name,
                api=client.config.base,
                signed_in=_signed_in(request),
            )

        rows = []
        for n in reversed(items):  # newest first for a reader
            oid = _leaf(n.get("id"))
            rows.append(
                [
                    f'<a href="/message/{html.escape(oid)}">'
                    f"{html.escape(_subject(n))}</a>",
                    _mbox_link(_leaf(n.get("attributedTo"))),
                    _when(n),
                ]
            )
        summary = html.escape((info.get("summary") or "") if info else "")
        body = (
            f"<h2><code>{html.escape(name)}</code></h2>"
            + (f'<p class="dim">{summary}</p>' if summary else "")
            + '<p class="dim">The operator\'s view. Looking does not consume — '
            "the agent keeps all of its mail.</p>"
            + _table(["Subject", "From", "When"], rows, "Nothing has been sent here.")
        )
        return Response(_page(f"{name}", body, hub, ""), media_type=MediaType.HTML)

    @get("/message/{object_id:str}", media_type=MediaType.HTML, sync_to_thread=True)
    def message(object_id: str, request: Request) -> Response:
        """One message and the **whole** thread it belongs to.

        Uses `/observe/objects/{id}/thread`, so it shows the conversation entire —
        including turns no single participant is party to. That is the operator's view,
        and the reason it is not the agent-facing `read_thread`.
        """
        hub = hub_or_none()
        try:
            turns = seen_by(request).observe_thread(object_id).get("items", [])
            detail = seen_by(request).observe_object(object_id)
        except ClientError as exc:
            return _err(
                exc,
                hub,
                "Message",
                api=client.config.base,
                signed_in=_signed_in(request),
            )

        read_by = detail.get("readBy", []) if detail else []
        blocks = []
        for n in turns:
            oid = _leaf(n.get("id"))
            here = oid == _leaf(object_id)
            blocks.append(
                f'<div class="msg{" mine" if here else ""}">'
                f'<div class="h"><strong>{html.escape(_subject(n))}</strong> · '
                f"from <code>{html.escape(_leaf(n.get('attributedTo')))}</code> · "
                f"{html.escape(_shortdate(n.get('published', '')))}</div>"
                f'<div class="b">{html.escape(n.get("content") or "")}</div></div>'
            )
        read_note = (
            "<p class='dim'>Read by "
            + ", ".join(f"<code>{html.escape(str(r))}</code>" for r in read_by)
            + ".</p>"
            if read_by
            else "<p class='dim'>Not yet read by anyone it was sent to.</p>"
        )
        body = "<h2>Thread</h2>" + "".join(blocks) + read_note
        return Response(_page("Message", body, hub, ""), media_type=MediaType.HTML)

    # -- acting (as the console's own identity) ----------------------------

    @get("/inbox", media_type=MediaType.HTML, sync_to_thread=True)
    def inbox(request: Request) -> Response:
        """The console's *own* mail — this is the one mailbox it may consume.

        Everything else on this console watches without touching. Here the operator is
        an ordinary participant reading their own inbox, which needs no special power
        and marks messages read exactly as any agent would.
        """
        hub = hub_or_none()
        acting, me = acting_for(request)
        try:
            items = acting.check_inbox().get("items", [])
        except ClientError as exc:
            return _err(
                exc,
                hub,
                "Inbox",
                api=client.config.base,
                signed_in=_signed_in(request),
            )
        rows = []
        for n in items:
            oid = _leaf(n.get("id"))
            rows.append(
                [
                    f'<a href="/message/{html.escape(oid)}">'
                    f"{html.escape(_subject(n))}</a>",
                    f"<code>{html.escape(_leaf(n.get('attributedTo')))}</code>",
                    _when(n),
                    f'<form method="post" action="/inbox/read" style="margin:0">'
                    f'<input type="hidden" name="id" value="{html.escape(oid)}">'
                    f'<button type="submit">Mark read</button></form>',
                ]
            )
        body = (
            f"<h2>Mail for <code>{html.escape(me)}</code></h2>"
            '<p class="dim">This is the console\'s own mailbox — the one place '
            "it acts as a participant rather than a watcher.</p>"
            + _table(["Subject", "From", "When", ""], rows, "Your inbox is empty.")
        )
        return Response(_page("Inbox", body, hub, "/inbox"), media_type=MediaType.HTML)

    @post("/inbox/read", sync_to_thread=True)
    def do_read(request: Request, data: Form) -> Redirect:
        oid = str(data.get("id", "")).strip()
        if oid:
            try:
                acting_for(request)[0].read_message(oid)
            except ClientError:
                pass  # the inbox will simply still show it; no page to break
        return Redirect("/inbox")

    @get("/compose", media_type=MediaType.HTML, sync_to_thread=True)
    def compose_form(request: Request) -> Response:
        hub = hub_or_none()
        me = html.escape(acting_for(request)[1])
        sent = ""  # populated by the redirect target below via query, kept simple
        body = (
            f"<h2>Send a message as <code>{me}</code></h2>"
            f"{sent}"
            '<form method="post" action="/compose/send">'
            '<label for="to">To (comma-separated, or <code>everyone</code>)</label>'
            '<input type="text" id="to" name="to" placeholder="rosemary_nasrin">'
            '<label for="subject">Subject</label>'
            '<input type="text" id="subject" name="subject" placeholder="a short line">'
            '<label for="body">Message</label>'
            '<textarea id="body" name="body" rows="8"></textarea>'
            '<p style="margin-top:.8rem"><button type="submit">Send</button></p>'
            "</form>"
            '<p class="dim">You send as this console\'s own identity — an ordinary '
            "agent. Replies come back to your <a href='/inbox'>inbox</a>.</p>"
        )
        return Response(
            _page("Compose", body, hub, "/compose"), media_type=MediaType.HTML
        )

    # A distinct path from the GET form on purpose: this Litestar version mis-dispatches
    # a GET when a sync GET and sync POST share one exact path, and the GET 500s. The
    # form posts here; the browser never sees the difference.
    @post("/compose/send", status_code=200, sync_to_thread=True)
    def do_compose(request: Request, data: Form) -> Response:
        hub = hub_or_none()
        recipients = [
            r.strip() for r in str(data.get("to", "")).split(",") if r.strip()
        ]
        body_text = str(data.get("body", "")).strip()
        subject = str(data.get("subject", "")).strip() or None
        if not recipients or not body_text:
            msg = (
                '<p class="warn">A message needs at least one recipient and a body.</p>'
            )
            return Response(
                _page("Compose", msg + _compose_again(), hub, "/compose"),
                media_type=MediaType.HTML,
            )
        try:
            acting_for(request)[0].send_message(recipients, body_text, subject=subject)
        except ClientError as exc:
            return _err(
                exc,
                hub,
                "Compose",
                api=client.config.base,
                signed_in=_signed_in(request),
            )
        done = (
            "<p>Sent to "
            + ", ".join(f"<code>{html.escape(r)}</code>" for r in recipients)
            + ".</p>"
        )
        return Response(
            _page("Compose", done + _compose_again(), hub, "/compose"),
            media_type=MediaType.HTML,
        )

    def _compose_again() -> str:
        return (
            '<p><a href="/compose">Write another</a> · <a href="/inbox">Inbox</a></p>'
        )

    # -- tokens -----------------------------------------------------

    def _setup_prompt(secret: str, hub_url: str) -> str:
        """The prompt an agent needs, with this token already in it (FR-013).

        **A second document, not the standing prompt.** The Prompt tab is on the
        console's open paths — served to anyone who can reach the hub, signed in or
        not — because an agent needs it *before* it has any way to authenticate. It
        earns that openness by holding nothing secret, and a credential in it would be
        handed to every anonymous visitor.

        This one exists inside a single HTTP response and is never served again. The hub
        keeps only a hash of the token, so there is no way to rebuild this page later
        even for the operator who made it.
        """
        return (
            f"Set up the agent-inbox mailbox on this machine.\n\n"
            f"1. Install the client:\n"
            f"     uv tool install --no-cache --force 'agent-inbox[clients]'\n\n"
            f"2. Install the credential. It admits this whole machine, so every agent\n"
            f"   here is covered and there is nothing to repeat per project:\n"
            f"     agent-inbox config set --global token {secret}\n\n"
            f"3. Claim a name on the hub and write this project's configuration:\n"
            f"     agent-inbox join --hub {hub_url}\n\n"
            f"4. Prove it:\n"
            f"     agent-inbox doctor\n\n"
            f"The token is sent automatically from now on; you never type it again.\n"
            f"It admits the machine, not you: your name still comes from your own\n"
            f"configuration, and every agent here uses the same credential.\n\n"
            f"Then read {hub_url}/prompts/agent for how the mailbox works."
        )

    def _token_instructions(secret: str, hub_url: str) -> str:
        """What to do with a token, shown at the only moment it is visible.

        The hub stores a hash, so this is the one and only time anyone can read it.
        Anything the agent needs must therefore be on this page, in a form that can be
        pasted — not a description of the file, but the command that writes it, and
        (FR-013) the whole setup prompt with the token already in place.
        """
        prompt = _setup_prompt(secret, hub_url)
        return (
            '<div class="warn"><p><strong>Copy it now.</strong> The hub keeps only a '
            "hash, so this is the only time it can be read — and that goes for the "
            "setup prompt below too, which contains it. If either is lost, mint "
            "another token and revoke this one.</p>"
            f'<p><code id="minted">{html.escape(secret)}</code></p>'
            "<p><button data-copy='minted' data-said='copied' type='button'>"
            "Copy the token</button> <span id='copied' class='dim'></span></p></div>"
            "<p>Put it in <code>~/.config/agent-inbox/config.toml</code> on the "
            "machine it is for. Every agent there is then admitted, whatever name "
            "each of them uses — there is nothing to do per agent and nothing to "
            "repeat per project:</p>"
            f'<pre>token = "{html.escape(secret)}"</pre>'
            "<h2>Or hand this to the agent</h2>"
            "<p>The same token, inside the instructions that use it. One copy and the "
            "agent sets itself up — there is no second step where somebody remembers "
            "to pass the credential separately.</p>"
            f'<pre id="setup">{html.escape(prompt)}</pre>'
            "<p><button data-copy='setup' data-said='prompt-copied' type='button'>"
            "Copy the setup prompt</button> "
            "<span id='prompt-copied' class='dim'></span></p>"
            "<p class='dim'>This is not the prompt on the Prompt tab. That one is "
            "public and never carries a credential; this one exists only on this "
            "page, once.</p>"
        )

    def _tokens_body(
        items: list[dict[str, Any]], hub: dict[str, Any] | None, extra: str
    ) -> str:
        """Every token on the hub — the screen this mission exists for.

        Not a list of agents. A token belongs to no agent, which is why a shared one
        used to be unfindable the moment its "shown once" page was closed: there was no
        screen it appeared on, and revoking it meant opening the database.
        """

        def actions(t: dict[str, Any]) -> str:
            if t.get("revoked"):
                return '<span class="dim">revoked</span>'
            tid = html.escape(str(t.get("id", "")))
            return (
                '<form method="post" action="/tokens/revoke">'
                f'<input type="hidden" name="id" value="{tid}">'
                "<button type='submit'>Revoke</button></form>"
            )

        def issued_to(t: dict[str, Any]) -> str:
            """What the operator *claimed*. Never what we observed — see `admitted`."""
            bound = t.get("boundTo")
            label = html.escape(str(t.get("label") or ""))
            if bound:
                return (
                    f"{label} <span class='dim'>· bound to "
                    f"<code>{html.escape(str(bound))}</code></span>"
                )
            return label or "<span class='dim'>—</span>"

        def _seen(u: dict[str, Any]) -> str:
            return _shortdate(str(u.get("lastSeen") or ""))

        def admitted(t: dict[str, Any]) -> str:
            """What the hub *observed*. Kept in its own column on purpose (FR-010): a
            stale label sitting where a fact appears to be is how somebody revokes the
            wrong credential."""
            names = t.get("admitted") or []
            if not names:
                return "<span class='dim'>nobody yet</span>"
            return ", ".join(
                f"<code>{html.escape(str(u.get('name', '')))}</code>"
                f"<span class='dim'> ({_seen(u)})</span>"
                for u in names
            )

        rows = [
            [
                issued_to(t),
                f'<span class="dim">{_shortdate(str(t.get("created") or ""))}</span>',
                # "never" and a date are different facts leading to different actions,
                # which is the whole reason this column exists.
                '<span class="dim">'
                f"{_shortdate(str(t.get('lastUsed') or '')) or 'never'}</span>",
                admitted(t),
                actions(t),
            ]
            for t in items
        ]
        note = (
            '<p class="warn">This hub does not require a token yet, so mail works '
            "without one. Minting now is still worth doing: an agent that already has "
            "a token keeps working on the day enforcement is turned on, and one that "
            "does not is locked out until someone is at a keyboard.</p>"
            if (hub or {}).get("authenticated") is False
            else ""
        )
        return (
            "<p>A token admits a <strong>machine</strong>. Whoever holds it is let in, "
            "and each agent still says which name it is using — so one token covers "
            "every agent on a laptop, and there is nothing to mint per agent.</p>"
            f"{note}{extra}"
            + _table(
                ["Issued to", "Created", "Last used", "Admitted", ""],
                rows,
                "No tokens yet. Nothing can authenticate here.",
            )
            + "<p class='dim'><strong>Issued to</strong> is what you typed when you "
            "minted it. <strong>Admitted</strong> is who the hub has actually seen use "
            "it — that is the column to revoke from.</p>"
            "<h2>Mint a token</h2>"
            "<p>The secret is shown once, with a prompt you can hand straight to an "
            "agent.</p>"
            '<form method="post" action="/tokens/mint">'
            "<label>Label — which machine is this for?</label>"
            '<input type="text" name="label" placeholder="workshop laptop" required>'
            "<p style='margin-top:.6rem'><button type='submit'>Mint</button></p>"
            "</form>"
        )

    def _tokens_page(request: Request, extra: str = "") -> Response:
        """The Tokens screen. Operator-only, and the console judges none of that itself:
        it relays the human's session inward and reports whatever the hub decides."""
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, _ = client.auth_call("GET", "/auth/tokens", session=sid)
        if status in (401, 403):
            page = (
                "<p>Tokens are an operator action. "
                "<a href='/login'>Sign in</a> first.</p>"
            )
            return Response(
                _page("Tokens", page, hub, "/tokens"), media_type=MediaType.HTML
            )
        if status >= 400:
            detail = (body or {}).get("detail", "the hub refused")
            return Response(
                _page("Tokens", f"<p>{html.escape(str(detail))}</p>", hub, "/tokens"),
                media_type=MediaType.HTML,
            )
        items = (body or {}).get("items", [])
        return Response(
            _page("Tokens", _tokens_body(items, hub, extra), hub, "/tokens"),
            media_type=MediaType.HTML,
        )

    @get("/tokens", media_type=MediaType.HTML, sync_to_thread=True)
    def token_index(request: Request) -> Response:
        """Every token on the hub.

        This used to list *agents*, with a per-agent page behind each one — which meant
        a shared token, belonging to no agent, appeared on no screen at all once its
        "shown once" page was closed. It could not be reviewed and could not be revoked
        without opening the database. That is the fault this mission opened with.
        """
        return _tokens_page(request)

    def _refused(
        body: dict[str, Any] | None, fallback: str, hub: dict[str, Any] | None
    ) -> str:
        detail = (body or {}).get("detail", fallback)
        return _page(
            "Maintenance",
            f"<h2>Expiry</h2><p>{html.escape(str(detail))}</p>"
            "<p><a href='/maintenance'>Try again</a></p>",
            hub,
            "/maintenance",
        )

    def _purge_page(
        preview: dict[str, Any], hub: dict[str, Any] | None, note: str = ""
    ) -> str:
        """The maintenance page: what would go, and the button that makes it go.

        Deliberately shows the preview *first* and every time. Expiry leaves no
        tombstone — afterwards a purged conversation is indistinguishable from one that
        never happened — so this page is the only chance anyone gets to disagree with
        it, and a button without the list would be one nobody could press responsibly.
        """
        schedule = preview.get("schedule", {}) if isinstance(preview, dict) else {}
        last = schedule.get("lastCycle")
        if last:
            when = html.escape(str(last)[:19].replace("T", " "))
            removed = schedule.get("lastRemovedObjects", 0)
            heartbeat = (
                f"<p class='muted'>Last automatic check {when} UTC "
                f"({schedule.get('cycles', 0)} so far, {removed} removed).</p>"
            )
        else:
            # An absent heartbeat is the finding, not a cosmetic gap. In 0.18.1 the
            # loop never reached its first cycle on a hub that restarted often, and
            # the startup log said "scheduled" throughout. This is where that shows.
            heartbeat = (
                "<p class='muted'><strong>No automatic check has completed yet."
                "</strong> The first runs a few minutes after the hub starts. If it is "
                "here long after that, retention is not running and the log will say "
                "why.</p>"
            )
        if schedule.get("lastError"):
            heartbeat += (
                "<p><strong>The last automatic check failed:</strong> "
                f"{html.escape(str(schedule['lastError']))}</p>"
            )

        threads = preview.get("threads", []) if isinstance(preview, dict) else []
        count = preview.get("threadCount", 0) if isinstance(preview, dict) else 0
        messages = preview.get("messageCount", 0) if isinstance(preview, dict) else 0

        if not threads:
            body = (
                "<p>Nothing has gone quiet for long enough to expire. "
                "The hub checks on its own schedule; this page is here for when you "
                "want to look, or to act sooner.</p>"
            )
            button = ""
        else:
            rows = "".join(
                "<tr><td>{subject}</td><td>{last}</td><td>{n}</td></tr>".format(
                    subject=html.escape(str(t.get("subject", ""))),
                    last=html.escape(str(t.get("lastPublished", ""))[:10]),
                    n=t.get("messages", 0),
                )
                for t in threads
            )
            body = (
                f"<p><strong>{count} conversation(s), {messages} message(s)</strong> "
                "would be removed. Each has been idle for longer than this hub keeps "
                "mail. Live conversations are kept whole however old they started.</p>"
                "<table><thead><tr><th>Conversation</th><th>Last activity</th>"
                "<th>Messages</th></tr></thead><tbody>"
                f"{rows}</tbody></table>"
            )
            button = (
                "<form method='post' action='/maintenance/purge'>"
                f"<button type='submit'>Purge these {messages} message(s)</button>"
                "</form>"
                "<p class='muted'>There is no undo, and nothing is left behind to say "
                "a conversation was here.</p>"
            )
        return _page(
            "Maintenance",
            f"<h2>Expiry</h2>{note}{heartbeat}{body}{button}",
            hub,
            "/maintenance",
        )

    @get("/maintenance", media_type=MediaType.HTML, sync_to_thread=True)
    def maintenance(request: Request) -> Response:
        """What a purge would remove. Reads only."""
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, _ = client.auth_call("GET", "/observe/purge", session=sid)
        if status != 200:
            return Response(
                _refused(body, "the hub would not say what it would purge", hub),
                media_type=MediaType.HTML,
            )
        return Response(_purge_page(body or {}, hub), media_type=MediaType.HTML)

    @post("/maintenance/purge", status_code=200, sync_to_thread=True)
    def maintenance_purge(request: Request) -> Response:
        """Purge now. The preview above said what this would do."""
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, _ = client.auth_call("POST", "/observe/purge", session=sid)
        if status != 200:
            return Response(
                _refused(body, "the hub refused to purge", hub),
                media_type=MediaType.HTML,
            )
        removed = (body or {}).get("removed", 0)
        note = (
            f"<p><strong>Removed {removed} message(s).</strong> "
            "The next scheduled purge will run as usual.</p>"
        )
        # Re-read rather than reusing the response: what is left is the interesting
        # part, and showing a stale list beside "removed" would read as a failure.
        status, fresh, _ = client.auth_call("GET", "/observe/purge", session=sid)
        return Response(
            _purge_page(fresh or {}, hub, note=note), media_type=MediaType.HTML
        )

    @post("/tokens/mint", status_code=200, sync_to_thread=True)
    def mint(request: Request, data: Form) -> Response:
        """Mint, and show the secret with the prompt that uses it — once (FR-013).

        A POST response on purpose. A page carrying a live credential must not be
        re-fetchable, cacheable or linkable, and a response to a form submission is none
        of those: reload it and the token is gone, which is correct.
        """
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, _ = client.auth_call(
            "POST",
            "/auth/tokens",
            {"label": str(data.get("label", ""))},
            session=sid,
        )
        if status not in (200, 201):
            detail = (body or {}).get("detail", "the hub refused to mint a token")
            return _tokens_page(
                request, f"<p class='warn'>{html.escape(str(detail))}</p>"
            )
        secret = str((body or {}).get("token", ""))
        return _tokens_page(request, _token_instructions(secret, client.config.base))

    @post("/tokens/revoke", status_code=200, sync_to_thread=True)
    def revoke(request: Request, data: Form) -> Response:
        """Revoke, and say what was just cut off.

        The hub returns the agents that token had admitted, because that is the only
        question an operator is actually asking — *what will this break?* Reporting a
        bare "revoked" leaves them to find out from whoever stops working.
        """
        sid = request.cookies.get(SESSION_COOKIE)
        token_id = str(data.get("id", ""))
        status, body, _ = client.auth_call(
            "DELETE", f"/auth/tokens/{token_id}", session=sid
        )
        if status not in (200, 204):
            detail = (body or {}).get("detail", "failed")
            return _tokens_page(
                request, f"<p class='warn'>{html.escape(str(detail))}</p>"
            )
        admitted = (body or {}).get("admitted") or []
        who = (
            "It had admitted "
            + ", ".join(f"<code>{html.escape(str(n))}</code>" for n in admitted)
            + " — those agents are locked out from their next call."
            if admitted
            else "It had never admitted anyone, so nothing was using it."
        )
        return _tokens_page(request, f"<p class='warn'>Revoked. {who}</p>")

    # -- the prompt --------------------------------------------------------

    @get("/prompts", media_type=MediaType.HTML, sync_to_thread=True)
    def prompts(request: Request) -> Response:
        """The onboarding prompt, and the short note that fetches it.

        What is offered for copying is **not** the full prompt but a few lines telling
        the agent to read it from here at the start of every session. Pasting the
        whole thing into a `CLAUDE.md` freezes it at the version it was copied on, and
        this prompt changes with almost every release. The full text is shown below
        so a human can read what they are pointing an agent at.
        """
        hub = hub_or_none() or {}
        address = _advertised(hub, client.config.base)
        prompt_url = f"{_console_base(request)}/prompts/agent"
        note = "".join(
            f"<p>{html.escape(para)}</p>"
            for para in role_note().replace("**", "").split("\n\n")
        )
        # The caution in the prompt comes from the hub's own descriptor — the same
        # field `hub_info` reports — so an authenticated hub cannot publish the
        # unauthenticated warning.
        rendered_prompt = onboarding(
            address, prompt_url, _version(hub), bool(hub.get("authenticated"))
        )
        body = (
            f"{note}"
            "<p>Paste this to an agent. It is short on purpose: it tells the agent "
            "to fetch the full prompt from this console every time it starts, so an "
            "agent onboarded months ago still follows current instructions.</p>"
            "<p><button data-copy='prompt' type='button'>Copy the prompt</button> "
            "<span id='said' class='dim'></span></p>"
            "<textarea id='prompt' readonly rows='16'>"
            f"{html.escape(bootstrap(prompt_url))}</textarea>"
            f"<p class='dim'>It points at <a href='/prompts/agent'><code>"
            f"{html.escape(prompt_url)}</code></a> — the full prompt below, served as "
            "plain text. Written for <code>"
            f"{html.escape(address)}</code>.</p>"
            "<h2>The full prompt</h2>"
            f"<pre>{html.escape(rendered_prompt)}</pre>"
            # The copy behaviour lives in /static/console.js (same-origin), so the CSP
            # can forbid inline scripts. It selects the textarea first, so a browser
            # that withholds the clipboard still leaves the text selected to copy.
        )
        return Response(
            _page("Prompt", body, hub, "/prompts"), media_type=MediaType.HTML
        )

    def _full_prompt(request: Request) -> str:
        """The prompt as served, named by the address it was fetched from.

        The text asks the reader to leave a pointer to this page behind in their
        project's instructions, so it has to know where "here" is. Whichever URL they
        reached it by is the one that demonstrably works for them.

        The version comes from the hub for the same reason the address does: it is the
        version actually running, asked for fresh, rather than the console's own — the
        two are separate containers and can differ across a rolling upgrade.
        """
        hub = hub_or_none() or {}
        address = _advertised(hub, client.config.base)
        # The caution comes from the hub's own descriptor — the same field `hub_info`
        # reports — so an authenticated hub cannot publish the unauthenticated warning.
        return onboarding(
            address,
            f"{_console_base(request)}/prompts/agent",
            _version(hub),
            bool(hub.get("authenticated")),
        )

    @get("/prompts/{role:str}", media_type=MediaType.TEXT, sync_to_thread=True)
    def prompt_for_role(role: str, request: Request) -> str:
        """The whole prompt as plain text — the address agents are pointed at.

        Any role name serves the same text, and that is the point rather than an
        oversight: `/prompts/agent`, `/prompts/host` and `/prompts/admin` are one
        document. Roles are configuration and what a role *means* is fetched from the
        hub, so there is nothing per-role to say here. Accepting the names keeps old
        bookmarks working without reviving three pages to drift apart.
        """
        return _full_prompt(request)

    @get("/prompts.txt", media_type=MediaType.TEXT, sync_to_thread=True)
    def prompt_text(request: Request) -> str:
        """The same prompt again, at the name `curl` users already have."""
        return _full_prompt(request)

    # -- static assets and the flow graph ----------------------------------

    @get("/static/{name:str}", sync_to_thread=True)
    def static_asset(name: str) -> Response:
        """Serve a vendored, same-origin asset (vis-network, console.js).

        Same-origin is the whole point: it is what lets the CSP restrict scripts to
        'self'. Only a small allow-list of files is served, so this cannot be walked
        into the rest of the filesystem.
        """
        allowed = {
            "vis-network.min.js": "application/javascript",
            "console.js": "application/javascript",
            "feed.js": "application/javascript",
            "feed.css": "text/css",
            "icon.svg": "image/svg+xml",
        }
        media = allowed.get(name)
        if media is None:
            raise NotFoundException(f"no such asset: {name}")
        return Response(
            (STATIC_DIR / name).read_bytes(),
            media_type=media,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @get("/graph", media_type=MediaType.HTML, sync_to_thread=True)
    def graph(request: Request) -> Response:
        """The message-flow network graph — who talks to whom, as a live diagram.

        The same data as the dashboard's flow table, drawn with the vendored vis-network
        library: drag the nodes, click one to open its mailbox. Data is injected as a
        non-executable JSON island the same-origin console.js reads — no inline code, no
        external fetch, so it renders cleanly under the strict CSP.
        """
        hub = hub_or_none()
        try:
            stats = seen_by(request).survey()
            actors = seen_by(request).list_agents().get("items", [])
        except ClientError as exc:
            return _err(
                exc,
                hub,
                "Graph",
                api=client.config.base,
                signed_in=_signed_in(request),
            )

        edges = [
            {"from": str(frm), "to": str(to), "count": int(count)}
            for frm, to, count in stats.get("flow", [])
        ]
        # Node size by how much an agent sent (from `busiest`); recency lights it green.
        sent = {str(name): int(n) for name, n in stats.get("busiest", [])}
        recent = {
            a.get("preferredUsername", ""): str(a.get("lastSeen") or "")[:10]
            >= "2026-07-24"
            for a in actors
        }
        names = (
            {e["from"] for e in edges}
            | {e["to"] for e in edges}
            | {a.get("preferredUsername", "") for a in actors}
        )
        nodes = [
            {
                "id": n,
                "label": n,
                "value": sent.get(n, 1) + 1,
                "recent": recent.get(n, False),
            }
            for n in sorted(names)
            if n
        ]
        # Escape `<` so nothing in the data can close the <script> early. Names are
        # already validated to ascii+underscore, so this is belt-and-braces.
        payload = json.dumps({"nodes": nodes, "edges": edges}).replace("<", "\\u003c")

        if not edges:
            inner = (
                '<p class="empty">No messages yet, so there is nothing to graph. '
                "Once agents start writing to each other, the network appears here.</p>"
            )
        else:
            # The JSON goes in a <script type="application/json"> — data, not code, so a
            # strict script-src allows it; console.js parses it and draws the graph.
            inner = (
                f'<p class="dim">{len(nodes)} agents · {len(edges)} channels. '
                "Drag a node; click one to open its mailbox.</p>"
                '<div id="graph" style="height:70vh;border:1px solid var(--line);'
                'border-radius:6px"></div>'
                '<script type="application/json" id="graph-data">'
                f"{payload}</script>"
                '<script src="/static/vis-network.min.js"></script>'
            )
        return Response(
            _page("Graph", "<h2>Message flow</h2>" + inner, hub, "/graph"),
            media_type=MediaType.HTML,
        )

    # -- authentication (the human side) -----------------------------------
    #
    # The console holds no security state: it relays the human's session cookie
    # inward to the hub and the hub's Set-Cookie back out. Every hub call here goes
    # through client.auth_call, which carries the cookie both ways.

    def _relay_cookie(set_cookie: str | None) -> list[Cookie]:
        """Turn the hub's raw Set-Cookie into one the console re-sends onward."""
        if not set_cookie:
            return []
        value = set_cookie.split(";", 1)[0].split("=", 1)[-1]
        return [Cookie(key=SESSION_COOKIE, value=value, httponly=True, path="/")]

    @get("/login", media_type=MediaType.HTML, sync_to_thread=True)
    def login_form() -> Response:
        hub = hub_or_none()
        # Shown only while the hub says nobody has finished setting it up. An operator
        # months in should not still be told where to find a password they replaced —
        # it reads as though the hub were less configured than it is.
        first_run = (
            "<p class='dim'>First run? The password for the account "
            f'"<code>{html.escape(str((hub or {}).get("setupUser", "admin")))}</code>" '
            "has been randomly generated and is visible in the application's start-up "
            "log. You will be asked to set up a password and 2FA after your first "
            "login.</p>"
            if (hub or {}).get("setupRequired") is True
            else ""
        )
        body = (
            "<h2>Sign in</h2>"
            '<form method="post" action="/login/submit">'
            '<label for="u">Username</label>'
            '<input type="text" id="u" name="username" autocomplete="username">'
            '<label for="p">Password</label>'
            '<input type="password" id="p" name="password" '
            'autocomplete="current-password">'
            '<label for="o">6-digit code (blank on first login)</label>'
            '<input type="text" id="o" name="otp" inputmode="numeric" '
            'autocomplete="one-time-code">'
            '<p style="margin-top:.8rem"><button type="submit">Sign in</button></p>'
            "</form>" + first_run
        )
        return Response(
            _page("Sign in", body, hub, "/login"), media_type=MediaType.HTML
        )

    @post("/login/submit", status_code=200, sync_to_thread=True)
    def login_submit(request: Request, data: Form) -> Response:
        hub = hub_or_none()
        payload = {
            "username": str(data.get("username", "")).strip(),
            "password": str(data.get("password", "")),
            "otp": str(data.get("otp", "")).strip() or None,
        }
        try:
            status, body, set_cookie = client.auth_call("POST", "/auth/login", payload)
        except ClientError as exc:
            return _err(exc, hub, "Sign in", api=client.config.base)
        if status != 200:
            msg = (body or {}).get("detail", "sign in failed") if body else "failed"
            page = (
                f'<p class="warn">{html.escape(str(msg))}</p>'
                '<p><a href="/login">Try again</a></p>'
            )
            return Response(
                _page("Sign in", page, hub, "/login"),
                media_type=MediaType.HTML,
                status_code=200,
            )
        target = "/account/enrol" if (body or {}).get("next") == "enrol" else "/"
        return Redirect(target, cookies=_relay_cookie(set_cookie))

    @post("/logout/submit", status_code=200, sync_to_thread=True)
    def logout_submit(request: Request) -> Redirect:
        sid = request.cookies.get(SESSION_COOKIE)
        if sid:
            try:
                client.auth_call("POST", "/auth/logout", {}, session=sid)
            except ClientError:
                pass
        return Redirect(
            "/login",
            cookies=[Cookie(key=SESSION_COOKIE, value="", path="/", max_age=0)],
        )

    @get("/account", media_type=MediaType.HTML, sync_to_thread=True)
    def account(request: Request) -> Response:
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        # Named on the form so a password manager can attribute the credential it is
        # being asked to update. Without an account it has a password belonging to
        # nobody, and offers to save nothing.
        me = acting_for(request)[1]
        if not sid:
            return Response(
                _page(
                    "Account",
                    '<p>You are not signed in. <a href="/login">Sign in</a>.</p>',
                    hub,
                    "/account",
                ),
                media_type=MediaType.HTML,
            )
        body = (
            "<h2>Your account</h2>"
            "<h2>Change password</h2>"
            '<form method="post" action="/account/password/submit">'
            "<label>Account</label>"
            f'<input type="text" name="username" value="{html.escape(me)}" '
            'autocomplete="username" readonly>'
            "<label>Current password</label>"
            '<input type="password" name="current" autocomplete="current-password">'
            "<label>New password</label>"
            '<input type="password" name="new" autocomplete="new-password">'
            '<p style="margin-top:.6rem"><button type="submit">Change</button></p>'
            "</form>"
            '<p><a href="/account/enrol">Re-scan / rotate 2FA</a></p>'
            '<form method="post" action="/logout/submit" style="margin-top:1rem">'
            '<button type="submit">Sign out</button></form>'
        )
        return Response(
            _page("Account", body, hub, "/account"), media_type=MediaType.HTML
        )

    @post("/account/password/submit", status_code=200, sync_to_thread=True)
    def change_password(request: Request, data: Form) -> Response:
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, _ = client.auth_call(
            "POST",
            "/auth/change-password",
            {"current": str(data.get("current", "")), "new": str(data.get("new", ""))},
            session=sid,
        )
        ok = status == 200
        msg = "Password changed." if ok else (body or {}).get("detail", "failed")
        page = f"<p>{html.escape(str(msg))}</p><p><a href='/account'>Back</a></p>"
        return Response(
            _page("Account", page, hub, "/account"), media_type=MediaType.HTML
        )

    @get("/account/enrol", media_type=MediaType.HTML, sync_to_thread=True)
    def enrol_form(request: Request) -> Response:
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        who = acting_for(request)[1]
        if not sid:
            return Redirect("/login")  # type: ignore[return-value]
        status, offer, _ = client.auth_call("GET", "/auth/enrol", session=sid)
        if status != 200 or not offer:
            return Response(
                _page(
                    "Enrol",
                    '<p class="warn">Could not start enrolment. '
                    '<a href="/login">Sign in</a> again.</p>',
                    hub,
                    "/account",
                ),
                media_type=MediaType.HTML,
            )
        codes = "".join(
            f"<li><code>{html.escape(c)}</code></li>" for c in offer["recoveryCodes"]
        )
        body = (
            "<h2>Set up two-factor authentication</h2>"
            "<p>Scan this with Authy or Google Authenticator, then enter the 6-digit "
            "code it shows to confirm.</p>"
            f'<div style="max-width:220px">{offer["qrSvg"]}</div>'
            "<p class='dim'>Save these one-time recovery codes somewhere safe — each "
            "works once if you lose your phone:</p>"
            f"<ul>{codes}</ul>"
            '<form method="post" action="/account/enrol/submit">'
            "<label>Account</label>"
            f'<input type="text" name="username" value="{html.escape(who)}" '
            'autocomplete="username" readonly>'
            "<label>Choose a password</label>"
            '<input type="password" name="password" autocomplete="new-password">'
            "<label>6-digit code from the app</label>"
            '<input type="text" name="otp" inputmode="numeric">'
            '<p style="margin-top:.6rem"><button type="submit">Confirm</button></p>'
            "</form>"
        )
        return Response(
            _page("Enrol", body, hub, "/account"), media_type=MediaType.HTML
        )

    @post("/account/enrol/submit", status_code=200, sync_to_thread=True)
    def enrol_submit(request: Request, data: Form) -> Response:
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, set_cookie = client.auth_call(
            "POST",
            "/auth/enrol",
            {
                "password": str(data.get("password", "")),
                "otp": str(data.get("otp", "")),
            },
            session=sid,
        )
        if status != 200:
            msg = (body or {}).get("detail", "enrolment failed") if body else "failed"
            page = (
                f'<p class="warn">{html.escape(str(msg))}</p>'
                '<p><a href="/account/enrol">Try again</a></p>'
            )
            return Response(
                _page("Enrol", page, hub, "/account"), media_type=MediaType.HTML
            )
        return Redirect("/", cookies=_relay_cookie(set_cookie))

    def _operator_list(people: list[dict[str, Any]], note: str = "") -> str:
        """The humans who can sign in, and their (inert) group."""
        if not people:
            return (
                "<p class='muted'><em>The hub would not say who can sign in.</em></p>"
            )
        rows = "".join(
            "<tr><td><code>{}</code></td><td>{}</td><td>{}</td>"
            "<td class='muted'>{}</td>"
            "<td><form method='post' action='/settings/users/remove' "
            "style='display:inline'><input type='hidden' name='username' value='{}'>"
            "<button type='submit'>Remove</button></form></td></tr>".format(
                html.escape(str(who.get("username", ""))),
                html.escape(str(who.get("email", "")) or "—"),
                html.escape(str(who.get("group", "admin"))),
                "set up" if str(who.get("state", "")) == "active" else "not set up yet",
                html.escape(str(who.get("username", ""))),
            )
            for who in people
        )
        return (
            f"{note}"
            "<table><thead><tr><th>User</th><th>Email</th><th>Group</th>"
            "<th>State</th><th></th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    def _operators_for(sid: str | None) -> list[dict[str, Any]]:
        status, body, _ = client.auth_call("GET", "/operators", session=sid)
        if status != 200 or not isinstance(body, dict):
            return []
        found = body.get("operators")
        return found if isinstance(found, list) else []

    def _peers_for(sid: str | None) -> list[dict[str, Any]]:
        """The trust list, or an empty one if the hub will not say.

        A console that cannot read the list still renders the rest of Settings — the
        alternative is a page that fails entirely because one section could not load.
        """
        status, body, _ = client.auth_call("GET", "/observe/peers", session=sid)
        if status != 200 or not isinstance(body, dict):
            return []
        found = body.get("peers")
        return found if isinstance(found, list) else []

    def _peer_list(peers: list[dict[str, Any]]) -> str:
        """The trust list, or an honest empty state.

        An empty list is the *normal* starting state and the reason federation appears
        not to work, so it says that rather than showing a bare "none".
        """
        if not peers:
            return (
                "<p class='muted'><em>No hubs are trusted yet, so no mail can cross "
                "in either direction.</em></p>"
            )
        rows = "".join(
            "<tr><td><code>{}</code></td><td class='muted'>{}</td><td>"
            "<form method='post' action='/settings/peers/remove' "
            "style='display:inline'>"
            "<input type='hidden' name='origin' value='{}'>"
            "<button type='submit'>Stop trusting</button></form></td></tr>".format(
                html.escape(str(peer.get("origin", ""))),
                html.escape(str(peer.get("added", ""))),
                html.escape(str(peer.get("origin", ""))),
            )
            for peer in peers
        )
        return (
            "<table><thead><tr><th>Hub</th><th>Trusted since</th><th></th></tr>"
            f"</thead><tbody>{rows}</tbody></table>"
        )

    def _settings_page(
        settings: dict[str, Any],
        hub: dict[str, Any] | None,
        note: str = "",
        peer_result: str = "",
        peers: list[dict[str, Any]] | None = None,
        people: list[dict[str, Any]] | None = None,
        user_note: str = "",
    ) -> str:
        """Everything an operator configures, in sections.

        A container, not a page about federation. Federation is the first section and
        retention, expiry and the rest join it — so a section is a heading and a block,
        and adding the next one should mean adding a block rather than reshaping this.
        """
        rows = []
        for key, label, hint in (
            (
                "name",
                "Hub name",
                "The <code>@hub</code> part of an address. Lowercase "
                "letters, digits and underscores. Not the hub's web address.",
            ),
            ("title", "Title", "A display name. Free text."),
            ("description", "Description", "What this hub is for, and who runs it."),
        ):
            field = settings.get(key) or {}
            value = html.escape(str(field.get("value") or ""))
            source = str(field.get("source", "default"))
            variable = field.get("variable")
            if source == "environment":
                # Shown, not offered. A greyed box with no explanation reads as broken;
                # one naming the variable reads as governed. The variable comes from the
                # API because a deployment may be configured through the legacy prefix,
                # and naming the wrong one sends the operator to edit the wrong thing.
                control = (
                    f'<input name="{key}" value="{value}" disabled>'
                    f'<p class="muted">Set by this deployment through '
                    f"<code>{html.escape(str(variable))}</code>. Change it there, or "
                    f"unset it to use the value stored here.</p>"
                )
            else:
                control = f'<input name="{key}" value="{value}">'
            rows.append(
                f'<p><label for="{key}"><strong>{label}</strong></label><br>'
                f'{control}<br><span class="muted">{hint}</span></p>'
            )

        version = html.escape(str(settings.get("version", "")))
        body = (
            "<h2>Settings</h2>"
            f"{note}"
            "<h3>Federation</h3>"
            "<p class='muted'>How this hub identifies itself. The hub's name "
            "appears in every address on it, so it is worth setting before anyone "
            "writes one down.</p>"
            "<h3>Trusted hubs</h3>"
            "<p class='muted'>Peering gates federation in <strong>both</strong> "
            "directions: this hub will not send to a hub that is not listed here, and "
            "will not accept mail from one. A hub with no peers can neither send nor "
            "receive, so this list is what switches federation on in practice.</p>"
            "<p class='muted'>Trust is not mutual by default. For mail to flow both "
            "ways, each hub must list the other.</p>"
            f"{_peer_list(peers or [])}"
            "<form method='post' action='/settings/peers/add'>"
            "<p><input name='origin' placeholder='https://hub.example' size='40'>"
            " <button type='submit'>Trust this hub</button></p></form>"
            "<h3>Check another hub</h3>"
            "<p class='muted'>Ask a hub who it is. Nothing is stored and no peering "
            "happens — this reads its public NodeInfo document, which is what a peer "
            "would read of us.</p>"
            f"{peer_result}"
            "<form method='post' action='/settings/peer'>"
            "<p><input name='url' placeholder='https://hub.example' size='40'>"
            " <button type='submit'>Check</button></p></form>"
            "<h3>Users</h3>"
            "<p class='muted'>Everyone who can sign in to this console. <strong>Every "
            "user is an admin today</strong> — each one can add and remove the others, "
            "including whoever set the hub up.</p>"
            f"{_operator_list(people or [], user_note)}"
            "<p class='muted'>The last remaining user cannot be removed, so the hub "
            "always has a way in. Whoever owns the hosting can also recover "
            "through the admin-password environment variable.</p>"
            "<form method='post' action='/settings/users/add'>"
            "<p><input name='username' placeholder='username' size='18'>"
            " <input name='email' placeholder='email (for future recovery)' size='28'>"
            " <select name='group'>"
            "<option value='admin'>admin</option>"
            "<option value='user'>user</option>"
            "</select>"
            " <button type='submit'>Add user</button></p></form>"
            "<p class='muted'><strong>Groups do nothing yet.</strong> They are "
            "recorded and shown, and no check anywhere reads them — an account marked "
            "<code>user</code> can do everything an <code>admin</code> can. The "
            "intention is that <code>admin</code> may add and remove users while "
            "<code>user</code> is read-only and may mint tokens. Until that is "
            "built, do not rely on this to restrain anybody.</p>"
            "<h3>This hub</h3>"
            "<form method='post' action='/settings/save'>"
            f'<input type="hidden" name="version" value="{version}">'
            + "".join(rows)
            + "<button type='submit'>Save</button></form>"
        )
        return _page("Settings", body, hub, "/settings")

    @get("/settings", media_type=MediaType.HTML, sync_to_thread=True)
    def settings_view(request: Request) -> Response:
        """What this hub is configured to be."""
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, _ = client.auth_call("GET", "/hub/settings", session=sid)
        if status != 200:
            return Response(
                _refused(body, "the hub would not say how it is configured", hub),
                media_type=MediaType.HTML,
            )
        return Response(
            _settings_page(
                body or {},
                hub,
                peers=_peers_for(sid),
                people=_operators_for(sid),
            ),
            media_type=MediaType.HTML,
        )

    @post("/settings/save", status_code=200, sync_to_thread=True)
    def settings_save(request: Request, data: Form) -> Response:
        """Save what the operator changed, and say what the hub made of it.

        Governed fields are `disabled`, so a browser does not submit them — that is the
        behaviour this relies on, deliberately rather than incidentally. The `version`
        goes back with the write so a page rendered under different configuration is
        refused rather than storing the deployment's value over the operator's own.
        """
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        changes: dict[str, Any] = {
            k: str(v) for k, v in data.items() if k in ("name", "title", "description")
        }
        if "version" in data:
            changes["version"] = str(data["version"])
        status, body, _ = client.auth_call("PUT", "/hub", changes, session=sid)
        if status != 200:
            detail = (body or {}).get("detail") or "the hub refused that change"
            note = (
                "<p class='muted'><strong>Not saved.</strong> "
                f"{html.escape(str(detail))}</p>"
            )
            fresh_status, fresh, _ = client.auth_call(
                "GET", "/hub/settings", session=sid
            )
            return Response(
                _settings_page(
                    fresh or {},
                    hub,
                    note,
                    peers=_peers_for(sid),
                    people=_operators_for(sid),
                ),
                media_type=MediaType.HTML,
            )
        # Re-render from what the hub returned, not from what was submitted: the two
        # differ whenever the environment governs, and showing the submission would say
        # a change took effect when it did not.
        return Response(
            _settings_page(
                body or {},
                hub,
                "<p class='muted'>Saved.</p>",
                peers=_peers_for(sid),
                people=_operators_for(sid),
            ),
            media_type=MediaType.HTML,
        )

    @post("/settings/users/add", status_code=200, sync_to_thread=True)
    def settings_user_add(request: Request, data: Form) -> Response:
        """Invite a human, and show their one-time password **once**.

        The hub sends no mail, so the password is displayed for the operator to pass on
        themselves. It is shown exactly once and never stored in a form anyone can read
        back.
        """
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, _ = client.auth_call(
            "POST",
            "/operators",
            {
                "username": str(data.get("username", "")).strip(),
                "email": str(data.get("email", "")).strip(),
                "group": str(data.get("group", "admin")),
            },
            session=sid,
        )
        if status not in (200, 201):
            detail = (body or {}).get("detail") or "the hub refused that user"
            note = (
                "<p class='muted'><strong>Not added.</strong> "
                f"{html.escape(str(detail))}</p>"
            )
        else:
            who = html.escape(str((body or {}).get("username", "")))
            password = html.escape(str((body or {}).get("password", "")))
            note = (
                f"<p><strong>Added {who}.</strong> Their one-time password is "
                f"<code>{password}</code> — <strong>shown once</strong>. Pass it on "
                "yourself; this hub sends no mail. They must set their own password "
                "and enrol a second factor before the account can do anything.</p>"
            )
        fresh_status, fresh, _ = client.auth_call("GET", "/hub/settings", session=sid)
        return Response(
            _settings_page(
                fresh or {},
                hub,
                peers=_peers_for(sid),
                people=_operators_for(sid),
                user_note=note,
            ),
            media_type=MediaType.HTML,
        )

    @post("/settings/users/remove", status_code=200, sync_to_thread=True)
    def settings_user_remove(request: Request, data: Form) -> Response:
        """Remove a human. The hub refuses the last one."""
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        username = str(data.get("username", "")).strip()
        status, body, _ = client.auth_call(
            "DELETE", f"/operators/{username}", session=sid
        )
        note = (
            f"<p class='muted'>Removed <code>{html.escape(username)}</code>. Any "
            "session they held stopped working immediately.</p>"
            if status == 200
            else "<p class='muted'><strong>Not removed.</strong> "
            f"{html.escape(str((body or {}).get('detail', 'the hub refused')))}</p>"
        )
        fresh_status, fresh, _ = client.auth_call("GET", "/hub/settings", session=sid)
        return Response(
            _settings_page(
                fresh or {},
                hub,
                peers=_peers_for(sid),
                people=_operators_for(sid),
                user_note=note,
            ),
            media_type=MediaType.HTML,
        )

    @post("/settings/peers/add", status_code=200, sync_to_thread=True)
    def settings_peer_add(request: Request, data: Form) -> Response:
        """Trust a hub.

        Nothing is contacted: peering is a local statement about who *we* trust, and a
        peer that is asleep must still be addable — otherwise two hubs could never be
        introduced to each other except while both happened to be up.
        """
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        origin = str(data.get("origin", "")).strip()
        status, body, _ = client.auth_call(
            "POST", "/observe/peers", {"origin": origin}, session=sid
        )
        if status not in (200, 201):
            detail = (body or {}).get("detail") or "the hub refused that peer"
            note = (
                "<p class='muted'><strong>Not added.</strong> "
                f"{html.escape(str(detail))}</p>"
            )
        else:
            note = (
                "<p class='muted'>Trusted "
                f"<code>{html.escape(str((body or {}).get('origin', origin)))}</code>. "
                "For mail to flow both ways, that hub must trust this one too.</p>"
            )
        fresh_status, fresh, _ = client.auth_call("GET", "/hub/settings", session=sid)
        return Response(
            _settings_page(
                fresh or {},
                hub,
                note,
                peers=_peers_for(sid),
                people=_operators_for(sid),
            ),
            media_type=MediaType.HTML,
        )

    @post("/settings/peers/remove", status_code=200, sync_to_thread=True)
    def settings_peer_remove(request: Request, data: Form) -> Response:
        """Stop trusting a hub.

        Mail already received stays. It is **ours** — our retention, our schedule — and
        a peer losing our trust does not reach back into our store, in either direction.
        """
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        origin = str(data.get("origin", "")).strip()
        status, body, _ = client.auth_call(
            "DELETE", f"/observe/peers?origin={origin}", session=sid
        )
        note = (
            "<p class='muted'>No longer trusting "
            f"<code>{html.escape(origin)}</code>. Mail already received stays.</p>"
            if status == 200
            else "<p class='muted'><strong>Not removed.</strong> "
            f"{html.escape(str((body or {}).get('detail', 'the hub refused')))}</p>"
        )
        fresh_status, fresh, _ = client.auth_call("GET", "/hub/settings", session=sid)
        return Response(
            _settings_page(
                fresh or {},
                hub,
                note,
                peers=_peers_for(sid),
                people=_operators_for(sid),
            ),
            media_type=MediaType.HTML,
        )

    @post("/settings/peer", status_code=200, sync_to_thread=True)
    def settings_peer(request: Request, data: Form) -> Response:
        """Ask another hub who it is, and show the answer.

        Reads only. Nothing is stored, no peering is arranged, and the hub being asked
        learns nothing about us beyond that someone fetched a public document.

        Everything shown is **that hub's claim**, not our finding, and the page says so
        — an operator reading a peer's title should not mistake it for something we
        verified.
        """
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        url = str(data.get("url", "")).strip()
        if not url:
            block = "<p class='muted'>Give a hub's address to check it.</p>"
        else:
            try:
                who = identify(url)
            except MailboxError as refusal:
                block = (
                    "<p class='warn'><strong>Could not read that hub.</strong> "
                    f"{html.escape(str(refusal))}</p>"
                )
            else:
                rows = [
                    ("Address", who.base),
                    ("Software", f"{who.software} {who.version}"),
                    ("Federating", "yes" if who.federates else "no"),
                ]
                if who.title:
                    rows.append(("Title", who.title))
                if who.description:
                    rows.append(("Description", who.description))
                if who.users is not None:
                    rows.append(("Agents", str(who.users)))
                cells = "".join(
                    f"<tr><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>"
                    for k, v in rows
                )
                block = (
                    "<table><tbody>" + cells + "</tbody></table>"
                    "<p class='muted'>Everything above is what that hub says about "
                    "itself. None of it is verified.</p>"
                )

        status, body, _ = client.auth_call("GET", "/hub/settings", session=sid)
        return Response(
            _settings_page(body or {}, hub, "", block), media_type=MediaType.HTML
        )

    def _gate(request: Request) -> Response | None:
        """Require a session for the console's own pages once the hub authenticates.

        Relying on the API to refuse was not enough: a page that happens not to call a
        guarded route still rendered, which is how `/tokens` showed a stranger every
        agent on the hub while `/` was correctly redirecting to sign-in. A screen is
        allowed only if it is needed *before* anyone can sign in.

        This is a gate, not a check — the console holds no security state and does not
        judge the cookie, it only insists one is present. The hub remains the authority
        on whether that session is real, and refuses on every route that matters.
        """
        path = request.url.path
        if path in OPEN_PATHS or path.startswith(("/prompts", "/static/")):
            return None
        if request.cookies.get(SESSION_COOKIE):
            return None
        if (hub_or_none() or {}).get("authenticated") is not True:
            return None  # off or warn: unchanged, a trusted LAN needs no login
        return Redirect("/login")

    return Litestar(
        on_startup=[ensure_own_mailbox],
        before_request=_gate,
        after_request=_add_csp,
        route_handlers=[
            health,
            change_password_url,
            overview,
            agents,
            graph,
            static_asset,
            mailbox,
            message,
            inbox,
            do_read,
            compose_form,
            do_compose,
            maintenance,
            maintenance_purge,
            settings_view,
            settings_save,
            settings_peer,
            settings_user_add,
            settings_user_remove,
            settings_peer_add,
            settings_peer_remove,
            token_index,
            mint,
            revoke,
            prompts,
            prompt_for_role,
            prompt_text,
            login_form,
            login_submit,
            logout_submit,
            account,
            change_password,
            enrol_form,
            enrol_submit,
        ],
    )
