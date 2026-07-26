"""The hub's one machine interface.

ActivityStreams on the wire, ActivityPub's route shape, served over a
:class:`~agent_mailbox.house.House` so that house rules apply to everything reachable
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

from __future__ import annotations

import logging
from typing import Any

import msgspec
from litestar import Litestar, MediaType, Request, Response, delete, get, post, put
from litestar.connection import ASGIConnection
from litestar.datastructures import Cookie
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.handlers.base import BaseRouteHandler

from agent_mailbox import __version__
from agent_mailbox.auth.exceptions import AuthError, NotAuthenticated, TooManyAttempts
from agent_mailbox.auth.records import SHARED_ACTOR
from agent_mailbox.auth.service import AuthService
from agent_mailbox.auth.throttle import LoginThrottle
from agent_mailbox.errors import auth_error_handler, mailbox_error_handler
from agent_mailbox.exceptions import MailboxError
from agent_mailbox.house import House
from agent_mailbox.wire import (
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
SESSION_COOKIE = "agent_mailbox_session"

#: ActivityStreams asks for this; plain JSON clients are not refused for lacking it.
ACTIVITY_JSON = "application/activity+json"

api_logger = logging.getLogger("agent_mailbox.api")


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


class Api:
    """Routes over a house. Holds the house and the renderer; decides nothing."""

    def __init__(
        self, house: House, public_url: str, *, authenticated: bool = False
    ) -> None:
        self.house = house
        self.wire = Renderer(public_url)
        #: True only under enforce — the hub reports its own posture honestly.
        self.authenticated = authenticated

    # -- hub ---------------------------------------------------------------

    async def hub(self) -> dict[str, Any]:
        mailbox = self.house.mailbox
        note = (
            "This hub requires authentication: agents present a device token as a "
            "Bearer credential, humans log in at the console."
            if self.authenticated
            else (
                "This hub does not authenticate. The caller's name is taken from the "
                f"{IDENTITY_HEADER} header at face value. Suitable for a trusted "
                "network only."
            )
        )
        return {
            "@context": "https://www.w3.org/ns/activitystreams",
            "type": "Service",
            "name": mailbox.hub_name,
            "version": __version__,
            "id": self.wire.base,
            # Said out loud, either way — a hub's posture should never be a surprise.
            "authenticated": self.authenticated,
            "note": note,
            "policies": [getattr(p, "name", "?") for p in self.house.policies],
            "federates": False,
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

    async def directory(self) -> Collection:
        actors = await self.house.directory()
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
            return self.wire.note(replied)

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
        return self.wire.note(sent)

    async def inbox(self, name: str, caller: str) -> Collection:
        owns(name, caller, self.wire)
        waiting = await self.house.peek(caller)
        return self.wire.collection([self.wire.note(m) for m in waiting])

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
        return await self.house.survey(since=since)

    async def observe_mailbox(self, name: str) -> Collection:
        items = await self.house.observe_mailbox(self.wire.name_from(name))
        return self.wire.collection([self.wire.note(m) for m in items])

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

    async def federation_inbox(self, name: str) -> Response:
        return Response(
            status_code=501,
            content={
                "code": "not_implemented",
                "detail": (
                    "This hub does not federate. Delivery from other mailboxes is "
                    "mission 0024 (Pen Pals) and mission 0025 (fediverse profile)."
                ),
            },
        )


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


def build_api(
    house: House,
    public_url: str,
    *,
    debug: bool = False,
    auth: AuthService | None = None,
    auth_mode: str = "off",
    throttle: LoginThrottle | None = None,
    trust_proxy: bool = False,
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
    api = Api(house, public_url, authenticated=enforcing)

    async def resolve_verified_caller(conn: ASGIConnection) -> str | None:
        """A caller proven by a credential — a device token or a full session — or None.

        Raises :class:`TokenRevoked` for a presented-but-revoked token, which the error
        handler turns into a 401; an *absent* credential is ``None``, not an
        error, so the mode can decide what to do about it.
        """
        if auth is None or auth_mode == "off":
            return None
        header = conn.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            actor = await auth.resolve_token(header[7:].strip())
            if actor:
                return actor
        sid = conn.cookies.get(SESSION_COOKIE)
        if sid:
            session = await auth.resolve_session(sid)
            if session is not None and not session.limited:
                return session.username
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
                "this hub requires authentication — present a device token as "
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
        """A human operator's username, for the token-admin routes.

        Under ``off`` there is no auth, so a placeholder operator is returned (dev/LAN).
        Otherwise a full (non-limited) session is required — minting or revoking
        a device token is an operator action.
        """
        if auth is None or auth_mode == "off":
            return "operator"
        sid = request.cookies.get(SESSION_COOKIE)
        session = await auth.resolve_session(sid) if sid else None
        if session is not None and not session.limited:
            return session.username
        raise NotAuthenticated("log in as an operator to manage device tokens")

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

        known = await house.mailbox.whois(claimed) if claimed else None

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
            },
            "you": {
                "claimed": claimed,
                "known": known is not None,
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
    async def directory() -> Collection:
        return await api.directory()

    @get("/actors/{name:str}", guards=[guard_enforce])
    async def actor(name: str) -> Actor:
        return await api.actor(name)

    @put("/actors/{name:str}", dependencies={"caller": Provide(provide_caller)})
    async def update_profile(name: str, data: dict[str, Any], caller: str) -> Actor:
        return await api.update_profile(name, data, caller)

    @get("/actors/{name:str}/inbox", dependencies={"caller": Provide(provide_caller)})
    async def inbox(name: str, caller: str) -> Collection:
        return await api.inbox(name, caller)

    @post("/actors/{name:str}/inbox")
    async def federation_inbox(name: str) -> Response:
        return await api.federation_inbox(name)

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
    @get("/observe/stats", guards=[guard_enforce])
    async def observe_stats(since: str = "") -> dict[str, Any]:
        return await api.survey(since)

    @get("/observe/mailbox/{name:str}", guards=[guard_enforce])
    async def observe_mailbox(name: str) -> Collection:
        return await api.observe_mailbox(name)

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
        "/auth/agents/{name:str}/tokens",
        status_code=201,
        dependencies={"operator": Provide(provide_operator)},
    )
    async def mint_token(
        name: str, data: dict[str, Any], operator: str
    ) -> dict[str, str]:
        assert auth is not None
        minted = await auth.mint_token(name, label=str(data.get("label", "")))
        return {"id": minted.id, "token": minted.secret, "actor": minted.actor}

    @get(
        "/auth/agents/{name:str}/tokens",
        dependencies={"operator": Provide(provide_operator)},
    )
    async def list_tokens(name: str, operator: str) -> dict[str, Any]:
        assert auth is not None
        tokens = await auth.list_tokens(name)
        return {
            "items": [
                {
                    "id": t.id,
                    "label": t.label,
                    "created": t.created,
                    "lastUsed": t.last_used,
                    "revoked": t.revoked,
                }
                for t in tokens
            ]
        }

    @delete(
        "/auth/agents/{name:str}/tokens/{token_id:str}",
        status_code=204,
        dependencies={"operator": Provide(provide_operator)},
    )
    async def revoke_token(name: str, token_id: str, operator: str) -> None:
        assert auth is not None
        await auth.revoke_token(token_id)

    async def open_the_house(_: Litestar) -> None:
        """Establish standing invariants once, at startup.

        This is where `admin` and `host` come into being. Without it the hub would
        serve happily and quietly have nowhere to report a fault to.
        """
        await house.open()

    handlers = [
        hub,
        health,
        doctor,
        join,
        directory,
        actor,
        update_profile,
        inbox,
        federation_inbox,
        outbox,
        view_object,
        observe_stats,
        observe_mailbox,
        observe_object,
        observe_thread,
        read_object,
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

    app = Litestar(
        on_startup=[open_the_house],
        route_handlers=handlers,
        exception_handlers={
            MailboxError: mailbox_error_handler,
            AuthError: auth_error_handler,
        },
        debug=debug,
    )
    app.state.api = api
    return app
