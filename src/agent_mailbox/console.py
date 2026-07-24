"""The human console — a browser client of the same API.

Server-rendered HTML, no JavaScript framework, no build step. It is a *client*
(ADR 0005): it holds no messaging semantics and reaches the hub over HTTP exactly as the
CLI does. If a screen ever needs to decide something about messaging, the API is missing
a route.

**Observing never consumes.** The operator can look into any mailbox, and looking must
not mark anything read — reading an agent's mail *for* it would steal it. That is why
these screens use the observation routes rather than `read`.

Deliberately plain. An operator wants to see what is happening at a glance; a single
stylesheet and a handful of tables do that, and there is nothing to build or install.
"""

from __future__ import annotations

import html
from typing import Any

from litestar import Litestar, MediaType, get
from litestar.response import Response

from agent_mailbox.client import HubClient
from agent_mailbox.prompts import onboarding, role_note

STYLE = """
:root { color-scheme: light dark; --line: #8884; }
* { box-sizing: border-box; }
body { font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; margin: 0;
       padding: 1.5rem clamp(1rem, 4vw, 3rem); max-width: 60rem; }
h1 { font-size: 1.3rem; margin: 0 0 .25rem; }
h1 a { text-decoration: none; color: inherit; }
.sub { opacity: .65; font-size: .85rem; margin-bottom: 1.5rem; }
nav { margin: 0 0 1.5rem; display: flex; gap: 1rem; flex-wrap: wrap; }
nav a { text-decoration: none; border-bottom: 2px solid transparent;
        padding-bottom: 2px; }
nav a:hover { border-color: currentColor; }
table { border-collapse: collapse; width: 100%; margin: 0 0 2rem; }
th, td { text-align: left; padding: .5rem .75rem .5rem 0;
         border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; font-size: .8rem; text-transform: uppercase;
     letter-spacing: .04em;
     opacity: .6; }
td.dim, .dim { opacity: .6; }
code { font: 13px ui-monospace, monospace; }
.warn { border: 1px solid var(--line); border-left-width: 4px; padding: .75rem 1rem;
        margin: 0 0 1.5rem; font-size: .9rem; }
.empty { opacity: .6; font-style: italic; }
.wrap { overflow-x: auto; }
"""


def _page(title: str, body: str, hub: dict[str, Any] | None = None) -> str:
    name = html.escape(str((hub or {}).get("name", "agent-mailbox")))
    version = html.escape(str((hub or {}).get("version", "")))
    unauthenticated = (hub or {}).get("authenticated") is False
    warning = (
        '<p class="warn"><strong>This hub does not authenticate.</strong> '
        "Anyone who can reach it can claim to be anyone. Suitable for a trusted "
        "network only.</p>"
        if unauthenticated
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — {name}</title><style>{STYLE}</style></head>
<body>
<h1><a href="/">{name}</a></h1>
<p class="sub">{html.escape(title)}{f" · v{version}" if version else ""}</p>
<nav><a href="/">Overview</a><a href="/agents">Agents</a>
<a href="/prompts">Prompt</a></nav>
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


def _advertised(hub: dict[str, Any], fallback: str) -> str:
    """The address the hub publishes for itself, for putting in front of a human.

    Prefer the hub's `id` over however this console reaches it: as a sidecar those
    differ, and only one of them is any use to an agent on the network.
    """
    return str(hub.get("id") or "").rstrip("/") or fallback


def _leaf(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def build_console(client: HubClient) -> Litestar:
    """A read-only window onto one hub."""

    @get("/", media_type=MediaType.HTML, sync_to_thread=True)
    def overview() -> Response:
        hub = client.hub_info()
        actors = client.list_agents().get("items", [])
        rows = [
            [
                f'<a href="/mailbox/{html.escape(a.get("preferredUsername", ""))}">'
                f"<code>{html.escape(a.get('preferredUsername', ''))}</code></a>",
                html.escape(str((a.get("profile") or {}).get("role", "") or "")),
                html.escape((a.get("summary") or "")[:90]),
            ]
            for a in actors
        ]
        body = _table(
            ["Who", "Role", "About"], rows, "Nobody has joined this mailbox yet."
        )
        body += (
            f'<p class="dim">Policies in force: '
            f"<code>{html.escape(', '.join(hub.get('policies', [])))}</code>. "
            f"Federation: {'on' if hub.get('federates') else 'off'}.</p>"
        )
        return Response(_page("Overview", body, hub), media_type=MediaType.HTML)

    @get("/agents", media_type=MediaType.HTML, sync_to_thread=True)
    def agents() -> Response:
        hub = client.hub_info()
        rows = []
        for a in client.list_agents().get("items", []):
            profile = a.get("profile") or {}
            facts = ", ".join(
                f"{html.escape(str(k))}: {html.escape(str(v))}"
                for k, v in profile.items()
                if k not in {"purpose", "standing"}
            )
            rows.append(
                [
                    f"<code>{html.escape(a.get('preferredUsername', ''))}</code>",
                    html.escape(str(a.get("type", ""))),
                    f'<span class="dim">{facts}</span>',
                ]
            )
        return Response(
            _page(
                "Agents", _table(["Who", "Type", "Profile"], rows, "Nobody yet."), hub
            ),
            media_type=MediaType.HTML,
        )

    @get("/mailbox/{name:str}", media_type=MediaType.HTML, sync_to_thread=True)
    def mailbox(name: str) -> Response:
        """What is waiting for one agent — **without consuming any of it**.

        The operator looks; the agent still has its mail — `check_inbox` peeks and
        never consumes, so watching cannot steal what it watches.

        **This currently works by asking as that agent**, which the hub permits only
        because nothing authenticates yet. That is a shortcut and it is recorded as
        one: the API was specified with `/observe/*` routes for exactly this and they
        were not built (M2 FR-010). When authentication arrives this stops working, and
        it should — an operator's authority belongs in authorisation on shared routes,
        not in the console being able to impersonate people (ADR 0005, ADR 0008).
        """
        hub = client.hub_info()
        peek = HubClient(
            type(client.config)(
                hub=client.config.hub, name=name, role=client.config.role
            )
        )
        try:
            waiting = peek.check_inbox().get("items", [])
        except Exception as exc:  # noqa: BLE001 - a page must render or explain
            body = (
                '<p class="warn">Could not read that mailbox: '
                f"{html.escape(str(exc))}</p>"
            )
            return Response(_page(name, body, hub), media_type=MediaType.HTML)

        rows = [
            [
                f"<code>{html.escape(_leaf(n.get('id')))}</code>",
                f"<code>{html.escape(_leaf(n.get('attributedTo')))}</code>",
                html.escape(n.get("summary") or "(no subject)"),
                (
                    '<span class="dim">'
                    + html.escape((n.get("content") or "")[:70])
                    + "</span>"
                ),
            ]
            for n in waiting
        ]
        body = (
            f"<p>Unread for <code>{html.escape(name)}</code>. "
            "Looking does not consume.</p>"
        )
        body += _table(["Id", "From", "Subject", "Body"], rows, "Nothing waiting.")
        return Response(
            _page(f"{name}'s mailbox", body, hub), media_type=MediaType.HTML
        )

    @get("/prompts", media_type=MediaType.HTML, sync_to_thread=True)
    def prompts() -> Response:
        """The one onboarding prompt, ready to paste.

        One page, because there used to be three and they drifted. Which role an agent
        holds is configuration, not a different prompt.

        The hub's own address is filled in, so the commands can be pasted as they
        stand — a placeholder is something to get wrong.

        The address comes from the hub's **`id`**, not from how this console happens
        to reach it. As a sidecar the console talks to `http://agent-mailbox:8080` over
        a container network, and pasting that to an agent would send it nowhere. `id`
        is the address the hub publishes as its identity, which is the one an agent can
        actually use.
        """
        hub = client.hub_info()
        text = onboarding(_advertised(hub, client.config.base))
        note = role_note().replace("**", "")
        body = (
            f"<p>{html.escape(note)}</p>"
            "<p>Paste the whole of this to an agent. Select it and copy — it is plain "
            "text, deliberately, so it survives being pasted anywhere.</p>"
            "<textarea readonly rows='28' style='width:100%;font:13px ui-monospace,"
            "monospace;padding:.75rem;border:1px solid var(--line);border-radius:4px;"
            "background:transparent;color:inherit'>"
            f"{html.escape(text)}</textarea>"
            "<p class='dim'>Written for "
            f"<code>{html.escape(_advertised(hub, client.config.base))}</code>. "
            "Also served as plain text at <a href='/prompts.txt'>/prompts.txt</a>.</p>"
        )
        return Response(_page("Prompt", body, hub), media_type=MediaType.HTML)

    @get("/prompts.txt", media_type=MediaType.TEXT, sync_to_thread=True)
    def prompt_text() -> str:
        """The same prompt as plain text, for `curl` and for pasting."""
        return onboarding(_advertised(client.hub_info(), client.config.base))

    return Litestar(route_handlers=[overview, agents, mailbox, prompts, prompt_text])
