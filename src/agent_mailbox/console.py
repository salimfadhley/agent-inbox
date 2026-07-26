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

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Annotated, Any

from litestar import Litestar, MediaType, Request, get, post
from litestar.datastructures import Cookie
from litestar.enums import RequestEncodingType
from litestar.exceptions import NotFoundException
from litestar.params import Body
from litestar.response import Redirect, Response

from agent_mailbox import __version__
from agent_mailbox.auth.records import SHARED_ACTOR
from agent_mailbox.client import SESSION_COOKIE, ClientError, HubClient
from agent_mailbox.prompts import bootstrap, onboarding, role_note

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

#: Reachable without signing in, once the hub authenticates. Each earns it by being
#: needed *before* anyone can sign in: the way in, the way out, the container's health
#: probe, and the onboarding prompt — which is how a new agent is set up in the first
#: place and holds nothing secret. Everything else is behind the gate.
#: `/prompts*` and `/static/*` are matched by prefix alongside this set.
OPEN_PATHS = frozenset({"/login", "/login/submit", "/logout/submit", "/health"})

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
.dot.off { background: var(--line); }
textarea, input[type=text] { width: 100%; font: 13px/1.45 ui-monospace, monospace;
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
        f'<a href="{PROJECT_URL}">agent-inbox on GitHub</a></footer>'
    )


def _page(title: str, body: str, hub: dict[str, Any] | None, here: str = "") -> str:
    name = html.escape(str((hub or {}).get("name", "agent-mailbox")))
    version = html.escape(str((hub or {}).get("version", "")))
    unauthenticated = (hub or {}).get("authenticated") is False
    warning = (
        '<p class="warn"><strong>This hub does not authenticate.</strong> '
        "Anyone who can reach it can claim to be anyone, and this console can watch "
        "every mailbox. Suitable for a trusted network only.</p>"
        if unauthenticated
        else ""
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
        + link("/account", "Account")
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="/static/icon.svg">
<title>{html.escape(title)} — {name}</title><style>{STYLE}</style></head>
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
    """Attach the Content-Security-Policy to every response, from one place.

    An `after_request` hook rather than a per-handler header, so the CSP cannot be
    forgotten on a single route — which is exactly how a script-injection hole opens.
    """
    response.headers["Content-Security-Policy"] = CSP
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


def _err(exc: Exception, hub: dict[str, Any] | None, title: str) -> Response:
    """Every screen either renders or explains — never a blank page.

    An operator staring at nothing cannot tell "hub down" from "nothing here", so a
    failure says which it was rather than falling through to an empty table.

    A hub that refuses for want of a credential is not a fault to report but a door to
    open: on an enforcing hub *every* page fails this way until someone signs in, and
    meeting a first-time operator with a 502 about their own hub would be absurd. So
    that one case redirects to the sign-in page instead.
    """
    if _needs_login(exc):
        return Redirect("/login")
    body = (
        '<p class="warn">The hub did not answer this request: '
        f"{html.escape(str(exc))}</p>"
    )
    return Response(_page(title, body, hub), media_type=MediaType.HTML, status_code=502)


def build_console(client: HubClient) -> Litestar:
    """A window onto one hub: watch anyone, act as yourself."""

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
    def overview() -> Response:
        hub = hub_or_none()
        try:
            stats = client.survey()
            actors = client.list_agents().get("items", [])
        except ClientError as exc:
            return _err(exc, hub, "Overview")

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
            ["", "Who", "Role", "Last seen"], online_rows, "Nobody has joined yet."
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
            # No heartbeat exists, so "recent" is the honest word, not "online": a
            # green dot means seen today, nothing more.
            recent = str(last)[:10] >= "2026-07-24"
            dot = f'<span class="dot{"" if recent else " off"}"></span>'
            rows.append(
                [
                    dot,
                    _mbox_link(name),
                    html.escape(str(profile.get("role", "") or "")),
                    f'<span class="dim">{html.escape(_shortdate(last))}</span>',
                ]
            )
        return rows

    @get("/agents", media_type=MediaType.HTML, sync_to_thread=True)
    def agents() -> Response:
        hub = hub_or_none()
        try:
            actors = client.list_agents().get("items", [])
        except ClientError as exc:
            return _err(exc, hub, "Agents")
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
                    f'<a href="/tokens/{html.escape(name)}">Tokens</a>',
                ]
            )
        body = _table(["Who", "Type", "About", "Profile", "Keys"], rows, "Nobody yet.")
        return Response(
            _page("Agents", body, hub, "/agents"), media_type=MediaType.HTML
        )

    @get("/mailbox/{name:str}", media_type=MediaType.HTML, sync_to_thread=True)
    def mailbox(name: str) -> Response:
        """Everything addressed to one agent — read or not, **without consuming it**.

        Reads `/observe/mailbox/{name}`, which takes no caller. The operator looks; the
        agent still has all of its mail. This is the route that replaced impersonation.
        """
        hub = hub_or_none()
        try:
            items = client.observe_mailbox(name).get("items", [])
            info = client.whois(name)
        except ClientError as exc:
            return _err(exc, hub, name)

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
    def message(object_id: str) -> Response:
        """One message and the **whole** thread it belongs to.

        Uses `/observe/objects/{id}/thread`, so it shows the conversation entire —
        including turns no single participant is party to. That is the operator's view,
        and the reason it is not the agent-facing `read_thread`.
        """
        hub = hub_or_none()
        try:
            turns = client.observe_thread(object_id).get("items", [])
            detail = client.observe_object(object_id)
        except ClientError as exc:
            return _err(exc, hub, "Message")

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
    def inbox() -> Response:
        """The console's *own* mail — this is the one mailbox it may consume.

        Everything else on this console watches without touching. Here the operator is
        an ordinary participant reading their own inbox, which needs no special power
        and marks messages read exactly as any agent would.
        """
        hub = hub_or_none()
        me = client.config.name
        try:
            items = client.check_inbox().get("items", [])
        except ClientError as exc:
            return _err(exc, hub, "Inbox")
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
    def do_read(data: Form) -> Redirect:
        oid = str(data.get("id", "")).strip()
        if oid:
            try:
                client.read_message(oid)
            except ClientError:
                pass  # the inbox will simply still show it; no page to break
        return Redirect("/inbox")

    @get("/compose", media_type=MediaType.HTML, sync_to_thread=True)
    def compose_form() -> Response:
        hub = hub_or_none()
        me = html.escape(client.config.name)
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
    def do_compose(data: Form) -> Response:
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
            client.send_message(recipients, body_text, subject=subject)
        except ClientError as exc:
            return _err(exc, hub, "Compose")
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

    # -- device tokens -----------------------------------------------------

    def _token_instructions(name: str, secret: str) -> str:
        """What to do with a token, shown at the only moment it is visible.

        The hub stores a hash, so this is the one and only time anyone can read it.
        Anything the agent needs must therefore be on this page, in a form that can be
        pasted — not a description of the file, but the command that writes it.
        """
        return (
            '<div class="warn"><p><strong>Copy it now.</strong> The hub keeps only a '
            "hash, so this is the only time it can be read. If it is lost, mint "
            "another and revoke this one.</p>"
            f"<p><code>{html.escape(secret)}</code></p></div>"
            + (
                "<p>Put it in <code>~/.config/agent-inbox/config.toml</code> on the "
                "machine it is for. Every agent there is then admitted, whatever name "
                "each of them uses — there is nothing to do per agent and nothing to "
                "repeat per project:</p>"
                f'<pre>token = "{html.escape(secret)}"</pre>'
                "<p>Any agent on that machine can confirm it with "
                "<code>agent-mailbox doctor</code>.</p>"
                if name == SHARED_ACTOR
                else "<p>Give it to the agent and have it run:</p>"
                f"<pre>agent-mailbox join {html.escape(name)} "
                f"--token {html.escape(secret)}</pre>"
                "<p>That writes the token into <code>agent-mailbox.toml</code> in the "
                "agent's project root, under its own engine's entry, and it is sent "
                "automatically from then on. <code>agent-mailbox doctor</code> "
                "confirms it works.</p>"
            )
        )

    def _tokens_page(request: Request, name: str, extra: str = "") -> Response:
        """List an agent's device tokens, and offer to mint another.

        Operator-only, and the console holds none of that judgement itself — it relays
        the human's session inward and reports whatever the hub decides.
        """
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, _ = client.auth_call(
            "GET", f"/auth/agents/{name}/tokens", session=sid
        )
        if status in (401, 403):
            page = (
                f"<p>Minting a token for <code>{html.escape(name)}</code> is an "
                "operator action. <a href='/login'>Sign in</a> first.</p>"
            )
            return Response(
                _page("Tokens", page, hub, "/agents"), media_type=MediaType.HTML
            )
        if status >= 400:
            detail = (body or {}).get("detail", "the hub refused")
            hint = (
                "<p class='dim'>This hub has authentication turned off, so device "
                "tokens do nothing here. Set <code>AGENT_MAILBOX_AUTH_MODE</code> to "
                "<code>warn</code> or <code>enforce</code> to use them.</p>"
                if (hub or {}).get("authenticated") is False
                else ""
            )
            page = f"<p>{html.escape(str(detail))}</p>{hint}"
            return Response(
                _page("Tokens", page, hub, "/agents"), media_type=MediaType.HTML
            )

        safe = html.escape(name)

        def actions(t: dict[str, Any]) -> str:
            if t.get("revoked"):
                return '<span class="dim">revoked</span>'
            tid = html.escape(str(t.get("id", "")))
            return (
                f'<form method="post" action="/tokens/{safe}/revoke">'
                f'<input type="hidden" name="id" value="{tid}">'
                "<button type='submit'>Revoke</button></form>"
            )

        rows = [
            [
                f"<code>{html.escape(str(t.get('id', '')))}</code>",
                html.escape(str(t.get("label") or "")),
                f'<span class="dim">{_shortdate(str(t.get("created") or ""))}</span>',
                '<span class="dim">'
                f"{_shortdate(str(t.get('lastUsed') or '')) or 'never'}</span>",
                actions(t),
            ]
            for t in (body or {}).get("items", [])
        ]
        page = (
            f"<h2>Device tokens for <code>{safe}</code></h2>"
            f"{extra}"
            + _table(
                ["Id", "Label", "Created", "Last used", ""],
                rows,
                "No tokens. This agent cannot authenticate yet.",
            )
            + "<h2>Mint a token</h2>"
            f'<form method="post" action="/tokens/{safe}/mint">'
            "<label>Label (what machine or session is this for?)</label>"
            '<input type="text" name="label" placeholder="laptop, ci, …">'
            "<p style='margin-top:.6rem'><button type='submit'>Mint</button></p>"
            "</form>"
        )
        return Response(
            _page("Tokens", page, hub, "/agents"), media_type=MediaType.HTML
        )

    @get("/tokens", media_type=MediaType.HTML, sync_to_thread=True)
    def token_index() -> Response:
        """Every agent, and the way in to minting one a key.

        This exists because the per-agent page was reachable only from an unlabelled
        column at the end of the directory table — which is to say, not reachable. A
        capability nobody can find is the same as one that was never built, and this
        one had already been built twice: the API could mint before any page could.
        """
        hub = hub_or_none()
        try:
            actors = client.list_agents().get("items", [])
        except ClientError as exc:
            return _err(exc, hub, "Tokens")
        rows = [
            [
                _mbox_link(a.get("preferredUsername", "")),
                '<span class="dim">'
                f"{html.escape((a.get('summary') or '')[:60])}</span>",
                f'<a href="/tokens/{html.escape(a.get("preferredUsername", ""))}">'
                "Tokens</a>",
            ]
            for a in actors
        ]
        # The hub descriptor says whether tokens are *required*, not which mode is set —
        # `authMode` lives on /doctor, and quoting a field that is not here would print
        # a confident "auth off" at a hub that is merely warning.
        note = (
            '<p class="warn">This hub does not require a token yet, so mail works '
            "without one. Minting now is still worth doing: an agent that already has "
            "a token keeps working on the day enforcement is turned on, and one that "
            "does not is locked out until someone is at a keyboard.</p>"
            if (hub or {}).get("authenticated") is False
            else ""
        )
        body = (
            "<p>A device token is how an agent proves it may use this hub once "
            "authentication is enforced. Each is shown once and can be revoked "
            "on its own.</p>"
            f"{note}"
            "<h2>One token for a whole machine</h2>"
            "<p>A <strong>shared</strong> token names no agent: it admits whoever "
            "holds it, and each agent still says which name it is using. Put one in "
            "<code>~/.config/agent-inbox/config.toml</code> and every agent on that "
            "machine is admitted, without minting one apiece.</p>"
            '<pre>token = "…"</pre>'
            "<p class='dim'>The trade is real: anyone who can read that file can act "
            "as any agent here. That is the right trade for your own laptop and the "
            "wrong one for a machine you share — mint per-agent tokens there.</p>"
            f'<form method="post" action="/tokens/{SHARED_ACTOR}/mint">'
            "<label>Label (which machine is this for?)</label>"
            '<input type="text" name="label" placeholder="workshop laptop">'
            "<p style='margin-top:.6rem'>"
            "<button type='submit'>Mint a shared token</button></p></form>"
            "<h2>Per-agent tokens</h2>"
            + _table(["Agent", "About", ""], rows, "Nobody has joined yet.")
        )
        return Response(
            _page("Tokens", body, hub, "/tokens"), media_type=MediaType.HTML
        )

    @get("/tokens/{name:str}", media_type=MediaType.HTML, sync_to_thread=True)
    def tokens(name: str, request: Request) -> Response:
        return _tokens_page(request, name)

    @post("/tokens/{name:str}/mint", status_code=200, sync_to_thread=True)
    def mint(name: str, request: Request, data: Form) -> Response:
        hub = hub_or_none()
        sid = request.cookies.get(SESSION_COOKIE)
        status, body, _ = client.auth_call(
            "POST",
            f"/auth/agents/{name}/tokens",
            {"label": str(data.get("label", ""))},
            session=sid,
        )
        if status not in (200, 201):
            detail = (body or {}).get("detail", "the hub refused to mint a token")
            return Response(
                _page(
                    "Tokens",
                    f"<p>{html.escape(str(detail))}</p>"
                    f"<p><a href='/tokens/{html.escape(name)}'>Back</a></p>",
                    hub,
                    "/agents",
                ),
                media_type=MediaType.HTML,
            )
        return _tokens_page(
            request, name, _token_instructions(name, str((body or {}).get("token", "")))
        )

    @post("/tokens/{name:str}/revoke", status_code=200, sync_to_thread=True)
    def revoke(name: str, request: Request, data: Form) -> Response:
        sid = request.cookies.get(SESSION_COOKIE)
        token_id = str(data.get("id", ""))
        status, body, _ = client.auth_call(
            "DELETE", f"/auth/agents/{name}/tokens/{token_id}", session=sid
        )
        note = (
            "<p>Revoked. Any agent still using it is now locked out.</p>"
            if status in (200, 204)
            else f"<p>{html.escape(str((body or {}).get('detail', 'failed')))}</p>"
        )
        return _tokens_page(request, name, note)

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
        body = (
            f"{note}"
            "<p>Paste this to an agent. It is short on purpose: it tells the agent "
            "to fetch the full prompt from this console every time it starts, so an "
            "agent onboarded months ago still follows current instructions.</p>"
            "<p><button id='copy' type='button'>Copy the prompt</button> "
            "<span id='said' class='dim'></span></p>"
            "<textarea id='prompt' readonly rows='16'>"
            f"{html.escape(bootstrap(prompt_url))}</textarea>"
            f"<p class='dim'>It points at <a href='/prompts/agent'><code>"
            f"{html.escape(prompt_url)}</code></a> — the full prompt below, served as "
            "plain text. Written for <code>"
            f"{html.escape(address)}</code>.</p>"
            "<h2>The full prompt</h2>"
            f"<pre>{html.escape(onboarding(address, prompt_url, _version(hub)))}</pre>"
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
        return onboarding(
            address, f"{_console_base(request)}/prompts/agent", _version(hub)
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
    def graph() -> Response:
        """The message-flow network graph — who talks to whom, as a live diagram.

        The same data as the dashboard's flow table, drawn with the vendored vis-network
        library: drag the nodes, click one to open its mailbox. Data is injected as a
        non-executable JSON island the same-origin console.js reads — no inline code, no
        external fetch, so it renders cleanly under the strict CSP.
        """
        hub = hub_or_none()
        try:
            stats = client.survey()
            actors = client.list_agents().get("items", [])
        except ClientError as exc:
            return _err(exc, hub, "Graph")

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
            '<input type="text" id="p" name="password" '
            'style="-webkit-text-security:disc" autocomplete="current-password">'
            '<label for="o">6-digit code (blank on first login)</label>'
            '<input type="text" id="o" name="otp" inputmode="numeric">'
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
            return _err(exc, hub, "Sign in")
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
            "<label>Current password</label>"
            '<input type="text" name="current" style="-webkit-text-security:disc">'
            "<label>New password</label>"
            '<input type="text" name="new" style="-webkit-text-security:disc">'
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
            "<label>Choose a password</label>"
            '<input type="text" name="password" style="-webkit-text-security:disc">'
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
            token_index,
            tokens,
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
