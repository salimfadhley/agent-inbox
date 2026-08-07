"""The hub's one machine interface.

ActivityStreams on the wire, ActivityPub's route shape, served over a
:class:`~agent_inbox.house.House` so that house rules apply to everything reachable
from outside.

**This module adds no messaging logic.** Who receives a copy, which turns of a
thread you may see, what expires — all of that is decided below, by pure functions.
What happens here is translation: HTTP in, records out, records in, HTTP out. A
structural test enforces it, because this is exactly the layer where a convenience
shortcut would reintroduce a second door.

**Nothing here authenticates.** The caller's identity arrives in a header and is
taken at face value (ADR 0007). That is acceptable on a trusted single-operator
network, and the hub says so about itself rather than leaving it to be discovered.
Authorisation is a different matter and is already enforced underneath, so the
visibility rules hold however the caller was identified.
"""

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import msgspec
from litestar import Litestar, MediaType, Request, Response, delete, get, post, put
from litestar.connection import ASGIConnection
from litestar.datastructures import Cookie
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.handlers.base import BaseRouteHandler
from litestar.openapi import OpenAPIConfig
from litestar.response import ServerSentEvent, ServerSentEventMessage

from agent_inbox import __version__, addressing, fedaudit, rules, visibility
from agent_inbox.auth.exceptions import AuthError, NotAuthenticated, TooManyAttempts
from agent_inbox.auth.records import SHARED_ACTOR
from agent_inbox.auth.service import INSECURE_ADMIN_WARNING, AuthService
from agent_inbox.auth.throttle import LoginThrottle
from agent_inbox.delivery import hub_signing_key
from agent_inbox.errors import (
    auth_error_handler,
    mailbox_error_handler,
    store_busy_handler,
)
from agent_inbox.exceptions import (
    AddressError,
    HubSettingGoverned,
    InvalidHubName,
    MailboxError,
    MalformedAddress,
    NameUnavailable,
    NoSuchWebfingerResource,
    UnknownActor,
)
from agent_inbox.federation import (
    ENABLED,
    FEDERATION_MODES,
    PeerBlocked,
    check_may_enable_federation,
    federates,
    may_exchange,
)
from agent_inbox.house import House
from agent_inbox.hub_settings import HUB_SETTING_KEYS, resolve_hub_settings
from agent_inbox.inbound import InboundRefused, parse_activity, read_create
from agent_inbox.keys import SigningKey
from agent_inbox.naming import validate_hub_name
from agent_inbox.notify import TooManyListeners
from agent_inbox.peers import (
    ALLOWED_SCHEMES,
    fetch_actor_document,
    insecure_federation,
    peer_origin,
)
from agent_inbox.prompts import onboarding
from agent_inbox.signatures import parse_signature, verify_request
from agent_inbox.wire import (
    BLIND_FIELDS,
    Actor,
    Collection,
    Create,
    Note,
    Renderer,
    unknown_properties,
)

#: Who is calling. A header rather than a path segment, so authentication can
#: verify it instead of trusting it (ADR 0007).
IDENTITY_HEADER = "X-Agent-Name"

#: The human session cookie set by /auth/login and carried by the console.
SESSION_COOKIE = "agent_inbox_session"

#: What client the caller says it is running. Declared here rather than imported for the
#: same reason as the two constants above — the hub does not depend on the client
#: package — and pinned by a test so the two spellings cannot drift apart.
#:
#: **Observed, never claimed.** The hub reads it from a request it received, which is a
#: different kind of fact from a version an agent wrote into its profile at join. The
#: agents worth finding are those who joined long ago on a client they did not choose:
#: an install on an interpreter older than our floor silently resolves to an old
#: release instead of failing, and until this header nothing recorded which client an
#: agent used (`igor_laszlo`, 2026-08-05).
CLIENT_HEADER = "X-Agent-Inbox-Client"

#: What version this hub is running, on **every** response — the mirror of the header
#: above, and for the same reason in the other direction.
#:
#: Reported by `mariana_taphrale`, 2026-08-05: an MCP session learned the hub's version
#: once, from `ping`, and then repeated it in every tool result for the rest of its
#: life. The hub upgraded twice underneath one such session, which went on telling its
#: agent "this hub runs 0.58.0" while its own calls were being answered by 0.60.1 — a
#: cached fact presented as an observation, which is the failure this project keeps
#: meeting in other clothes.
#:
#: A header rather than a field in each payload: it costs nothing per route, cannot be
#: forgotten by a new one, and reaches responses that carry no body at all.
HUB_HEADER = "X-Agent-Inbox-Hub"

#: ActivityStreams asks for this; plain JSON clients are not refused for lacking it.
ACTIVITY_JSON = "application/activity+json"

api_logger = logging.getLogger("agent_inbox.api")


def caller_name(request: Request) -> str:
    """The caller's name, or a refusal that says what is missing."""
    value = request.headers.get(IDENTITY_HEADER, "").strip()
    if not value:
        raise HTTPException(
            status_code=400,
            detail=f"missing {IDENTITY_HEADER} header — send your name, for example "
            "'rosemary_nasrin'. This hub does not authenticate; it takes the header "
            "at its word.",
        )
    return value


def owns(name: str, caller: str, wire: Renderer) -> str:
    """Check that the caller is who the path says, or refuse.

    An earlier version accepted the path parameter and quietly ignored it, so
    ``GET /actors/alice/inbox`` with a header of ``bob`` returned *Bob's* inbox and a
    cheerful 200. That made the URL's owner meaningless, and would have laid a trap for
    authentication: an edge or middleware checking the path would have been checking
    nothing at all.
    """
    wanted = wire.name_from(name)
    if wanted != caller:
        raise HTTPException(
            status_code=403,
            detail=(
                f"this is {wanted}'s mailbox and you are {caller} — "
                f"use /actors/{caller}/… for your own"
            ),
        )
    return caller


#: How many messages one compact response may describe. Not a limit on what you may
#: read — the cursor carries you to the rest — but a ceiling on what a single glance
#: costs, so that ignoring your mail for a week cannot produce one unpayable reply.
PAGE = 50

#: How long an idle event stream waits before sending a comment frame. Proxies and load
#: balancers close connections that go quiet, and the interval has to be comfortably
#: under the shortest of those — Fly's idle timeout being the one that matters here.
#: Short enough to hold the connection, long enough that a hub full of idle listeners is
#: not a hub doing constant work.
STREAM_KEEPALIVE_SECONDS = 15.0

#: How much recent activity `/observe/recent` returns when the caller does not say, and
#: the most it will return however loudly they ask.
#:
#: The maximum is the point. "Recent" with no ceiling is a whole-store dump wearing a
#: small name, and the route is open to any signed-in operator, so the limit belongs to
#: the hub rather than to whoever remembers to pass one. The default is a screenful:
#: this exists so a live view opens full instead of blank, not so it can be read as an
#: archive.
DEFAULT_RECENT = 50
MAX_RECENT = 200


def _cursor_key(record: Any) -> tuple[str, str]:
    """A message's place in the order a cursor walks: when it was sent, then its id."""
    return (record.published or "", str(record.id))


def _cursor_text(key: tuple[str, ...]) -> str:
    return "|".join(key) if key else ""


def unmangled_timestamp(value: str) -> str:
    """Undo the one thing a URL does to a timestamp we handed out.

    Our timestamps carry a UTC offset — ``2026-07-28T08:16:42.589603+00:00`` — and in a
    query string ``+`` means a space. A caller that pastes a value we gave it straight
    into a URL therefore sends something subtly different from what it received, and we
    used to compare against the difference without noticing.

    It failed silently and in the worse direction: a space (0x20) sorts *below* ``+``
    (0x2B), so the mangled value is smaller than every real one, and the inbox filter —
    a strict ``>`` on a tuple — stopped excluding the very message the caller had just
    been shown. Mail it had already accounted for came back, and nothing said why.

    Applied to every timestamp a caller can hand back, not only the one that broke. See
    :meth:`Api.survey` for the other, which measurement showed is *not* affected today
    and is one operator away from being so.

    The mapping is unambiguous, which is what makes fixing it here safe rather than a
    guess: an ISO 8601 timestamp never contains a space, so a space in one can only ever
    have been a ``+``. **Timestamps only** — never an id, which is hex and could in
    principle carry a space meaningfully in some future format.

    `agent_inbox.client` escapes correctly and always did, so this repairs nothing
    that was broken for it. It is for the clients ADR 0005 and the published OpenAPI
    schema invite, which will reasonably treat an opaque string as opaque.
    """
    return value.replace(" ", "+")


def _cursor_parts(cursor: str) -> tuple[str, str]:
    """A cursor back into its parts, tolerating one written by an older client.

    A bare timestamp (no ``|``) is read as "that instant, before any id", which includes
    anything sent in that same instant rather than swallowing it. Erring towards showing
    a message twice is recoverable; erring towards never showing it is not.
    """
    published, _, ident = cursor.partition("|")
    return (unmangled_timestamp(published), ident)


#: What a client needs to know that the route signatures cannot tell them.
#:
#: The generated schema describes shapes; this describes the *profile* — the handful of
#: behaviours that are decisions rather than types, and that a client author would
#: otherwise have to discover by experiment.
API_DESCRIPTION = """\
ActivityStreams 2.0 over ActivityPub's route shape. One hub, no federation.

**What is accepted.** A `Create` wrapping a `Note`, or a bare `Note` — posting what you
mean is enough, and the wrapper is added for you. Recipients go in `to` and `cc`, by
name (`rosemary_nasrin`) or as an actor URI; a group name expands to its members and
`everyone` to the whole hub.

**What is emitted.** `@context`, `type`, `attributedTo`, `to`, `cc`, `summary`,
`content`, `inReplyTo`, `published`. Actors and objects are absolute URIs built from the
hub's configured public URL; the internal ids are never exposed.

**What is ignored — and kept.** An AS2 property this API does not model survives a round
trip unchanged rather than being dropped, so a richer client is not punished for being
richer.

**What is refused.** Blind addressing (`bto`, `bcc`) — 422, because a mailbox that
delivers copies nobody can see is one nobody can reason about. Send separate messages,
or address everyone in `to`.

**Reading never happens by accident.** `GET /actors/{name}/inbox` consumes nothing,
however often you call it; `POST /objects/{id}/read` is the only call that marks mail
handled, and it does so for the caller alone — everyone else addressed keeps their copy.
By default the inbox returns a manifest without message bodies; `?view=full` returns
them.

**You can be told instead of asking.** `GET /actors/{name}/events` is a Server-Sent
Events stream, authenticated as that actor and carrying only that actor's events. Each
one says *that* mail arrived — `id`, `from`, `subject`, `published` — and **never the
body**: it is a notification, not a delivery, so `POST /objects/{id}/read` remains the
only call that consumes anything. Idle streams carry a comment frame every fifteen
seconds so a proxy does not close them.

Holding one is optional in every respect. Polling `GET /actors/{name}/inbox` is the
floor and always will be: a client that cannot hold a connection — one invoked per
command, one behind a proxy that forbids it — loses immediacy and nothing else, and mail
waits either way. A dropped stream loses nothing, so reconnecting is your business and a
client that never reconnects is exactly a polling client. Streams are capped per hub; at
the cap the request is refused with 503 and the connections already open are unaffected.

**The cursor is yours to keep, and opaque.** Every inbox reply carries one — including
when nothing is waiting, so you can store it unconditionally. Hand it back as `?since=`
to see only what has arrived since. It is a filter you own, never server state: the hub
remembers nothing, so losing one costs a longer list and nothing else, and two sessions
sharing a name cannot hide mail from each other.

Treat it as opaque. It currently looks like `<published>|<id>`, and that shape is an
implementation detail — do not parse it, build one, or compare its parts. Comparing two
whole cursors is fine.

One practical note, because it bit us: a cursor contains `+`, and `+` in a query string
means a space. **Percent-encode it** (`%2B`) like any query value. A hub since v0.23
repairs the mangled form rather than silently filtering against a value you did not
send — but encode it anyway, because a hub that has not been upgraded will not, and the
symptom is mail you have already handled arriving a second time with nothing to explain
why.

**Absent and forbidden are the same answer.** A message that does not exist and one that
exists but is not yours both return 404. Distinguishing them would answer the question
the visibility rules exist to refuse.

**Who you are arrives in a header.** `X-Agent-Name`. Under an authenticating hub it is
verified against a token (`Authorization: Bearer`); a hub says which it is doing
in `GET /`, and `authenticated: false` means the header is taken at face value.
"""


def _settings_version(resolved: Mapping[str, Any]) -> str:
    """A token for the state a client read, so a stale write can be spotted.

    Covers value **and source**, because the risk here is not two operators racing —
    it is one operator submitting a page rendered while the environment governed a
    field. The value alone would not change when a variable is removed; the source does.
    """
    material = "|".join(
        f"{key}={resolved[key].value!r}:{resolved[key].source}"
        for key in sorted(resolved)
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


class Api:
    """Routes over a house. Holds the house and the renderer; decides nothing."""

    def __init__(
        self,
        house: House,
        public_url: str,
        *,
        authenticated: bool = False,
        admin_password_set: bool = False,
    ) -> None:
        self.house = house
        self.wire = Renderer(public_url)
        #: Filled in by build_api; the scheduler writes to it, the preview reads it.
        self.purge_status = PurgeStatus()
        #: True only under enforce — the hub reports its own posture honestly.
        self.authenticated = authenticated
        #: True when the low-security admin override is active. Advertised for the same
        #: reason `authenticated` is: a hub's posture should never be a surprise, and a
        #: hole in the front door that cannot be seen from outside is the worst kind.
        self.admin_password_set = admin_password_set

    # -- hub ---------------------------------------------------------------

    async def hub(self) -> dict[str, Any]:
        mailbox = self.house.mailbox
        note = (
            "This hub requires authentication: agents present a token as a "
            "Bearer credential, humans log in at the console."
            if self.authenticated
            else (
                "This hub does not authenticate. The caller's name is taken from the "
                f"{IDENTITY_HEADER} header at face value. Suitable for a trusted "
                "network only."
            )
        )
        resolved = resolve_hub_settings(
            await mailbox.hub_settings(), default_name=mailbox.hub_name
        )
        # Omitted, not empty. An unset title is absent from the document; `""` is a
        # value an operator chose, and the two must stay distinguishable because the
        # console renders them the same and the API must not.
        presentation = {
            key: resolved[key].value
            for key in ("title", "description")
            if resolved[key].value is not None
        }
        return {
            "@context": "https://www.w3.org/ns/activitystreams",
            "type": "Service",
            # Resolved, not read from the mailbox: the environment may govern it, and
            # there is one place that answers "what is this hub called".
            "name": resolved["name"].value,
            **presentation,
            "version": __version__,
            # An ADDRESS, and not the identity. A hub answers to many; changing this
            # does not change `name` (NFR-003).
            "id": self.wire.base,
            # Said out loud, either way — a hub's posture should never be a surprise.
            "authenticated": self.authenticated,
            "note": note,
            # Advertised so the console can warn and a caller can tell. A hub running
            # with the admin override is not as authenticated as `authenticated: true`
            # would otherwise suggest, and hiding that would make the flag above a lie
            # by omission.
            "adminPasswordSet": self.admin_password_set,
            **(
                {"adminPasswordWarning": INSECURE_ADMIN_WARNING}
                if self.admin_password_set
                else {}
            ),
            "policies": [getattr(p, "name", "?") for p in self.house.policies],
            "federates": federates(await mailbox.hub_settings()),
        }

    async def federation_descriptor(self) -> dict[str, Any]:
        """What another hub needs to know before talking to this one. Unauthenticated.

        **Deliberately not NodeInfo, and deliberately not `GET /`.**

        NodeInfo is the fediverse's server-descriptor convention and this hub already
        serves it — but its schema *requires* `usage.users`, and FR-010 forbids counts
        here. A descriptor that must carry a number it is not allowed to carry is the
        wrong document, so this is a second one rather than a bent one.

        `GET /` is the *local* descriptor: it names the hub, lists its policies, and
        says whether an admin password override is set. Every one of those is an
        operator's business and none of it is a peer's.

        **No hub `name`, and that is the part easiest to get wrong** because it feels
        like identity. Decision `01KYMQ4GNS4B1PRD6WJ6W75DRG`: federated identity is the
        **domain**. The name is local and friendly, and keeping it off every federated
        surface is exactly what keeps renaming free — a hub that renamed itself and
        thereby became a different peer would have a name it could never change.

        Honest about the mode, including when the answer is `disabled`. A compatibility
        check that cannot be trusted is worse than one reporting a state the caller does
        not like.
        """
        mailbox = self.house.mailbox
        stored = await mailbox.hub_settings()
        resolved = resolve_hub_settings(stored, default_name=mailbox.hub_name)
        # Presentation only, and omitted rather than empty — an unset title is absent,
        # `""` is a value somebody chose, and the two stay distinguishable.
        presentation = {
            key: resolved[key].value
            for key in ("title", "description")
            if resolved[key].value is not None
        }
        return {
            "software": {"name": "agent-inbox", "version": __version__},
            # The address, which *is* the federated identity.
            "id": self.wire.base,
            **presentation,
            "federation": resolved["federation"].value,
            "protocols": ["activitypub"],
            "capabilities": {
                # What a peer can actually rely on today. Said plainly rather than
                # implied by our silence, so a peer never has to probe to find out.
                "inbox": True,
                "webfinger": True,
                "signedDelivery": True,
                # Nothing is bridged, and no relay is supported. Empty is the honest
                # answer, not a gap somebody should fill in later.
                "relay": False,
            },
            "schemes": list(ALLOWED_SCHEMES),
            # Said out loud for the same reason `authenticated` is on `GET /`: a
            # peer deciding whether to trust us is entitled to know we would accept
            # unencrypted federation, and a posture invisible from outside is the
            # worst kind.
            **({"insecureTransport": True} if insecure_federation() else {}),
            "publicKey": {
                # Where to fetch the key, not the key itself. A peer that needs it to
                # verify a signature is already fetching the actor document that carries
                # it, and publishing a second copy here creates two things to rotate.
                "keyId": f"{self.wire.base}#main-key",
                "owner": self.wire.base,
            },
        }

    async def hub_settings(self) -> dict[str, Any]:
        """Each setting with its value, its source, and what governs it.

        Operator-gated, as the contract settles: `GET /` is public and says what the hub
        *is*, while this says how the deployment is *configured*, which is
        administrative and sits in `revoke_token`'s neighbourhood.

        An unset `title` is `null` with source `default` here, and omitted entirely from
        `GET /`. A client rendering the field needs to know it exists and is unset; a
        reader of the descriptor does not.
        """
        mailbox = self.house.mailbox
        resolved = resolve_hub_settings(
            await mailbox.hub_settings(), default_name=mailbox.hub_name
        )
        return {
            **{
                key: {
                    "value": setting.value,
                    "source": setting.source,
                    **({"variable": setting.variable} if setting.variable else {}),
                }
                for key, setting in resolved.items()
            },
            "version": _settings_version(resolved),
        }

    async def set_hub_settings(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        """Change what the operator controls, and refuse what they do not.

        Two refusals, and the second is the one an outside review found.

        A field the environment governs is refused with `409` rather than stored: the
        next read would override it, so accepting would be a write that reports success
        and changes nothing.

        **A value that came from the environment is never written back** (FR-011). A
        client that rendered a governed field and submits it later — after the variable
        has gone, or from a page rendered before it did — would persist the deployment's
        value over the operator's own. Startup was guarded against that; this path was
        not, and it is the path an operator actually uses.
        """
        mailbox = self.house.mailbox
        stored = await mailbox.hub_settings()
        resolved = resolve_hub_settings(stored, default_name=mailbox.hub_name)

        # FR-011. The client states which state it read; if that is no longer the
        # state, what it is submitting was rendered under different rules and must not
        # be stored. This is the stale-page erasure an outside review found: a field
        # rendered while the environment governed it, submitted after the variable was
        # removed, would otherwise persist the deployment's value over the operator's.
        #
        # It protects a client that participates. A client that sends no version gets
        # no protection, which is why the console is required to send one (WP04 T022)
        # and why it also declines to submit governed fields at all.
        seen = changes.get("version")
        if seen is not None and seen != _settings_version(resolved):
            raise HubSettingGoverned(
                "these settings changed since you read them — reload before writing. "
                "A value rendered under different configuration must not be stored, "
                "because it may be the deployment's value rather than yours"
            )
        changes = {k: v for k, v in changes.items() if k != "version"}

        unknown = set(changes) - set(HUB_SETTING_KEYS)
        if unknown:
            raise MalformedAddress(
                f"not hub settings: {', '.join(sorted(unknown))}; "
                f"settable: {', '.join(HUB_SETTING_KEYS)}"
            )

        for key, value in changes.items():
            current = resolved[key]
            if current.source == "environment":
                raise HubSettingGoverned(
                    f"{key!r} is set by this deployment through {current.variable} and "
                    "cannot be changed here — change the variable, or unset it to use "
                    "the stored value"
                )
            if value is None:
                continue
            if not isinstance(value, str):
                raise MalformedAddress(
                    f"{key!r} must be text, not {type(value).__name__}"
                )
            if key == "name":
                try:
                    validate_hub_name(value)
                except NameUnavailable as refusal:
                    raise InvalidHubName(str(refusal)) from refusal
            if key == "federation":
                if value not in FEDERATION_MODES:
                    raise MalformedAddress(
                        f"federation must be one of {', '.join(FEDERATION_MODES)}, "
                        f"not {value!r}"
                    )
                if value == ENABLED:
                    # Gated on the name the hub will *have*, so enabling and
                    # renaming in one request is judged on the outcome, not the
                    # starting point.
                    intended = changes.get("name") or resolved["name"].value or ""
                    check_may_enable_federation(str(intended))

        for key, value in changes.items():
            await mailbox.set_hub_setting(key, value)

        # Report what actually took effect, not what was asked for. They differ whenever
        # the environment governs, and showing the submission would tell an operator a
        # change landed when it did not.
        return await self.hub_settings()

    async def nodeinfo_index(self) -> dict[str, Any]:
        """The discovery document every fediverse server serves.

        Two hops by design: this names where the real document lives, so a server can
        add versions without breaking clients pinned to an older one.
        """
        if not federates(await self.house.mailbox.hub_settings()):
            # Silent, not an empty link list: a hub that does not federate has no
            # NodeInfo service, and advertising a document that then refuses would say
            # "something is here" to exactly the caller who should learn nothing.
            raise NoSuchWebfingerResource("this hub does not federate")
        return {
            "links": [
                {
                    "rel": "http://nodeinfo.diaspora.software/ns/schema/2.1",
                    "href": f"{self.wire.base}/nodeinfo/2.1",
                }
            ]
        }

    async def nodeinfo(self) -> dict[str, Any]:
        """What this hub is, in the schema the fediverse already agreed on.

        All seven top-level fields are required by the schema, so none is omitted even
        where the honest answer is empty. Our own fields live in ``metadata``, which is
        explicitly free-form — inventing a parallel document would be the thing C-001
        forbids.

        **Served only when federation is enabled.** An earlier version served it always,
        on the grounds that requiring federation first would deadlock two fresh hubs
        trying to check each other. That argument was wrong: enabling federation is a
        purely local act needing no peer, so each operator enables first and then adds
        the other. Nothing deadlocks.

        Meanwhile serving it unconditionally disclosed `usage.users.total` — the size
        of a private hub's roster — plus its title and description, to anyone who asked
        a hub that had never chosen to federate. Found by outside review, 2026-07-29.
        """
        mailbox = self.house.mailbox
        stored = await mailbox.hub_settings()
        if not federates(stored):
            raise NoSuchWebfingerResource("this hub does not federate")
        resolved = resolve_hub_settings(stored, default_name=mailbox.hub_name)
        actors = await self.house.directory()
        metadata: dict[str, Any] = {
            "federation": resolved["federation"].value,
            # Said out loud, for the same reason `authenticated` is: a peer deciding
            # whether to trust us is entitled to know we accept unencrypted federation,
            # and a posture that cannot be seen from outside is the worst kind.
            **({"insecureTransport": True} if insecure_federation() else {}),
            # Not the hub's `name`: that never crosses the wire, which is
            # what makes renaming free. Presentation only.
            **{
                key: resolved[key].value
                for key in ("title", "description")
                if resolved[key].value is not None
            },
        }
        return {
            "version": "2.1",
            "software": {"name": "agent-inbox", "version": __version__},
            "protocols": ["activitypub"],
            # Nothing is bridged in or out. Empty is the honest answer, not a gap.
            "services": {"inbound": [], "outbound": []},
            # Whether an agent may join unasked — what auth mode decides.
            "openRegistrations": not self.authenticated,
            # **A public number counts only actors willing to be public.** Counting a
            # `local` actor here would leak that somebody is there without naming them,
            # which is a smaller disclosure than a name and is still one.
            "usage": {
                "users": {
                    "total": sum(
                        1
                        for a in actors
                        if visibility.read(a.profile) is not visibility.Visibility.LOCAL
                    )
                }
            },
            "metadata": metadata,
        }

    async def webfinger(self, resource: str) -> dict[str, Any]:
        """Resolve ``acct:alice@hub.example`` to this hub's actor document.

        **Answers only when federation is enabled.** Actor visibility — letting an
        individual actor opt out — is a later step, so until it exists the hub-level
        switch is the whole control: a hub that has not chosen to federate resolves
        nobody. A default hub is therefore silent here, which is every hub today.

        Refuses with 404 rather than 403 when federation is off. A hub that does not
        federate has no WebFinger service at all; saying "forbidden" would confirm that
        the named actor exists, which is the disclosure the gate exists to prevent.
        """
        mailbox = self.house.mailbox
        stored = await mailbox.hub_settings()
        if not federates(stored):
            raise NoSuchWebfingerResource(
                "this hub does not federate, so it resolves no accounts"
            )

        wanted = resource.strip()
        if not wanted.startswith("acct:") or "@" not in wanted:
            raise NoSuchWebfingerResource(
                f"{resource!r} is not an account — expected acct:name@host"
            )
        name, _, host = wanted[len("acct:") :].partition("@")
        if host.lower() not in self._webfinger_hosts():
            raise NoSuchWebfingerResource(f"{host!r} is not this hub")

        record = await mailbox.whois(name)
        # **One refusal, one wording.** A `local` actor and a name nobody holds produce
        # the identical error — deliberately, and asserted by a test that compares the
        # two responses. A differently-worded refusal is an oracle: ask for a thousand
        # names and the one that is "hidden" rather than "unknown" has told you it
        # exists, which is the whole thing visibility is for (T013, NFR-004).
        if (
            record is None
            or visibility.read(record.profile) is visibility.Visibility.LOCAL
        ):
            raise NoSuchWebfingerResource(f"no account {name!r} here")

        return {
            "subject": f"acct:{name}@{host}",
            "links": [
                {
                    "rel": "self",
                    "type": "application/activity+json",
                    "href": f"{self.wire.base}/actors/{name}",
                }
            ],
        }

    def _webfinger_hosts(self) -> set[str]:
        """What this hub answers to in an address.

        The host from the public URL, with and without its port. A hub reached as
        `hub.example:8081` should resolve `alice@hub.example` too — the port is part of
        the address and not of the identity, which is this project's whole argument
        about hub names one level down.
        """
        netloc = urlsplit(self.wire.base).netloc.lower()
        return {netloc, netloc.partition(":")[0]}

    async def signing_key(self) -> SigningKey:
        """This hub's key, minted on first need and kept thereafter.

        Generated lazily rather than at startup: a hub that never federates never needs
        one, and generating a 2048-bit key on every boot of every test would be a cost
        with no purpose.
        """
        # One implementation, in `delivery`, because the sending path needs the same
        # key and two lazily-minting copies could race each other into two keys.
        return await hub_signing_key(self.house.mailbox)

    # -- the trust list ----------------------------------------------------
    #
    # Peering gates federation in **both** directions: `outbound.deliver` refuses an
    # origin that is not listed, and an inbound signature from an unlisted origin is a
    # stranger's. A hub with no peers can neither send nor receive, which is why these
    # exist — until they did, federation worked in the tests and could not be switched
    # on by anyone who could not open the database by hand.
    #
    # Operator-only, per ADR 0008: deciding who this hub trusts is administration, and
    # administration is not reachable by sending a message. An agent that could add a
    # peer could be talked into adding one.

    async def list_peers(self) -> dict[str, Any]:
        """Who this hub trusts, and when each was added."""
        peers = await self.house.mailbox.peers()
        return {
            "peers": [
                {"origin": origin, "added": added}
                for origin, added in sorted(peers.items())
            ]
        }

    async def add_peer(self, data: dict[str, Any]) -> dict[str, Any]:
        """Trust a hub, by origin.

        The origin is normalised through the **same** `peer_origin` the trust check and
        the fetch guards use. Two nearly-agreeing notions of "same hub" is how a trust
        list acquires a bypass, so there is deliberately only one.

        Adding a peer does not contact it. Peering is a local statement about who *we*
        trust, and a hub that is asleep should still be addable.
        """
        raw = str(data.get("origin", "")).strip()
        if not raw:
            raise HTTPException(status_code=422, detail="give an origin to trust")
        try:
            origin = peer_origin(raw)
        except MailboxError as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused
        # **Before anything else touches this origin.** FR-007 orders the flow:
        # normalise, check the blocklist, only then go near the network. The order is
        # the requirement rather than an optimisation — blocking a hub while still
        # sending it a request tells it we tried, which is worse than not blocking it.
        verdict = await may_exchange(self.house.mailbox.store, origin)
        if not verdict:
            # Recorded even though nobody typed it. An operator asking "why did that
            # peer not get my mail" is asking about exactly this, and an audit of only
            # deliberate acts cannot answer them.
            fedaudit.record("peer.add.refused", origin, reason=verdict.reason)
            raise PeerBlocked(verdict.reason)
        note = str(data.get("note", "")).strip()
        added = datetime.now(UTC).date().isoformat()
        await self.house.mailbox.add_peer(origin, added, note)
        return {"origin": origin, "trusted": True}

    async def blocks(self) -> dict[str, Any]:
        """Origins this hub refuses, and why."""
        blocked = await self.house.mailbox.store.blocks()
        return {
            "items": [
                {"origin": origin, "note": note}
                for origin, note in sorted(blocked.items())
            ]
        }

    async def add_block(self, data: dict[str, Any]) -> dict[str, Any]:
        """Refuse an origin, whatever the mode says.

        Normalised through the **same** `peer_origin` the decision uses, so a block
        entered with a trailing slash or an explicit `:443` matches the traffic it was
        meant to stop. Two nearly-agreeing notions of "same hub" is how a blocklist
        acquires a bypass.

        Blocking does not remove an existing peering, and deliberately so: the block
        wins while it stands, and un-blocking should not silently restore trust the
        operator may since have changed their mind about. Both facts stay visible.
        """
        raw = str(data.get("origin", "")).strip()
        if not raw:
            raise HTTPException(status_code=422, detail="give an origin to block")
        try:
            origin = peer_origin(raw)
        except MailboxError as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused
        note = str(data.get("note", "")).strip()
        added = datetime.now(UTC).date().isoformat()
        await self.house.mailbox.store.add_block(origin, added, note)
        fedaudit.record("block.add", origin, reason=note or "no reason given")
        return {"origin": origin, "blocked": True}

    async def remove_block(self, origin: str) -> dict[str, Any]:
        """Stop refusing an origin. **It is not thereby trusted** — that is a separate
        statement, and one an operator has to make on purpose."""
        try:
            normalised = peer_origin(origin)
        except MailboxError as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused
        await self.house.mailbox.store.remove_block(normalised)
        fedaudit.record("block.remove", normalised)
        return {"origin": normalised, "blocked": False, "trusted": False}

    async def remove_peer(self, origin: str) -> dict[str, Any]:
        """Stop trusting a hub.

        Takes effect immediately and in both directions, because authorization is
        re-derived at send time rather than carried from anywhere (FR-050). Mail already
        received is **ours** and is not withdrawn — our retention, our rules.
        """
        await self.house.mailbox.remove_peer(peer_origin(origin))
        return {"origin": origin, "trusted": False}

    async def verified_peer(
        self, request: Request, *, body: bytes | None = None
    ) -> str | None:
        """The peer that signed this request, or None.

        None means *not verified*, and every caller must treat it as "stranger" rather
        than as an error to route around.

        **Two conditions, and the second was missing.** A valid signature proves only
        that the sender holds the key at the ``keyId`` they chose — and anyone can
        publish an actor document with their own key, sign correctly, and be
        "verified". That is possession, not identity. So the signer's origin must also
        be a hub this one has been *told* to trust.

        Found by outside review, 2026-07-29: without the second condition any stranger
        could obtain the rich actor document by signing as themselves.

        A hub with no peers therefore verifies nobody, which is every hub until an
        operator adds one — and is the right default.
        """
        claim = parse_signature(request.headers.get("signature", ""))
        if claim is None:
            return None

        try:
            signer = peer_origin(claim.key_id)
        except MailboxError:
            return None
        if signer not in await self.house.mailbox.peers():
            return None

        try:
            # The key lives on the actor document the keyId points at. Fetching it is
            # bounded and origin-checked by the same guards a peer check uses, so a
            # signature cannot make us fetch an arbitrary URL.
            document = await asyncio.to_thread(fetch_actor_document, claim.key_id)
        except MailboxError:
            return None
        public = document.get("publicKeyPem")
        owner = document.get("owner")
        if not isinstance(public, str) or not isinstance(owner, str):
            return None
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"
        headers = {k.lower(): v for k, v in request.headers.items()}
        if not verify_request(claim, public, request.method, path, headers, body=body):
            return None
        # The document's own `owner` must live at the origin we trusted, or a trusted
        # peer's document could name someone else as the signer.
        try:
            if peer_origin(owner) != signer:
                return None
        except MailboxError:
            return None
        return owner

    async def _resolvable_or_absent(self, name: str) -> None:
        """Refuse a `local` actor exactly as an unknown name is refused.

        Shared by every outward-facing path so the wording cannot drift between them —
        two refusals that differ by a word are the oracle this exists to close.
        """
        record = await self.house.whois(self.wire.name_from(name))
        if record is None or visibility.read(record.profile) is (
            visibility.Visibility.LOCAL
        ):
            raise HTTPException(status_code=404, detail=f"no actor named {name!r}")

    async def thin_actor(self, name: str) -> dict[str, Any]:
        """The barebones actor document a stranger gets.

        Exactly what addressing requires — an id, a type, the username, and an inbox to
        deliver to — and nothing else. No profile, no project, no last-seen, no role.

        This is Mastodon's shipped behaviour under `AUTHORIZED_FETCH`, verified from its
        documentation: *"Profiles will only return barebones technical information when
        no authentication is supplied."* The alternative — the fediverse default that
        actor documents are world-readable in full — is right for public social software
        and wrong for private mail, because it would publish a hub's whole roster.

        Only reachable when federation is enabled; see the route.
        """
        record = await self.house.mailbox.whois(name)
        if record is None:
            raise UnknownActor(f"no actor {name!r} here")
        actor_id = f"{self.wire.base}/actors/{record.name}"
        key = await self.signing_key()
        return {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": actor_id,
            "type": "Person",
            "preferredUsername": record.name,
            "inbox": f"{actor_id}/inbox",
            # What a peer needs to verify anything we send it. The hub holds one key
            # and every actor advertises it: agents are not separate principals across
            # a hub boundary, the hub speaks for them.
            "publicKey": {
                "id": f"{actor_id}#main-key",
                "owner": actor_id,
                "publicKeyPem": key.public_pem,
            },
        }

    async def health(self) -> dict[str, str]:
        """Liveness only — deliberately does not touch the store.

        A wedged database should be reported by the routes that need it, not hidden
        behind a health check that also hangs.
        """
        return {"status": "ok"}

    # -- actors ------------------------------------------------------------

    async def join(self, data: dict[str, Any]) -> Actor:
        requested = data.get("preferredUsername") or data.get("name")
        actor = await self.house.join(requested)
        return self.wire.actor(actor)

    async def directory(self, *, listed_only: bool = False) -> Collection:
        """Who is here.

        ``listed_only`` is the **federated** view: `discoverable` actors and nothing
        else. That is the middle level doing its job — `normal` is addressable but
        unlisted, so somebody who knows the name can reach it while the directory does
        not advertise it.

        **A verified local caller still sees everyone**, and that is a deliberate
        reading of T010 rather than an oversight. Visibility governs exposure *outward*:
        an agent must be able to find the other agents on its own machine or the product
        does not work, and `list_agents` is how the console, the CLI and every agent do
        that. If this reading is wrong the fix is one argument at the call site, and the
        tests say plainly which behaviour they pin.
        """
        actors = await self.house.directory()
        if listed_only:
            actors = tuple(
                a
                for a in actors
                if visibility.read(a.profile) is visibility.Visibility.DISCOVERABLE
            )
        return self.wire.collection([self.wire.actor(a) for a in actors])

    async def actor(self, name: str) -> Actor:
        record = await self.house.whois(self.wire.name_from(name))
        if record is None:
            raise HTTPException(status_code=404, detail=f"no actor named {name!r}")
        return self.wire.actor(record)

    async def update_profile(
        self, name: str, data: dict[str, Any], caller: str
    ) -> Actor:
        owns(name, caller, self.wire)
        profile = data.get("profile", data)
        record = await self.house.update_profile(caller, dict(profile))
        return self.wire.actor(record)

    # -- mail --------------------------------------------------------------

    async def outbox(self, name: str, request: Request, caller: str) -> Note:
        owns(name, caller, self.wire)
        raw: dict[str, Any] = await request.json()
        _refuse_blind_addressing(raw)
        activity = decode_activity(raw)
        note = activity.object

        parent = (
            self.wire.object_id_from(note.in_reply_to) if note.in_reply_to else None
        )
        if parent and not note.to and not note.cc:
            # A note with a parent and no recipients *is* a reply. Sending it as-is
            # would return 201 and reach nobody — a silent success, which is the worst
            # failure shape we have. House.reply addresses the original sender and
            # adds the `Re:` subject.
            replied = await self.house.reply(
                caller, parent, note.content, subject=note.summary
            )
            return self.wire.note(replied.record)

        sent = await self.house.send(
            caller,
            self.wire.recipients(note.to),
            note.content,
            subject=note.summary,
            cc=self.wire.recipients(note.cc),
            in_reply_to=parent,
            # Whatever this document carried that we do not model, kept verbatim.
            document=unknown_properties(raw) or None,
        )
        if sent.reached_nobody:
            # Never 201. `api.py` already refuses to report a reply addressed to nobody
            # as a success; a send whose only recipients were remote and unreachable is
            # the same failure arriving by a different route.
            raise HTTPException(
                status_code=502,
                detail="; ".join(
                    f"{r.recipient}: {r.detail or 'failed'}" for r in sent.receipts
                ),
            )
        rendered = self.wire.note(sent.record)
        if sent.receipts:
            # Per recipient, and a *word* rather than a boolean — Step 7's queue adds
            # `queued` here, and a client that reads three states keeps working.
            rendered.extra = {
                **(rendered.extra or {}),
                "delivery": [
                    {
                        "recipient": r.recipient,
                        "state": r.state,
                        **({"detail": r.detail} if r.detail else {}),
                    }
                    for r in sent.receipts
                ],
            }
        return rendered

    async def inbox(
        self,
        name: str,
        caller: str,
        view: str = "summary",
        since: str | None = None,
    ) -> Collection | dict[str, Any]:
        """What is waiting, in one of three weights. Consumes nothing, always.

        The default used to be every waiting message in full, which meant the cheapest
        thing an agent can do — glance at its inbox — was also the most expensive call
        in the API. An agent then paid for bodies it had not chosen to open, on every
        poll, including ones it had already seen and left. `summary` is the honest
        default: enough to decide from, which is exactly what the tool documentation
        already told recipients they should be doing.

        `since` is a filter, never a bookmark. The caller keeps the cursor and passes
        it back, so this call still mutates nothing — a server-side "last seen" marker
        would break the moment two sessions share an identity, and the mail that
        vanished would be indistinguishable from mail that never arrived.
        """
        owns(name, caller, self.wire)
        # Repaired once, here, rather than at each use. The filter below and the cursor
        # carried forward at the end must agree: repairing only the filter would still
        # hand a spoiled cursor back, the caller would store *that*, and the damage
        # would persist across every later poll instead of one.
        since = unmangled_timestamp(since) if since else since
        waiting = await self.house.peek(caller)
        if since:
            after = _cursor_parts(since)
            waiting = tuple(m for m in waiting if _cursor_key(m) > after)

        total = len(waiting)
        if view != "count":
            # Bounded, oldest first, and the cursor makes the bound safe: what is cut
            # off is not lost, it is *next*. An unbounded manifest would put a mailbox
            # that has been ignored for a week into one response, which is the same
            # unpayable bill in a smaller font.
            waiting = tuple(sorted(waiting, key=_cursor_key))[:PAGE]

        # The newest thing this caller has been shown, as `<published>|<id>`.
        #
        # The id is not decoration. On a timestamp alone, two messages sent in the same
        # instant collapse: the cursor takes that instant, and the second one can never
        # be greater than it, so it is hidden **for ever** — mail that vanished, which
        # is the failure this whole design exists to avoid. The pair is unique, so it
        # both never hides and never repeats. Still readable, still safe to persist.
        cursor = _cursor_text(max((_cursor_key(m) for m in waiting), default=()))
        if not cursor:
            # Nothing shown, so there is no message to anchor to. Carry the caller's own
            # cursor forward when they had one; otherwise mark this instant.
            #
            # The empty string used to be returned here, on the first poll of a quiet
            # mailbox — which is exactly the poll where a caller starts persisting the
            # value. Stored and handed back, `""` is falsy and reads as "no filter", so
            # the next poll returns everything and the caller re-reads mail it had
            # already accounted for. A bookmark that means "everything" is worse than no
            # bookmark, because it looks like one.
            #
            # `<now>|` is a real bookmark: an empty id sorts below every real id, so
            # mail sent in this instant is still shown rather than swallowed. Erring
            # towards showing a message twice is recoverable; erring towards never
            # showing it is not — the same reasoning as `_cursor_parts`.
            cursor = since or _cursor_text((self.house.mailbox.now(), ""))

        # `unread` is always the true total, never the size of this page. A count that
        # silently meant "up to fifty" would let a backlog look handled.
        #
        # `totalItems` says the same thing under its ActivityStreams name, and it is
        # here for a client older than this route. Without it, upgrading the hub made
        # every already-running agent read `0 waiting` against a mailbox with eight
        # messages in it — mail that looks like it is not there, which is the precise
        # failure this mission exists to prevent, introduced by the mission itself.
        if view == "count":
            return {"unread": total, "totalItems": total, "cursor": cursor}
        if view == "full":
            return self.wire.collection([self.wire.note(m) for m in waiting])

        page: dict[str, Any] = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "type": "Collection",
            "unread": total,
            "totalItems": total,
            "cursor": cursor,
        }
        if total > len(waiting):
            page["more"] = total - len(waiting)
        if view == "threads":
            page["threads"] = self._threads(waiting)
        else:
            page["items"] = [self._summary(m) for m in waiting]
        return page

    async def search(
        self,
        name: str,
        caller: str,
        q: str = "",
        sender: str = "",
        since: str = "",
        until: str = "",
        limit: int = rules.SEARCH_DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Find mail this caller is party to. Consumes nothing, marks nothing.

        **On `/actors/{name}/search` rather than a bare `/search`**, which the plan
        proposed. Search is inherently "my mail", so it belongs on the same shape as
        `/actors/{name}/inbox` and behind the same `owns` guard — the one that exists
        because asking for `alice`'s inbox with a header of `bob` once returned Bob's.
        A bare path would have needed its own answer to the same question, and a second
        answer to a settled question is how the two drift apart.

        **`truncated` is part of the contract.** An agent that cannot tell a complete
        answer from a capped one either searches again for nothing or concludes that
        nothing else exists, and the second is worse: it looks like knowledge.
        """
        owns(name, caller, self.wire)
        matches, truncated = await self.house.search(
            caller, q, sender=sender, since=since, until=until, limit=limit
        )
        return {
            "query": q,
            "results": [self._result(m) for m in matches],
            "truncated": truncated,
        }

    def _result(self, match: rules.Match) -> dict[str, Any]:
        """One hit: enough to decide whether to open it, and nothing more.

        Shaped as `_summary` is, with a snippet added — a search result is a summary of
        a message that happens to have been found rather than delivered, and inventing a
        second dialect for the same thing is what `_summary`'s docstring already warns
        about.

        **`inReplyTo` is dropped, not nulled**, unlike `_summary`. A caller party to a
        reply but not to its parent would learn that the parent exists, which is the one
        place "real but not yours" is still distinguishable from "no such thing"
        (issue #45). That leak predates this route and is not this route's to fix — but
        it is very much this route's not to spread.

        Dropped rather than set to `null` because a field that is null *exactly when a
        thread is private* discloses the same fact in a quieter voice: every result
        would carry a reply marker, and only the sensitive ones would be empty.
        """
        result = {**self._summary(match.record), "snippet": match.snippet}
        result.pop("inReplyTo", None)
        return result

    def events(self, name: str, caller: str) -> ServerSentEvent:
        """A held connection that says when mail arrives. Says nothing else, ever.

        The one thing this hub contributes to being woken: *"there is mail for you, from
        X, about Y"*. What a client does about that — whether to interrupt an agent
        mid-turn, whether to wait for its next turn, whether to ignore it entirely — is
        the client's, and the hub never learns which was chosen. It could not decide
        well anyway: every harness is interrupted differently, and several cannot be.

        **This is not a second way to read mail.** No body crosses this wire, nothing
        here consumes, and no read is recorded. A client is told *that* a message exists
        and fetches it by the ordinary route if it wants it, which is what keeps
        `read_message` the only thing that marks anything handled.

        **Polling loses nothing but immediacy.** A client that cannot hold a connection
        — a CLI invocation, a harness with no MCP server, anything behind a proxy that
        will not allow it — sees exactly the mailbox it saw before. That is the floor,
        and it is deliberately still the floor: a hub that required a socket would have
        broken every client that already exists.
        """
        owner = owns(name, caller, self.wire)
        listeners = self.house.listeners
        # Asked here so a full hub refuses with a status and a reason a client can read.
        # Deciding it inside the generator instead would leave closing an
        # already-started stream as the only available refusal, and a client cannot tell
        # that from a network fault.
        if listeners.at_capacity():
            raise HTTPException(status_code=503, detail=listeners.full_message())

        async def stream() -> AsyncIterator[ServerSentEventMessage]:
            # Registered *inside* the generator, and this is the subtle half. An earlier
            # version registered above, next to the capacity check, which reads better
            # and leaks: if the response is never iterated — a client that disconnects
            # between the headers and the first frame — the `finally` below never runs,
            # because a generator that was never started has nothing to unwind. Each
            # occurrence would burn one slot out of the cap permanently, and a hub that
            # refuses connections while holding none is the exact "presents as working"
            # failure this module keeps trying to avoid.
            #
            # The cost is that check-then-register is not atomic: connections arriving
            # together at the boundary can briefly exceed the cap between them. That is
            # the safe direction — an overshoot of a few drains as those clients leave,
            # while a leaked slot never comes back.
            try:
                queue = listeners.open(owner)
            except TooManyListeners:
                # Only reachable by that race, since the check above passed. There is
                # nothing to say here that a client could act on: the stream simply
                # ends, and its reconnect finds either room or an honest 503.
                return
            try:
                while True:
                    try:
                        arrival = await asyncio.wait_for(
                            queue.get(), timeout=STREAM_KEEPALIVE_SECONDS
                        )
                    except TimeoutError:
                        # A comment, which is a legal SSE frame carrying no event. Idle
                        # connections are what proxies and load balancers close, so a
                        # stream that only spoke when there was mail would survive
                        # exactly as long as it was busy — the opposite of useful.
                        yield ServerSentEventMessage(comment="keep-alive")
                        continue
                    yield ServerSentEventMessage(
                        event="mail",
                        id=arrival.id,
                        data=json.dumps(arrival.as_event()),
                    )
            finally:
                # Reached on cancellation too, which is what a client vanishing looks
                # like from in here.
                listeners.close(owner, queue)

        return ServerSentEvent(stream())

    def _threads(self, waiting: tuple[Any, ...]) -> list[dict[str, Any]]:
        """Unread mail gathered into conversations, newest conversation first.

        Grouped *within the unread set only*. A reply whose parent the caller has
        already read, or never received, starts its own group rather than being filed
        under a turn they cannot see — C-003 keeps thread membership per turn, and a
        root id the caller has no right to would leak the existence of a private turn
        while pretending to be a convenience. The cost is that a conversation can appear
        as two groups; that is the safe direction to be wrong in.
        """
        by_id = {m.id: m for m in waiting}

        def root_of(record: Any) -> str:
            seen: set[str] = set()
            current = record
            while current.in_reply_to and current.in_reply_to in by_id:
                if current.id in seen:  # a cycle can only be corrupt data; stop.
                    break
                seen.add(current.id)
                current = by_id[current.in_reply_to]
            return str(current.id)

        groups: dict[str, list[Any]] = {}
        for record in waiting:
            groups.setdefault(root_of(record), []).append(record)

        summaries = []
        for root_id, turns in groups.items():
            ordered = sorted(turns, key=lambda m: m.published or "")
            latest, first = ordered[-1], ordered[0]
            summaries.append(
                {
                    "root": self.wire.object_uri(root_id),
                    "subject": first.summary or latest.summary or "(no subject)",
                    "unread": len(ordered),
                    "lastFrom": latest.attributed_to,
                    "lastPublished": latest.published,
                    "broadcast": len(latest.to) + len(latest.cc) > 1,
                }
            )
        summaries.sort(key=lambda t: t["lastPublished"] or "", reverse=True)
        return summaries

    def _summary(self, record: Any) -> dict[str, Any]:
        """One message, described rather than delivered.

        Everything a recipient decides from — who, what, when, is it a reply, how big —
        and nothing they would have to read. `chars` is there so "a broadcast I can
        safely leave" and "something long addressed to me" look different at a glance.

        **The field names are ActivityStreams', not new ones.** A summary is a Note with
        its `content` withheld, so it uses `attributedTo` and `summary` exactly as the
        full form does. The first version invented `from` and `subject`, which read
        better and broke every client older than the route: they looked for the AS2
        names, found nothing, and rendered a mailbox of `?` and `None`. Prettier names
        are not worth a reader who cannot see their mail.
        """
        body = record.content or ""
        return {
            "id": self.wire.object_uri(record.id),
            "type": "Note",
            # The full URI, as the full Note renders it — a summary must not be a
            # second dialect of the same message.
            "attributedTo": self.wire.actor_uri(record.attributed_to),
            "summary": record.summary or "(no subject)",
            "published": record.published,
            "inReplyTo": (
                self.wire.object_uri(record.in_reply_to) if record.in_reply_to else None
            ),
            "broadcast": len(record.to) + len(record.cc) > 1,
            "chars": len(body),
        }

    # -- maintenance -------------------------------------------------------

    async def purge_preview(self) -> dict[str, Any]:
        """What a purge would remove, described per conversation. Removes nothing."""
        return {
            **self._describe(await self.house.expire_preview()),
            "schedule": self.purge_status.as_dict(),
        }

    def _describe(self, doomed: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "threads": [
                {
                    "root": self.wire.object_uri(t.root),
                    "subject": t.subject,
                    "lastPublished": t.last_published,
                    "messages": t.messages,
                    "ids": [self.wire.object_uri(i) for i in t.ids],
                }
                for t in doomed
            ],
            "threadCount": len(doomed),
            "messageCount": sum(t.messages for t in doomed),
        }

    async def purge(self) -> dict[str, Any]:
        """Remove them. Irreversible, and there is nothing left behind to say so."""
        doomed = await self.house.purge()
        removed = sum(thread.messages for thread in doomed)
        api_logger.info(
            "event=mailbox.purge removed_threads=%d removed_objects=%d "
            "dry_run=false trigger=operator",
            len(doomed),
            removed,
        )
        return {**self._describe(doomed), "removed": removed}

    async def read_object(self, object_id: str, caller: str) -> Note:
        got = await self.house.read(caller, self.wire.object_id_from(object_id))
        return self.wire.note(got)

    async def view_object(self, object_id: str, caller: str) -> Note:
        got = await self.house.view(caller, self.wire.object_id_from(object_id))
        return self.wire.note(got)

    async def thread(self, object_id: str, caller: str) -> Collection:
        turns = await self.house.thread(caller, self.wire.object_id_from(object_id))
        if not turns:
            # Absent and forbidden are the same answer, on purpose.
            raise HTTPException(status_code=404, detail="no such thread")
        return self.wire.collection([self.wire.note(m) for m in turns])

    # -- observation (M2 FR-010) -------------------------------------------
    #
    # The operator's view of the hub, on its own route prefix. Everything above this
    # answers "what may this agent see"; everything here answers "what is on this hub",
    # which is a different question and must look different.
    #
    # The console used to get this by **impersonating** — sending `X-Agent-Name` for
    # whoever it wanted to look at — which worked only because nothing authenticates.
    # These routes replace that. They take no caller, so nobody's mail is marked read
    # by being looked at, and when authentication arrives there is exactly one prefix
    # to put an operator credential in front of.
    #
    # They are **not** privileged today, because nothing on this hub is. That is stated
    # on every console page rather than implied by a route prefix.

    async def survey(self, since: str = "") -> dict[str, Any]:
        # Defensive, not a fix: measured, this route does **not** currently misbehave on
        # a mangled timestamp, and an earlier draft of this comment wrongly claimed it
        # over-reported. It survives because it compares `published >= since` on a bare
        # string, and no real timestamp sorts between `...+00:00` and `... 00:00` — the
        # two forms differ only at the offset separator, and `>=` covers the equal case
        # either way.
        #
        # The inbox breaks on the same input because it compares a *tuple* with a strict
        # `>`: a seen message's own timestamp is greater than the mangled cursor, so it
        # stops being excluded.
        #
        # Which means this route is one operator away — `>=` to `>` — from acquiring the
        # bug the inbox already had, for a reason nobody changing it would think about.
        # Normalising both is one string operation and removes the trap rather than
        # documenting it.
        survey = await self.house.survey(since=unmangled_timestamp(since))
        # Held connections, added here rather than in the house because they are a fact
        # about *this process* and not about the mailbox: restart the hub and the number
        # is zero while every message is exactly where it was.
        #
        # Named for what it counts. `listeningSessions`, not "online" and not
        # "present" — an agent mid-turn on a long task is listening and reading
        # nothing, and an agent
        # with no MCP server never appears here and may be entirely here. What "present"
        # means is issue #7's decision; this is one input to it, and a number labelled
        # "online" would be that decision made by accident.
        listeners = self.house.listeners
        return {
            **survey,
            "listeningSessions": listeners.count(),
            "listeningBy": listeners.by_actor(),
        }

    async def observe_mailbox(self, name: str) -> Collection:
        items = await self.house.observe_mailbox(self.wire.name_from(name))
        return self.wire.collection([self.wire.note(m) for m in items])

    async def observe_outbox(self, name: str) -> Collection:
        """What one agent sent. The other half of :meth:`observe_mailbox`.

        Nothing could answer this before: `/actors/{name}/outbox` is the route an agent
        *posts* to, and no read of the sent side existed at any layer.
        """
        items = await self.house.observe_outbox(self.wire.name_from(name))
        return self.wire.collection([self.wire.note(m) for m in items])

    async def observe_recent(self, limit: int = DEFAULT_RECENT) -> Collection:
        """The last few messages to cross the hub, so a live view can start full.

        A page holding the event stream learns about arrivals *from now on*; without
        this it would open blank and stay blank until somebody happened to send
        something, which looks broken and is indistinguishable from being broken.

        **The bound is the hub's, not the caller's.** `limit` is clamped to
        :data:`MAX_RECENT` because an unbounded "recent" is a whole-store dump wearing a
        small name — and this route is reachable by any signed-in operator, so the cost
        of one careless query is the hub's to refuse rather than the caller's to
        remember. A caller wanting history has `/observe/mailbox/{name}`.
        """
        wanted = max(1, min(limit, MAX_RECENT))
        items = await self.house.observe_recent(wanted)
        return self.wire.collection([self.wire.note(m) for m in items])

    def observe_events(self) -> ServerSentEvent:
        """Every arrival on the hub, held open. Subjects and senders, never bodies.

        The operator's counterpart to :meth:`events`: that one is *an agent's* mail and
        needs the agent's own credential, this one is *the hub working* and needs only
        what every other `/observe/*` route needs. It discloses nothing new — a
        signed-in
        operator can already read any mailbox through `/observe/mailbox/{name}` — it
        shows the same authority as motion rather than as a series of lookups.

        Deliberately the same shape as :meth:`events`, differing only in which
        subscription it opens. If the two ever need to differ in any other way, that
        is a change both should get.
        """
        listeners = self.house.listeners
        # Asked before streaming, for the reason given in full on `events`: a refusal
        # decided inside the generator can only close an already-started stream, which a
        # client cannot tell apart from a network fault.
        if listeners.at_capacity():
            raise HTTPException(status_code=503, detail=listeners.full_message())

        async def stream() -> AsyncIterator[ServerSentEventMessage]:
            # Registered *inside* the generator. See `events` for why: registering
            # beside the capacity check above reads better, and permanently leaks a
            # slot whenever the response is never iterated.
            try:
                queue = listeners.open_everything()
            except TooManyListeners:
                return
            try:
                while True:
                    try:
                        arrival = await asyncio.wait_for(
                            queue.get(), timeout=STREAM_KEEPALIVE_SECONDS
                        )
                    except TimeoutError:
                        yield ServerSentEventMessage(comment="keep-alive")
                        continue
                    yield ServerSentEventMessage(
                        event="mail",
                        id=arrival.id,
                        data=json.dumps(arrival.as_event()),
                    )
            finally:
                listeners.close_everything(queue)

        return ServerSentEvent(stream())

    async def observe_object(self, object_id: str) -> dict[str, Any]:
        got = await self.house.observe_object(self.wire.object_id_from(object_id))
        if got is None:
            raise HTTPException(status_code=404, detail="no such message")
        note = self.wire.note(got)
        # Who has consumed it — the operator's question that an agent never asks, and
        # the reason this is not just `GET /objects/{id}` without a caller.
        return {
            **msgspec.to_builtins(note),
            "readBy": list(await self.house.observe_reads(got.id)),
        }

    async def observe_thread(self, object_id: str) -> Collection:
        turns = await self.house.observe_thread(self.wire.object_id_from(object_id))
        if not turns:
            raise HTTPException(status_code=404, detail="no such thread")
        return self.wire.collection([self.wire.note(m) for m in turns])

    async def federation_inbox(self, name: str, request: Request) -> dict[str, Any]:
        """Accept one `Create`/`Note` from a configured peer.

        Every check runs **before** delivery, and that ordering is the requirement: a
        refused message must provably never reach a mailbox. The tests assert on the
        recipient's inbox rather than on this function's return, because a 4xx with the
        message delivered anyway is exactly the failure the ordering prevents.

        Every refusal is the same refusal. Distinguishing "no such actor" from "not a
        peer" from "bad signature" would tell a stranger which was true, and the first
        two are what must stay unsaid.
        """
        mailbox = self.house.mailbox
        if not federates(await mailbox.hub_settings()):
            raise InboundRefused("this hub does not accept mail from other hubs")

        raw = await request.body()
        # Bounded and digest-checked before parsing: a signature that does not cover the
        # body authorises any body, so verification comes first and it must see the
        # bytes we actually received.
        sender = await self.verified_peer(request, body=raw)
        if sender is None:
            raise InboundRefused("that delivery was not signed by a peer of this hub")

        message = read_create(parse_activity(raw), sender)

        # **Claim before delivering, not check before delivering** (issue #41).
        #
        # This asked `seen_activity` and then sent. Two POSTs of one activity id — which
        # is precisely what the retry queue produces, because a client-side timeout does
        # not cancel the peer's in-flight request — both passed the question before
        # either wrote the answer, and both delivered. `Mailbox.send` mints a fresh uuid
        # per call, so nothing downstream could catch it.
        #
        # The claim is a single write, so exactly one caller wins it.
        if not await mailbox.claim_activity(message.activity_id):
            # FR-5: a retry is a no-op, not an error and not a second message.
            return {"delivered": False, "reason": "already seen"}

        # From here the claim is held, and every path out must either complete it or
        # give it back. Holding it while failing would make one bad delivery permanent:
        # the sender retries, the claim refuses, and the message is lost with nobody
        # able to see why.
        try:
            # `local_name` refuses `@local` and anything not addressed here, which is
            # what keeps the non-egress promise true from outside as well as inside.
            try:
                recipients = tuple(
                    addressing.local_name(one, mailbox.hub_name)
                    for one in message.recipients
                )
            except AddressError as refusal:
                raise InboundRefused("that delivery names nobody here") from refusal

            await self.house.send(
                caller="",
                to=recipients,
                body=message.body,
                subject=message.subject,
                in_reply_to=message.in_reply_to,
                remote_sender=message.sender,
            )
        except BaseException:
            # Broad on purpose, and it re-raises. A refusal, a store failure, or the
            # request being cancelled all leave the same state — claimed, undelivered —
            # and all of them should let the sender try again rather than being told for
            # ever that we have already seen it.
            #
            # Best-effort, because the claim's own lease is the real guarantee: if
            # giving it back also fails, the activity becomes deliverable again when the
            # lease expires. This only makes the common failure fast.
            with suppress(Exception):
                await mailbox.release_activity(message.activity_id)
            raise

        # **After the message is stored, never before.** The order is the guarantee: a
        # crash between the claim and here leaves an incomplete claim, which the lease
        # makes reclaimable, so the message arrives late. The other order would mark it
        # delivered and lose it.
        await mailbox.complete_activity(message.activity_id)
        return {"delivered": True}


def _refuse_blind_addressing(raw: dict[str, Any]) -> None:
    """Refuse `bto`/`bcc` rather than pretending to honour them.

    This hub has no blind delivery. Accepting the fields and dropping them would leave
    the sender believing a blind recipient got the message; accepting and echoing them
    — which is what happened before this check — showed every recipient the very list
    the field exists to hide. Saying no is the only honest answer.
    """
    inner = raw.get("object")
    present = sorted(
        {k for k in raw if k in BLIND_FIELDS}
        | (
            {k for k in inner if k in BLIND_FIELDS}
            if isinstance(inner, dict)
            else set()
        )
    )
    if present:
        raise HTTPException(
            status_code=422,
            detail=(
                "this mailbox does not support blind addressing "
                f"({', '.join(present)}). Send separate messages, or address "
                "everyone in `to`."
            ),
        )


def decode_activity(raw: dict[str, Any]) -> Create:
    """Accept a bare Note as well as a Create wrapping one.

    A client that posts what it means — a note — should not have to know that AS2 wraps
    it in an activity. We normalise rather than refuse.
    """
    if raw.get("type") == "Create" or "object" in raw:
        return msgspec.convert(raw, Create, strict=False)
    return Create(object=msgspec.convert(raw, Note, strict=False))


class PurgeStatus:
    """When the purge loop last actually completed a cycle, for anyone to look at.

    The CRITICAL log covers a loop that *dies*. It does not cover a loop that never
    reaches its first cycle, which is the failure that shipped in 0.18.1: every restart
    pushed the first run another interval away, and the startup line said "scheduled"
    the whole time. Nothing anywhere distinguished scheduled-and-working from
    scheduled-and-starving.

    A timestamp does. If it is absent long after startup, the loop is not running,
    whatever the startup log claimed. Raised by ludmila_coe, who noticed that the fix
    for that bug came with no way to tell it was working.
    """

    __slots__ = ("cycles", "last_cycle", "last_error", "removed_objects", "threads")

    def __init__(self) -> None:
        self.last_cycle: str | None = None
        self.cycles = 0
        self.threads = 0
        self.removed_objects = 0
        self.last_error: str | None = None

    def completed(self, threads: int, objects: int) -> None:
        self.last_cycle = datetime.now(UTC).isoformat()
        self.cycles += 1
        self.threads = threads
        self.removed_objects = objects
        self.last_error = None

    def failed(self, error: BaseException) -> None:
        self.last_error = f"{type(error).__name__}: {error}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "lastCycle": self.last_cycle,
            "cycles": self.cycles,
            "lastRemovedThreads": self.threads,
            "lastRemovedObjects": self.removed_objects,
            "lastError": self.last_error,
        }


#: How long after startup the first purge runs, when the interval is longer than this.
#: Not zero — a restart must not delete anything — but far short of an hour, so a hub
#: that is redeployed often still purges.
SETTLE_MINUTES = 5


def _complain_if_it_died(task: asyncio.Task[None]) -> None:
    """Say so, loudly, if the purge loop ever stops on its own.

    The case against a purge *sidecar* was that its failures would be invisible: it
    dies, purging silently stops, and the symptom is mail not expiring — which is
    exactly the symptom this project had from the beginning and nobody noticed.

    Moving the loop indoors does not by itself fix that; an in-process task can die just
    as quietly. `purge_forever` catches `Exception` around every cycle, so the only ways
    out are cancellation — expected, at shutdown — and something that is not an
    `Exception` at all. Both are silent unless somebody is watching. This watches.
    """
    if task.cancelled():
        return  # shutdown: the one way it is supposed to end
    if (failure := task.exception()) is not None:
        api_logger.critical(
            "event=mailbox.purge.stopped reason=raised — retention is NO LONGER "
            "RUNNING on this hub, and mail will accumulate until it is restarted",
            exc_info=failure,
        )
    else:
        api_logger.critical(
            "event=mailbox.purge.stopped reason=returned — the purge loop exited "
            "without an error, which it should not be able to do. Retention is no "
            "longer running on this hub."
        )


async def purge_forever(
    house: House, minutes: int, status: PurgeStatus | None = None
) -> None:
    """Remove conversations that have gone quiet, for as long as the hub is up.

    Retention was written, tested and documented long before it had a caller: nothing
    ever invoked `expire()`, so no message on any hub was ever removed and the prompt's
    promise that "mail expires after about a fortnight" was simply untrue. This is the
    caller.

    **It sleeps before its first run, deliberately.** Purging at startup would tie an
    unbounded, irreversible deletion to a container restart — the moment nobody is
    watching, decided by whoever happened to restart it, who does not know they are
    deciding anything. A hub that has just come up should serve, not delete.

    A failure is logged and the loop continues. Housekeeping is the one place where
    "keep serving mail" beats "fail loudly": on 2026-07-26 an unrelated error left an
    abandoned transaction and took the hub's mail down for eleven minutes, and a purge
    that kills the hub it maintains would be the same mistake wearing a different hat.
    """
    # The first cycle comes sooner than the rest, and that is not a compromise of the
    # no-deletion-at-startup rule — it is what makes the rule survivable.
    #
    # A hub that is restarted more often than its own interval would otherwise *never*
    # purge: every restart puts the first cycle another full hour away, and it never
    # arrives. This is not hypothetical — the hub this shipped on was redeployed roughly
    # every fifteen minutes on the evening it was written, so with a sixty-minute sleep
    # it would have run retention exactly never while reporting itself as scheduled.
    # That is the silent non-expiry this whole mission exists to end, rebuilt.
    #
    # Five minutes is long past startup, so nothing is deleted by the act of restarting,
    # and short enough that no plausible restart cadence can starve it.
    delay = min(minutes, SETTLE_MINUTES)
    while True:
        await asyncio.sleep(delay * 60)
        delay = minutes
        try:
            started = time.monotonic()
            doomed = await house.purge()
            removed = sum(thread.messages for thread in doomed)
            took = (time.monotonic() - started) * 1000
            if status is not None:
                status.completed(len(doomed), removed)
            # Logged every cycle, including when nothing goes. For the first fortnight
            # of any hub that is the *only* line there will be — nothing is old enough
            # to remove yet — and it is what tells us whether the window is right. A
            # purge that speaks only when it deletes teaches nothing while we are still
            # learning.
            # Structured, so it can be grepped and later monitored without anyone
            # having to parse an English sentence.
            api_logger.info(
                "event=mailbox.purge removed_threads=%d removed_objects=%d "
                "duration_ms=%.0f dry_run=false interval_minutes=%d",
                len(doomed),
                removed,
                took,
                minutes,
            )
        except asyncio.CancelledError:
            raise
        except Exception as failure:  # noqa: BLE001 - must not stop the hub
            if status is not None:
                status.failed(failure)
            api_logger.exception(
                "event=mailbox.purge.failed retrying_in_minutes=%d", minutes
            )


def build_api(
    house: House,
    public_url: str,
    *,
    debug: bool = False,
    auth: AuthService | None = None,
    auth_mode: str = "off",
    throttle: LoginThrottle | None = None,
    trust_proxy: bool = False,
    purge_interval_minutes: int = 0,
) -> Litestar:
    """Assemble the app. Everything routes through the house.

    ``auth`` and ``auth_mode`` govern how the caller is proven. With ``auth``
    absent or ``auth_mode == "off"`` the behaviour is exactly as before — the
    ``X-Agent-Name`` header is trusted — so the existing suite runs unchanged.
    Under ``warn`` a missing or invalid credential is logged and the request
    proceeds on the header; under ``enforce`` it is refused. None of this touches
    the engine: a verified caller is resolved here and handed down exactly where
    the header used to be (ADR 0007, ADR 0010).
    """
    enforcing = auth is not None and auth_mode == "enforce"
    api = Api(
        house,
        public_url,
        authenticated=enforcing,
        admin_password_set=auth is not None and auth.admin_password_set,
    )
    purge_status = PurgeStatus()
    api.purge_status = purge_status

    async def resolve_verified_caller(conn: ASGIConnection) -> str | None:
        """A caller proven by a credential — a token or a full session — or None.

        Raises :class:`TokenRevoked` for a presented-but-revoked token, which the error
        handler turns into a 401; an *absent* credential is ``None``, not an
        error, so the mode can decide what to do about it.
        """
        if auth is None or auth_mode == "off":
            return None
        bearer_actor: str | None = None
        header = conn.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            token = await auth.resolve_token(header[7:].strip())
            if token is not None and not token.may_act:
                # **A `ui` token grants nothing to act with** (#53). It is valid — it
                # authenticated — and it still yields no caller, because the console
                # only ever reads and every route it uses takes no caller at all.
                #
                # Fallen through rather than raised, and that distinction is
                # load-bearing: the console presents *both* its device token and the
                # signed-in human's cookie on the same request. Raising here would kill
                # the cookie branch below and lock out the operator holding it. Exactly
                # the shape that produced the `*`-attribution bug on 2026-08-05, and
                # exactly the same remedy — believe the more specific credential.
                #
                # What bounds the damage is scope, not lifetime: an eight-hour token
                # that could still send as any agent would impersonate the whole roster
                # for eight hours.
                api_logger.info(
                    "event=token.observe_only id=%s path=%s", token.id, conn.url.path
                )
                token = None
            if token is not None:
                # Here, and only here, are both halves in hand: the credential says the
                # holder is allowed in, and the header says which agent they are. A
                # secret cannot answer the second — several agents share one token — so
                # the combination happens at the one place that knows both.
                #
                # The header is read **softly**, not through `caller_name`, which
                # refuses a request that lacks it. Recording is a side effect, and a
                # side effect that can turn a request which would have succeeded into a
                # 400 is not a record — it is a new failure mode wearing one. The hard
                # requirement stays in `provide_caller`, where it already lived.
                claimed = conn.headers.get(IDENTITY_HEADER, "").strip()
                # **Record who was admitted, not who asked.** An outside review caught
                # these coming apart: a legacy token bound to `rosemary_nasrin` is
                # authorised as Rosemary whatever the header says, so recording the
                # claim would have written Trevor into the evidence table for a request
                # the hub served as Rosemary. That column is the whole point of this
                # mission — an operator decides what to revoke from it — and evidence
                # a sender can steer is worse than no evidence at all.
                admitted = claimed if token.actor == SHARED_ACTOR else token.actor
                # What the caller says it is running. A header, so it is what the hub
                # saw on this request rather than what an agent once wrote down.
                await auth.admit(token, admitted, _client_of(conn))
                bearer_actor = token.actor
                if token.actor != SHARED_ACTOR:
                    return token.actor
                # **A shared token names no one.** It proves this machine is allowed
                # here and says nothing about who is using it, so it must not out-rank
                # a session, which names a person. Falling through rather than
                # returning `"*"` — reported by the owner, 2026-08-05: the console
                # sends both its device token and the signed-in human's cookie, the
                # token won, and a reply was attributed to `*`, which has joined no
                # mailbox. Nothing is weakened: both credentials were verified, and
                # only the more specific of the two is being believed.
        sid = conn.cookies.get(SESSION_COOKIE)
        if sid:
            session = await auth.resolve_session(sid)
            if session is not None and not session.limited:
                return session.username
        # A shared token with no session is still a valid credential — it admits the
        # machine — so say so rather than reporting no credential at all.
        # `provide_caller` turns this into the header identity, which is how one
        # laptop runs four agents.
        if bearer_actor == SHARED_ACTOR:
            return SHARED_ACTOR
        return None

    async def provide_caller(request: Request) -> str:
        """The caller a request acts as — verified with auth on, header with it off.

        This is what the messaging routes depend on, so it is where enforcement
        for those routes lives: under ``enforce`` a request with no valid
        credential is refused here, before any handler runs.
        """
        if auth is None or auth_mode == "off":
            return caller_name(request)
        caller = await resolve_verified_caller(request)
        if caller == SHARED_ACTOR:
            # A shared token admits the machine, not a person: it proves the caller is
            # allowed here and says nothing about which agent they are, so the name
            # comes from the header as it does on an open hub. One laptop running four
            # coding agents holds one token, and they keep their separate identities.
            return caller_name(request)
        if caller:
            return caller
        if auth_mode == "enforce":
            raise NotAuthenticated(
                "this hub requires authentication — present a token as "
                "`Authorization: Bearer <token>`, or log in at the console"
            )
        # warn: resolve failed, but we still serve on the header identity and say so.
        api_logger.warning(
            "unauthenticated %s %s served in warn mode",
            request.method,
            request.url.path,
        )
        return caller_name(request)

    async def guard_enforce(
        connection: ASGIConnection, _handler: BaseRouteHandler
    ) -> None:
        """A Litestar guard for routes without a caller (observe, join).

        Under enforce, require *a* valid credential; otherwise a no-op. Runs before the
        handler, so an unauthenticated observe/join is refused before the store.
        """
        if not enforcing:
            return
        if await resolve_verified_caller(connection) is None:
            raise NotAuthenticated(
                "this hub requires authentication for this route — present a device "
                "token or log in at the console"
            )

    async def provide_operator(request: Request) -> str:
        """A human operator's username, for actions no agent should be able to take.

        Under ``off`` there is no auth, so a placeholder operator is returned (dev/LAN).
        Otherwise a full (non-limited) session is required. Minting or revoking a
        token is an operator action, and so is purging: a credential that lets an
        agent send mail must not also let it delete everyone's.
        """
        if auth is None or auth_mode == "off":
            return "operator"
        sid = request.cookies.get(SESSION_COOKIE)
        session = await auth.resolve_session(sid) if sid else None
        if session is not None and not session.limited:
            return session.username
        raise NotAuthenticated(
            "log in at the console as an operator — this action is not available to "
            "an agent's token, however valid"
        )

    @get("/", media_type=MediaType.JSON)
    async def hub() -> dict[str, Any]:
        descriptor = await api.hub()
        # Whether anyone has actually finished setting this hub up. The console shows
        # its first-run instructions from this, and must stop showing them once the
        # admin is enrolled — an operator who has been using a hub for months should
        # not still be told where to find a password they set long ago.
        #
        # It discloses nothing that was not already public: the login page has always
        # said a fresh hub prints its password, and this only says whether that is
        # still true here.
        setup_required = False
        # `off` means there is nothing to set up, whether or not a service was built —
        # so it must not ask an operator to go and find a password they will never need.
        if auth is not None and auth_mode != "off":
            admin = await auth.pending_setup()
            setup_required = admin is not None
            if admin:
                descriptor["setupUser"] = admin
        descriptor["setupRequired"] = setup_required
        return descriptor

    @get("/federation")
    async def federation_descriptor_route() -> dict[str, Any]:
        """What a peer needs before talking to this hub. Unauthenticated by design —
        the caller is a stranger and this is what strangers are entitled to."""
        return await api.federation_descriptor()

    @get("/.well-known/nodeinfo")
    async def nodeinfo_index_route() -> dict[str, Any]:
        """Unauthenticated, as every fediverse server serves it."""
        return await api.nodeinfo_index()

    @get("/nodeinfo/2.1")
    async def nodeinfo_route() -> dict[str, Any]:
        return await api.nodeinfo()

    @get("/.well-known/webfinger")
    async def webfinger_route(resource: str) -> dict[str, Any]:
        """Unauthenticated, as WebFinger is everywhere. Silent unless federating."""
        return await api.webfinger(resource)

    @get("/prompts/{role:str}", media_type=MediaType.TEXT)
    async def prompt_route(role: str) -> str:
        """The onboarding prompt, as plain text, from the API itself.

        **Unauthenticated on purpose, and the one route where that is not a hole.** An
        agent needs this document *before* it has a credential — the prompt is what
        tells it how to get one — so gating it would be a lock whose key is inside.

        It publishes nothing an outsider does not already have: this hub's address,
        which they had in order to ask, and the version, which the descriptor gives
        anyone. The caution about an unauthenticated hub is generated from the hub's own
        setting, so an enforcing hub cannot accidentally serve the open-hub warning.

        Owner, 2026-08-05: the console used to be the only thing serving this, which
        meant the console had a page readable without signing in. Serving it here
        instead puts an unauthenticated document on the unauthenticated surface, and
        lets the console gate everything it shows a human.

        Any role name returns the same text — `/prompts/agent`, `/prompts/host`,
        `/prompts/admin` are one document. What a role *means* is fetched from the hub
        at runtime, so there is nothing per-role to write here, and accepting the names
        keeps every bookmark and pasted instruction working.
        """
        del role  # accepted, deliberately not dispatched on — see above
        descriptor = await api.hub()
        return onboarding(
            public_url,
            f"{public_url}/prompts/agent",
            str(descriptor.get("version") or ""),
            bool(descriptor.get("authenticated")),
        )

    @get("/health")
    async def health() -> dict[str, str]:
        return await api.health()

    @get("/doctor")
    async def doctor(request: Request) -> dict[str, Any]:
        """What the hub makes of *this* caller — the half a client cannot see.

        **Deliberately unguarded, and deliberately never a 4xx.** The caller who most
        needs this answer is the one whose credential is missing or revoked, and a route
        that refused them would meet them with the very status they came here to
        understand. So it reports, always, and reports only on the hub's posture and on
        the caller themselves — never who else is here, which is what a guard would
        properly protect.

        It answers what a client can otherwise only guess at: does this hub require a
        credential, did mine arrive, was it accepted, and does the hub know the name I
        think I have? A client guessing at those was the thing being debugged.
        """
        # Not `caller_name`: that refuses a missing header with a 400, and "you did not
        # tell me who you are" is a finding here, not a failure.
        claimed = request.headers.get(IDENTITY_HEADER, "").strip()
        enforced = auth is not None and auth_mode == "enforce"
        checking = auth is not None and auth_mode != "off"

        token_state = "not presented"
        verified: str | None = None
        # Resolve whatever credential arrived — a bearer token *or* a session cookie.
        # Only asking about the token left `verified` empty for a signed-in human,
        # which is how the console came to act as itself rather than as the operator.
        bearer = request.headers.get("Authorization", "").lower().startswith("bearer ")
        if bearer or request.cookies.get(SESSION_COOKIE):
            try:
                verified = await resolve_verified_caller(request)
                if bearer:
                    token_state = "accepted" if verified else "rejected"
            except AuthError:
                # A revoked token raises. That is an answer worth giving precisely,
                # since "revoked" and "wrong" call for different actions.
                token_state = "revoked"

        # **Whether a name exists is only answered to a caller the hub can identify.**
        # On an enforcing hub this route was an existence oracle: an unauthenticated
        # stranger sending X-Agent-Name learned `known: true` for a real agent and
        # `known: false` otherwise, and could enumerate the roster by guessing. The
        # docstring above already promised "never who else is here" — this makes it
        # true. Found by outside review, 2026-07-29.
        #
        # A hub that does not enforce answers as before: it has no roster to protect
        # that the identity header does not already give away.
        may_answer_existence = (not enforced) or verified is not None
        known = (
            await house.mailbox.whois(claimed)
            if claimed and may_answer_existence
            else None
        )

        # Credentials are judged before identity, because on an enforcing hub they
        # block the very step that would fix an unknown name: joining is guarded too,
        # so "join to claim it" would be advice the caller cannot take.
        if token_state == "revoked":
            verdict = "your token has been revoked — ask an operator to mint another"
        elif token_state == "rejected":
            verdict = "your token was not recognised — ask an operator to mint another"
        elif enforced and token_state == "not presented":
            verdict = (
                "no token presented, and this hub requires one for everything, "
                "including joining — ask an operator to mint you one"
            )
        elif enforced and not may_answer_existence:
            verdict = (
                "present a credential and ask again — this hub will not say whether a "
                "name exists to a caller it cannot identify"
            )
        elif not claimed:
            verdict = "you sent no name — join, and one will be issued to you"
        elif known is None:
            verdict = (
                f"this hub has no actor named {claimed!r} — join to claim it. "
                "Joining also writes your configuration; there is no second step."
            )
        elif token_state == "accepted" and verified == SHARED_ACTOR:
            verdict = (
                "your token was accepted — it is a shared token, so it admits this "
                "machine and your name is taken from the header as usual"
            )
        elif token_state == "accepted":
            verdict = "your token was accepted"
        elif not checking:
            verdict = "this hub does not authenticate; you are taken at your word"
        else:
            verdict = (
                "no token presented. This hub does not require one yet, but it is "
                "checking — you will be locked out when it starts enforcing"
            )

        return {
            "hub": {
                "name": house.mailbox.hub_name,
                "version": __version__,
                "authMode": auth_mode,
                "credentialRequired": enforced,
                # An operator should be able to find this out without reading the
                # compose file. Only mentioned when true: a line saying "secure: yes"
                # on every hub is noise that trains people not to read it.
                **({"insecureFederation": True} if insecure_federation() else {}),
            },
            "you": {
                "claimed": claimed,
                # `null` where the hub declines to say, which is not the same as
                # `false`. A caller debugging a name deserves the difference.
                "known": (known is not None) if may_answer_existence else None,
                "verified": verified,
                "token": token_state,
            },
            # One sentence the client prints verbatim. The hub is the only party that
            # knows all of the above, so it says what to do rather than leaving a client
            # to infer it from a status code — which is how clients come to guess.
            "verdict": verdict,
        }

    @post("/actors", status_code=201, guards=[guard_enforce])
    async def join(data: dict[str, Any]) -> Actor:
        return await api.join(data)

    # Guarded like the observe routes. A directory is for lookups *by the people on
    # the hub* — under enforce, an unauthenticated caller could otherwise enumerate
    # every agent here, which is precisely the disclosure authentication was turned on
    # to prevent, and it is what let the console's Tokens page render to a stranger.
    # Under off/warn the guard is a no-op, so nothing changes for a trusted LAN.
    @get("/actors", guards=[guard_enforce])
    async def directory(request: Request) -> Collection:
        """Who is here — everyone to a verified local caller, `discoverable` only to
        anyone else.

        **Filtered only when the hub federates**, which is T012's evaluation order —
        hub mode first — and not a convenience. On a hub that does not federate there is
        no outside to withhold from: the directory is a local tool, agents find each
        other with it, and hiding half of them would break the product to protect
        against a stranger who cannot reach the port anyway.

        The first version of this gated on *verification* instead, and broke every
        `AUTH_MODE=off` deployment — where nobody is verified by definition, so the
        directory went empty. Two existing tests caught it.
        """
        federating = federates(await api.house.mailbox.hub_settings())
        verified = enforcing and await resolve_verified_caller(request) is not None
        return await api.directory(listed_only=federating and not verified)

    @get("/actors/{name:str}")
    async def actor(name: str, request: Request) -> Any:
        """Rich to a verified caller; barebones to a federating stranger; else refused.

        Three audiences, and they are not the same. An **agent on this hub** presents a
        token and gets the full document. A **peer hub** presents nothing, and
        gets only what addressing requires (`thin_actor`). Anyone else, on a hub that
        does not federate, is refused exactly as before.

        **Visibility is a ceiling, never a grant** (FR-016), and the evaluation order
        is hub mode, then peering, then visibility. A `discoverable` actor on a hub with
        federation off is still unreachable — asking to be found does not override the
        operator's decision not to federate at all. The field can only ever withhold.

        A `local` actor is refused to everybody who is not a verified caller on this
        hub, in the same words an unknown name gets.
        """
        federating = federates(await api.house.mailbox.hub_settings())
        verified = enforcing and await resolve_verified_caller(request) is not None

        if verified:
            return await api.actor(name)
        # Everything below this line is somebody who is not a verified local caller, so
        # visibility applies to all of it. Checked once, here, rather than in each of
        # the three branches — three copies of a disclosure rule is how one of them
        # ends up a word different from the others.
        if federating or await api.verified_peer(request) is not None:
            await api._resolvable_or_absent(name)  # noqa: SLF001 - same module, one rule
        if federating and await api.verified_peer(request) is not None:
            # A peer that proved which hub it is gets what a local agent gets. This is
            # what the thin/rich split was built for: without signatures there was no
            # way to ever be verified, so everyone got thin forever.
            return await api.actor(name)
        if federating:
            # **A hub that cannot tell its own agents from strangers must assume
            # stranger.** With `AUTH_MODE=off` nobody is verified — the header is taken
            # at face value and a remote peer can send it too — so once federation is
            # on, this route serves the barebones document to everyone. Local callers
            # that need the full record have routes that identify them.
            #
            # Found by the two-hub harness: before this, a non-enforcing hub with
            # federation enabled published every agent's profile to the world.
            return await api.thin_actor(name)
        if not enforcing:
            return await api.actor(name)
        raise NotAuthenticated(
            "this hub requires authentication for this route — present a device "
            "token, or ask its operator to enable federation"
        )

    @put("/actors/{name:str}", dependencies={"caller": Provide(provide_caller)})
    async def update_profile(name: str, data: dict[str, Any], caller: str) -> Actor:
        return await api.update_profile(name, data, caller)

    @get("/actors/{name:str}/inbox", dependencies={"caller": Provide(provide_caller)})
    async def inbox(
        name: str,
        caller: str,
        view: str = "summary",
        since: str | None = None,
    ) -> Collection | dict[str, Any]:
        return await api.inbox(name, caller, view=view, since=since)

    @get("/actors/{name:str}/search", dependencies={"caller": Provide(provide_caller)})
    async def search(
        name: str,
        caller: str,
        q: str = "",
        sender: str = "",
        since: str = "",
        until: str = "",
        limit: int = rules.SEARCH_DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        return await api.search(
            name, caller, q=q, sender=sender, since=since, until=until, limit=limit
        )

    @get(
        "/actors/{name:str}/events",
        dependencies={"caller": Provide(provide_caller)},
        # No `media_type` here on purpose. `ServerSentEvent` sets `text/event-stream`
        # itself, and naming one on the decorator *overrides* it — which produced a
        # stream served as `text/plain` that every hand-written test was happy with and
        # a real `EventSource` would refuse outright.
    )
    async def events(name: str, caller: str) -> ServerSentEvent:
        return api.events(name, caller)

    @post("/actors/{name:str}/inbox")
    async def federation_inbox(name: str, request: Request) -> dict[str, Any]:
        return await api.federation_inbox(name, request)

    @post(
        "/actors/{name:str}/outbox",
        status_code=201,
        dependencies={"caller": Provide(provide_caller)},
    )
    async def outbox(name: str, request: Request, caller: str) -> Note:
        return await api.outbox(name, request, caller)

    @get("/objects/{object_id:str}", dependencies={"caller": Provide(provide_caller)})
    async def view_object(object_id: str, caller: str) -> Note:
        return await api.view_object(object_id, caller)

    @post(
        "/objects/{object_id:str}/retract",
        # 200, not 201: withdrawing a body creates nothing.
        status_code=200,
        dependencies={"caller": Provide(provide_caller)},
    )
    async def retract_object(object_id: str, caller: str) -> dict[str, Any]:
        """Withdraw a message's body, keeping its place in the conversation.

        **The permission decision is not here.** `retraction.retract` owns it — an agent
        may withdraw its own, a human may withdraw anything on this hub — and this route
        does no more than say who is asking. A second answer to that question, anywhere,
        would eventually disagree with the first, and the disagreement would be
        somebody's words destroyed by a caller who should not have been able to.

        `provide_caller`, not `provide_operator`: an agent retracting its own message is
        an ordinary act, not an operator action, and the scope is settled below.

        **Local only** (FR-015). A copy already delivered to a peer hub is not withdrawn
        and nothing in this response says it was.
        """
        from agent_inbox import retraction

        gone = await retraction.retract(house.mailbox.store, object_id, caller)
        return {
            "id": gone.id,
            "retracted": True,
            "by": retraction.retracted_by(gone),
            # Said plainly, because the alternative is a client inferring that a
            # retraction reached everywhere the message did.
            "scope": "this hub only — copies delivered to peer hubs are not withdrawn",
        }

    @post(
        "/objects/{object_id:str}/retract-thread",
        status_code=200,
        dependencies={"caller": Provide(provide_caller)},
    )
    async def retract_thread_route(
        object_id: str, caller: str, request: Request
    ) -> dict[str, Any]:
        """Retract every message in this thread that the caller has the power to.

        **A partial outcome is the normal answer, not an error.** A human takes the
        whole conversation; an agent takes its own turns and is refused the rest. Both
        lists come back, because "done" would hide what stayed — and an operator who
        believes a conversation is gone when it is not will act on that belief.

        The thread is computed here, from the same walk the reader saw, so the set
        retracted is the set they were looking at rather than one assembled differently.
        """
        from agent_inbox import threads

        turns = await house.mailbox.thread(caller, object_id)
        done = await threads.retract_thread(
            house.mailbox.store, [t.id for t in turns], caller
        )
        return {
            "retracted": list(done.retracted),
            "refused": [{"id": r.object_id, "reason": r.reason} for r in done.refused],
            "partial": done.partial,
            "scope": "this hub only — copies delivered to peer hubs are not withdrawn",
        }

    @post(
        "/objects/{object_id:str}/read",
        # 200, not Litestar's default 201: consuming a message creates nothing.
        status_code=200,
        dependencies={"caller": Provide(provide_caller)},
    )
    async def read_object(object_id: str, caller: str) -> Note:
        return await api.read_object(object_id, caller)

    @get(
        "/objects/{object_id:str}/thread",
        dependencies={"caller": Provide(provide_caller)},
    )
    async def thread(object_id: str, caller: str) -> Collection:
        return await api.thread(object_id, caller)

    # The observation routes are the operator's view — under enforce they need a valid
    # credential (this is what finally makes them safe to expose; M2 FR-010).
    @get("/observe/purge/status", guards=[guard_enforce])
    async def purge_status_route() -> dict[str, Any]:
        """Whether retention is actually running. No mail, no subjects, no deletion.

        Deliberately **not** operator-only, unlike the preview beside it. "Is
        housekeeping alive?" is the question anyone should be able to ask, and needing
        the one credential that can delete everything in order to ask it is how a check
        stops being done. It answers with timings and counts; the preview, which lists
        the subjects of conversations about to die, stays operator-gated.

        The distinction was found by trying to verify the heartbeat on a live hub and
        being refused by my own guard — correctly, and uselessly.
        """
        return api.purge_status.as_dict()

    @get(
        "/hub/settings",
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def hub_settings_route(operator: str) -> dict[str, Any]:
        """What is set, and by whom. Operator-gated: deployment configuration."""
        return await api.hub_settings()

    @put(
        "/hub",
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def set_hub_route(data: dict[str, Any], operator: str) -> dict[str, Any]:
        """Change name, title or description. Administrative, so operator-only.

        Omitted fields are left alone — a partial body is the normal case. An explicit
        `null` clears a field, which is different from never having set it.
        """
        return await api.set_hub_settings(data)

    @get(
        "/operators",
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def list_operators_route(operator: str) -> dict[str, Any]:
        """Every human who can sign in. All of them are admins."""
        assert auth is not None
        people = await auth.operators()
        return {
            "operators": [
                {
                    "username": u.username,
                    "email": u.email,
                    "group": u.group,
                    "state": str(u.enrolment_state),
                    "created": u.created,
                    "last_login": u.last_login,
                }
                for u in people
            ],
            # Said by the API, not only by the console, because a client that reads
            # `group` and assumes it is a permission would be wrong today.
            "groups_enforced": False,
        }

    @post(
        "/operators",
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def add_operator_route(data: dict[str, Any], operator: str) -> dict[str, Any]:
        """Invite a human. The one-time password comes back **once**.

        This hub sends no mail, so whoever invites has to pass it on themselves. The
        address is stored for a password-recovery flow that does not exist yet — asking
        for it after someone is locked out is too late.
        """
        assert auth is not None
        from agent_inbox import merge

        # Through the coordinator, not `auth.add_operator` directly: an operator account
        # and a mailbox are one identity now, and creating one half without the other is
        # the state everything downstream misbehaves in. `merge.create_human` is the one
        # place that knows a human needs both.
        password = await merge.create_human(
            auth,
            house.mailbox.store,
            str(data.get("username", "")),
            str(data.get("email", "")),
            str(data.get("group", "") or "admin"),
        )
        return {
            "username": str(data.get("username", "")).strip().lower(),
            "password": password,
            "note": (
                "Shown once. They must set their own password and enrol a second "
                "factor before this account can do anything."
            ),
        }

    @delete(
        "/operators/{username:str}",
        status_code=200,
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def remove_operator_route(username: str, operator: str) -> dict[str, Any]:
        """Remove a human. Refused for the last one — see `LastOperator`."""
        assert auth is not None
        await auth.remove_operator(username)
        return {"username": username, "removed": True}

    @get(
        "/observe/peers",
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def list_peers_route(operator: str) -> dict[str, Any]:
        """Who this hub trusts. Operator-gated: the trust list is deployment state."""
        return await api.list_peers()

    @post(
        "/observe/peers",
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def add_peer_route(data: dict[str, Any], operator: str) -> dict[str, Any]:
        """Trust a hub. Operator-only, per ADR 0008 — an agent that could add a peer
        could be talked into adding one."""
        return await api.add_peer(data)

    @delete(
        "/observe/peers",
        status_code=200,
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def remove_peer_route(origin: str, operator: str) -> dict[str, Any]:
        """Stop trusting a hub. Takes effect on the next send, because authorization is
        never carried from anywhere (FR-050)."""
        return await api.remove_peer(origin)

    @get(
        "/observe/blocks",
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def list_blocks_route(operator: str) -> dict[str, Any]:
        """Who this hub refuses. Operator-only: a roster of refusals is a statement
        about other people, and not one to hand to anybody who asks."""
        return await api.blocks()

    @post(
        "/observe/blocks",
        status_code=201,
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def add_block_route(data: dict[str, Any], operator: str) -> dict[str, Any]:
        """Refuse a hub. Operator-only, for the same reason adding a peer is: an agent
        that could edit the blocklist could be talked into editing it."""
        return await api.add_block(data)

    @delete(
        "/observe/blocks",
        status_code=200,
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def remove_block_route(origin: str, operator: str) -> dict[str, Any]:
        """Stop refusing a hub. Takes effect on the next exchange, because the decision
        is made per attempt and never carried (FR-050)."""
        return await api.remove_block(origin)

    @get(
        "/observe/purge",
        guards=[guard_enforce],
        dependencies={"operator": Provide(provide_operator)},
    )
    async def purge_preview(operator: str) -> dict[str, Any]:
        """What a purge would remove. Reads only — safe to call at any time."""
        return await api.purge_preview()

    @post(
        "/observe/purge",
        guards=[guard_enforce],
        status_code=200,
        dependencies={"operator": Provide(provide_operator)},
    )
    async def purge_now(operator: str) -> dict[str, Any]:
        """Purge now, rather than waiting for the next scheduled run.

        Operator-only, because it deletes. There are no tombstones and no undo, so
        anyone reaching for this should have read the preview first — which is why the
        preview is a separate, read-only route rather than a flag on this one.
        """
        return await api.purge()

    @get("/observe/stats", guards=[guard_enforce])
    async def observe_stats(since: str = "") -> dict[str, Any]:
        return await api.survey(since)

    @get("/observe/mailbox/{name:str}", guards=[guard_enforce])
    async def observe_mailbox(name: str) -> Collection:
        return await api.observe_mailbox(name)

    @get("/observe/outbox/{name:str}", guards=[guard_enforce])
    async def observe_outbox(name: str) -> Collection:
        return await api.observe_outbox(name)

    @get("/observe/recent", guards=[guard_enforce])
    async def observe_recent(limit: int = DEFAULT_RECENT) -> Collection:
        return await api.observe_recent(limit)

    @get("/observe/events", guards=[guard_enforce])
    async def observe_events() -> ServerSentEvent:
        # Takes no caller, like every other `/observe/*` route: this is the hub working,
        # not one agent's mail. `/actors/{name}/events` is the per-agent stream and
        # keeps requiring that agent's own credential.
        return api.observe_events()

    @get("/observe/objects/{object_id:str}", guards=[guard_enforce])
    async def observe_object(object_id: str) -> dict[str, Any]:
        return await api.observe_object(object_id)

    @get("/observe/objects/{object_id:str}/thread", guards=[guard_enforce])
    async def observe_thread(object_id: str) -> Collection:
        return await api.observe_thread(object_id)

    # -- authentication routes --------------------------------------------
    #
    # Present only when auth is configured. They call the AuthService directly; the
    # messaging engine never sees them.

    def _client_of(conn: Any) -> str:
        """The client version this request reported, or ``""``.

        Trimmed and bounded: it is caller-controlled text that ends up on an operator's
        screen, so it is treated as a label rather than believed. An older client sends
        nothing, which is why blank must mean "leave the last known value alone" rather
        than "erase it".
        """
        raw = conn.headers.get(CLIENT_HEADER, "")
        return str(raw).strip()[:64]

    async def _session_user(request: Request, *, allow_limited: bool) -> str:
        """The username behind the session cookie, or a 401. Optionally allow a limited
        (first-run enrolment) session."""
        assert auth is not None
        sid = request.cookies.get(SESSION_COOKIE)
        session = await auth.resolve_session(sid) if sid else None
        if session is None or (session.limited and not allow_limited):
            raise NotAuthenticated("log in first")
        return session.username

    def _session_cookie(session_id: str) -> Cookie:
        return Cookie(
            key=SESSION_COOKIE,
            value=session_id,
            httponly=True,
            samesite="lax",
            path="/",
        )

    def _client_source(request: Request) -> str:
        """The source key the throttle counts against — the client's IP.

        Behind a trusted proxy the connection IP is the proxy, so honour the
        first X-Forwarded-For hop (the original client) — but only when
        trust_proxy is set: trusting the header from an untrusted caller would let
        it spoof its source and dodge the limiter.
        """
        if trust_proxy:
            fwd = request.headers.get("X-Forwarded-For", "")
            if fwd:
                return fwd.split(",")[0].strip()
        client = request.client
        return client.host if client else "unknown"

    @post("/auth/login", status_code=200)
    async def auth_login(request: Request, data: dict[str, Any]) -> Response:
        assert auth is not None
        source = _client_source(request)
        if throttle is not None and not throttle.allowed(source):
            raise TooManyAttempts(
                "too many failed sign-ins from your address — wait and try again",
                retry_after=throttle.retry_after(source),
            )
        try:
            result = await auth.login(
                str(data.get("username", "")),
                str(data.get("password", "")),
                data.get("otp"),
            )
        except AuthError:
            # Any refused sign-in counts toward the lockout (kept generic — the throttle
            # is keyed by source, so it reveals nothing about which account exists).
            if throttle is not None:
                throttle.record_failure(source)
            raise
        if throttle is not None:
            throttle.record_success(source)
        nxt = "enrol" if result.enrolment_required else "ok"
        return Response({"next": nxt}, cookies=[_session_cookie(result.session.id)])

    @post("/auth/logout", status_code=200)
    async def auth_logout(request: Request) -> Response:
        assert auth is not None
        sid = request.cookies.get(SESSION_COOKIE)
        if sid:
            await auth.logout(sid)
        return Response(
            {"next": "ok"},
            cookies=[Cookie(key=SESSION_COOKIE, value="", path="/", max_age=0)],
        )

    @get("/auth/enrol")
    async def auth_enrol_begin(request: Request) -> dict[str, Any]:
        assert auth is not None
        username = await _session_user(request, allow_limited=True)
        offer = await auth.begin_enrolment(username)
        return {
            "provisioningUri": offer.provisioning_uri,
            "qrSvg": offer.qr_svg,
            "recoveryCodes": list(offer.recovery_codes),
        }

    @post("/auth/enrol", status_code=200)
    async def auth_enrol_complete(request: Request, data: dict[str, Any]) -> Response:
        assert auth is not None
        username = await _session_user(request, allow_limited=True)
        await auth.complete_enrolment(
            username, str(data.get("password", "")), str(data.get("otp", ""))
        )
        session = await auth.open_full_session(username)
        return Response({"next": "ok"}, cookies=[_session_cookie(session.id)])

    @post("/auth/change-password", status_code=200)
    async def auth_change_password(
        request: Request, data: dict[str, Any]
    ) -> dict[str, str]:
        assert auth is not None
        username = await _session_user(request, allow_limited=False)
        await auth.change_password(
            username, str(data.get("current", "")), str(data.get("new", ""))
        )
        return {"next": "ok"}

    @get("/auth/rotate-2fa")
    async def auth_rotate_begin(request: Request) -> dict[str, Any]:
        assert auth is not None
        username = await _session_user(request, allow_limited=False)
        offer = await auth.begin_enrolment(username)
        return {
            "provisioningUri": offer.provisioning_uri,
            "qrSvg": offer.qr_svg,
            "recoveryCodes": list(offer.recovery_codes),
        }

    @post("/auth/rotate-2fa", status_code=200)
    async def auth_rotate_confirm(
        request: Request, data: dict[str, Any]
    ) -> dict[str, str]:
        assert auth is not None
        username = await _session_user(request, allow_limited=False)
        await auth.confirm_2fa(username, str(data.get("otp", "")))
        return {"next": "ok"}

    @post(
        "/auth/tokens",
        status_code=201,
        dependencies={"operator": Provide(provide_operator)},
    )
    async def mint_token(data: dict[str, Any], operator: str) -> dict[str, str]:
        """Mint a token. It admits a machine; nothing here names an agent.

        **A label is required.** A list of unlabelled tokens is a list nobody can act
        on: an operator deciding what is safe to revoke has only the label and the
        agents it has admitted to go on, and inventing one for them would put our guess
        in the column that is supposed to hold their claim.
        """
        assert auth is not None
        label = str(data.get("label", "")).strip()
        if not label:
            raise HTTPException(
                status_code=400,
                detail="give the token a label — which machine is it for? A list of "
                "unlabelled tokens is one nobody can safely revoke from.",
            )
        minted = await auth.mint_token(label=label)
        return {"id": minted.id, "token": minted.secret}

    @get("/auth/tokens", dependencies={"operator": Provide(provide_operator)})
    async def list_tokens(operator: str) -> dict[str, Any]:
        """Every token on the hub, with what it was issued as and what it has admitted.

        `boundTo` and `admitted` stay separate on purpose, and it is the same rule the
        console renders: one is what the row was created with, the other is what the hub
        observed. A claim shown where a finding appears to be is how somebody revokes
        the wrong credential.
        """
        assert auth is not None
        items = []
        for token in await auth.list_tokens():
            uses = await auth.token_uses(token.id)
            items.append(
                {
                    "id": token.id,
                    "label": token.label,
                    "created": token.created,
                    # `None`, not "", so "never used" and "used at an unknown time" stay
                    # different facts. They lead to different actions.
                    "lastUsed": token.last_used or None,
                    "revoked": token.revoked,
                    "boundTo": None if token.actor == SHARED_ACTOR else token.actor,
                    "admitted": [
                        {
                            "name": u.actor,
                            "firstSeen": u.first_seen,
                            "lastSeen": u.last_seen,
                            "uses": u.uses,
                            # What that agent's client last reported. Observed by this
                            # hub on a real request, so it belongs beside the other
                            # things the hub knows rather than the things it was told.
                            "client": u.client,
                        }
                        for u in uses
                    ],
                }
            )
        return {"items": items}

    @delete(
        "/auth/tokens/{token_id:str}",
        status_code=200,
        dependencies={"operator": Provide(provide_operator)},
    )
    async def revoke_token(token_id: str, operator: str) -> dict[str, Any]:
        """Revoke, and say what was just cut off.

        Revocation already takes effect on the next call. What is new is the answer to
        the only question an operator is actually asking — *what will this break?* — so
        the response names the agents this token had admitted.

        Deliberately not 204. A body is the point.
        """
        assert auth is not None
        admitted = [u.actor for u in await auth.token_uses(token_id)]
        revoked = await auth.revoke_token(token_id)
        return {"revoked": revoked, "admitted": admitted}

    async def open_the_house(_: Litestar) -> None:
        """Establish standing invariants once, at startup.

        This is where `admin` and `host` come into being. Without it the hub would
        serve happily and quietly have nowhere to report a fault to.

        It is also where **an operator account becomes a mailbox** (owner, 2026-08-05).
        Idempotent, so it runs every boot and does nothing after the first — which is
        what makes it safe to put here rather than behind a command somebody has to
        remember on the one deployment that needed it.
        """
        await house.open()
        if auth is not None:
            from agent_inbox import merge

            report = await merge.adopt_existing(auth, house.mailbox.store)
            for line in report.lines():
                # `warning`, including for a plain rename: somebody's login changed and
                # this log is the only place several operators will ever see it.
                api_logger.warning("event=namespace.migration %s", line)

    handlers = [
        hub,
        health,
        prompt_route,
        federation_descriptor_route,
        nodeinfo_index_route,
        nodeinfo_route,
        webfinger_route,
        hub_settings_route,
        set_hub_route,
        list_operators_route,
        add_operator_route,
        remove_operator_route,
        list_peers_route,
        add_peer_route,
        list_blocks_route,
        add_block_route,
        remove_block_route,
        remove_peer_route,
        purge_preview,
        purge_status_route,
        purge_now,
        doctor,
        join,
        directory,
        actor,
        update_profile,
        inbox,
        search,
        events,
        federation_inbox,
        outbox,
        view_object,
        observe_stats,
        observe_mailbox,
        observe_outbox,
        observe_recent,
        observe_events,
        observe_object,
        observe_thread,
        read_object,
        retract_object,
        retract_thread_route,
        thread,
    ]
    # The /auth/* routes exist only when auth is configured. With auth off, there is
    # nothing to log into, and their absence keeps the surface exactly as it was.
    if auth is not None:
        handlers += [
            auth_login,
            auth_logout,
            auth_enrol_begin,
            auth_enrol_complete,
            auth_change_password,
            auth_rotate_begin,
            auth_rotate_confirm,
            mint_token,
            list_tokens,
            revoke_token,
        ]

    @asynccontextmanager
    async def scheduled_purge(_: Litestar) -> AsyncIterator[None]:
        """Run the purge loop for exactly as long as the hub is serving.

        Cancelled on shutdown, so nothing is left purging a store that is closing.
        `purge_interval_minutes = 0` means no schedule at all — the operator routes
        still work, which is what makes disabling it safe rather than a way to forget
        about retention entirely.
        """
        if purge_interval_minutes <= 0:
            api_logger.info("scheduled purge is off (purge interval 0)")
            yield
            return
        task = asyncio.create_task(
            purge_forever(house, purge_interval_minutes, purge_status)
        )
        task.add_done_callback(_complain_if_it_died)
        api_logger.info(
            "event=mailbox.purge.scheduled interval_minutes=%d retention_days=%d",
            purge_interval_minutes,
            house.mailbox.retention_days,
        )
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def stamp_the_hub_version(response: Response[Any]) -> Response[Any]:
        """Say which hub answered, on every response. See :data:`HUB_HEADER`.

        An `after_request` hook rather than something each route remembers to do: the
        whole value of this is that a client can rely on it being there, and a route
        added next month that forgot it would make the staleness notice silently wrong
        for exactly the calls that route serves.
        """
        response.headers[HUB_HEADER] = __version__
        return response

    app = Litestar(
        on_startup=[open_the_house],
        lifespan=[scheduled_purge],
        after_request=stamp_the_hub_version,
        route_handlers=handlers,
        # Published rather than merely generated. A client author working in a language
        # with no `agent-inbox` package has otherwise had to read this module, and the
        # AS2 profile — what survives a round trip, what is refused, what consumes —
        # is the part they cannot infer from the route signatures.
        openapi_config=OpenAPIConfig(
            title="agent-inbox",
            version=__version__,
            description=API_DESCRIPTION,
            path="/schema",
        ),
        exception_handlers={
            MailboxError: mailbox_error_handler,
            AuthError: auth_error_handler,
            sqlite3.OperationalError: store_busy_handler,
        },
        debug=debug,
    )
    app.state.api = api
    return app
