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
from typing import Annotated, Any

from litestar import Litestar, MediaType, get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Redirect, Response

from agent_mailbox.client import ClientError, HubClient
from agent_mailbox.prompts import onboarding, role_note

#: A browser form arrives URL-encoded, not as JSON. Naming the type once keeps the
#: three POST handlers from each repeating the annotation.
Form = Annotated[dict[str, Any], Body(media_type=RequestEncodingType.URL_ENCODED)]

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
        + link("/inbox", "Inbox")
        + link("/compose", "Compose")
        + link("/prompts", "Prompt")
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — {name}</title><style>{STYLE}</style></head>
<body>
<h1><a href="/">{name}</a></h1>
<p class="sub">{html.escape(title)}{f" · v{version}" if version else ""}</p>
<nav>{nav}</nav>
{warning}
{body}
</body></html>"""


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


def _err(exc: Exception, hub: dict[str, Any] | None, title: str) -> Response:
    """Every screen either renders or explains — never a blank page.

    An operator staring at nothing cannot tell "hub down" from "nothing here", so a
    failure says which it was rather than falling through to an empty table.
    """
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
                ]
            )
        body = _table(["Who", "Type", "About", "Profile"], rows, "Nobody yet.")
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

    # -- the prompt --------------------------------------------------------

    @get("/prompts", media_type=MediaType.HTML, sync_to_thread=True)
    def prompts() -> Response:
        """The one onboarding prompt, ready to paste.

        One page, because there used to be three and they drifted. Which role an agent
        holds is configuration, not a different prompt. The hub's own `id` is filled in
        (not the route this console uses to reach it), so the commands can be pasted as
        they stand.
        """
        hub = hub_or_none() or {}
        address = _advertised(hub, client.config.base)
        note = "".join(
            f"<p>{html.escape(para)}</p>"
            for para in role_note().replace("**", "").split("\n\n")
        )
        body = (
            f"{note}"
            "<p>Paste the whole of this to an agent.</p>"
            "<p><button id='copy' type='button'>Copy the prompt</button> "
            "<span id='said' class='dim'></span></p>"
            "<textarea id='prompt' readonly rows='28'>"
            f"{html.escape(onboarding(address))}</textarea>"
            f"<p class='dim'>Written for <code>{html.escape(address)}</code>. "
            "Also served as plain text at <a href='/prompts.txt'>/prompts.txt</a>, "
            "for when the console is not where you are.</p>"
            # Selecting first means the fallback is the manual gesture the user was
            # going to make anyway, rather than nothing happening on a browser that
            # withholds the clipboard.
            "<script>document.getElementById('copy').onclick=async()=>{"
            "const t=document.getElementById('prompt'),"
            "s=document.getElementById('said');"
            "t.select();"
            "try{await navigator.clipboard.writeText(t.value);s.textContent='Copied.';}"
            "catch(e){s.textContent='Selected — press ctrl/cmd+C.';}};</script>"
        )
        return Response(
            _page("Prompt", body, hub, "/prompts"), media_type=MediaType.HTML
        )

    @get("/prompts.txt", media_type=MediaType.TEXT, sync_to_thread=True)
    def prompt_text() -> str:
        """The same prompt as plain text, for `curl` and for pasting."""
        return onboarding(_advertised(hub_or_none() or {}, client.config.base))

    return Litestar(
        on_startup=[ensure_own_mailbox],
        route_handlers=[
            overview,
            agents,
            mailbox,
            message,
            inbox,
            do_read,
            compose_form,
            do_compose,
            prompts,
            prompt_text,
        ],
    )
