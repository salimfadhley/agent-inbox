"""Sending one message to one peer, synchronously.

No queue, no retry, no delivery state. The smallest honest path from a local `send` to a
row in somebody else's store.

**Authorization is re-derived here, inside the function that makes the request**, from
configuration read at that moment. It is not passed in, and the caller does not decide.

That is deliberate, and it is the whole of the parent spec's FR-050 — the finding from
the first outside review. Authorization derived at queue time and trusted at send time
lets a peer that can stall a retry make us send after federation was disabled. There is
no queue yet, so the bug cannot exist; but Step 7 adds one, and a check living here
cannot be got between and the send. A check in the caller would have to be remembered,
which is exactly how the finding arose.
"""

import json
from dataclasses import dataclass

from agent_inbox.exceptions import MailboxError
from agent_inbox.federation import federates
from agent_inbox.keys import SigningKey
from agent_inbox.peers import (
    PeerUnreachable,
    _fetch_json,
    _permitted,
    peer_origin,
)
from agent_inbox.signatures import sign_request


class DeliveryRefused(MailboxError):
    """This hub will not send that.

    Refused before anything leaves — the distinction matters for `@local`, where making
    the request at all would leak that the address exists.
    """

    code = "delivery_refused"


class AlreadyDelivered(MailboxError):
    """The peer had this activity already and did not deliver it a second time.

    **Not an error, and not a success either.** The peer behaved correctly:
    de-duplicating on activity id is what makes a retry safe. But the message did not
    arrive *because of this call*, and recording it as `delivered` is how one message
    addressed to two recipients on one hub reported success for both while reaching one
    (issue #40).

    Raised so the receipt says what happened. A caller that treats every 2xx as a
    delivery cannot tell "arrived" from "was already here", and those differ exactly
    when it matters — when we thought we were sending something new.
    """

    code = "already_delivered"


def _candidate_origins(host: str) -> tuple[str, ...]:
    """Where to look for a hub named only by hostname.

    HTTPS first and always. Plain HTTP is tried only where this deployment has said it
    accepts unencrypted federation — the same switch, and the same reasoning, as
    fetching a peer descriptor.
    """
    from agent_inbox.peers import insecure_federation

    if "://" in host:
        return (host,)
    if insecure_federation():
        return (f"https://{host}", f"http://{host}")
    return (f"https://{host}",)


@dataclass(frozen=True, slots=True)
class RemoteRecipient:
    """Where a remote actor's mail goes, once resolved."""

    handle: str
    actor_uri: str
    inbox: str

    @property
    def origin(self) -> str:
        return peer_origin(self.actor_uri)


def resolve(
    handle: str, signing: tuple[SigningKey, str] | None = None
) -> RemoteRecipient:
    """Turn `alice@beta.example` into an actor URI and an inbox.

    Reuses Step 3's fetching, and therefore its bounds, its refusal to follow redirects,
    and its origin checks. A resolution path of its own would be a second place for a
    hostile peer to be trusted.
    """
    name, _, host = handle.strip().lstrip("@").partition("@")
    if not name or not host:
        raise DeliveryRefused(
            f"{handle!r} is not a remote address — try name@hub.example"
        )

    # A handle carries no scheme, and the fediverse's answer is "https, always". That
    # stays the default — but a deployment that opted into insecure transport has hubs
    # it can only reach over HTTP, and refusing to try would make the opt-in useless
    # for the case it exists for. HTTPS is still attempted first, so a peer that speaks
    # both is reached securely.
    attempts: list[str] = []
    finger: dict[str, object] | None = None
    base = ""
    for candidate in _candidate_origins(host):
        try:
            base = _permitted(candidate)
            finger = _fetch_json(
                f"{base}/.well-known/webfinger?resource=acct:{name}@{host}", signing
            )
            break
        except (PeerUnreachable, DeliveryRefused) as failure:
            attempts.append(f"{candidate}: {failure}")
    if finger is None:
        raise DeliveryRefused(
            f"could not resolve {name}@{host} — " + "; ".join(attempts)
        )
    links = finger.get("links")
    actor_uri = None
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and link.get("rel") == "self":
                target = link.get("href")
                if isinstance(target, str):
                    actor_uri = target
    if actor_uri is None:
        raise DeliveryRefused(f"{host} does not know {name!r}")
    if peer_origin(actor_uri) != peer_origin(base):
        # A hub answering for somebody else's actor is either misconfigured or trying
        # to make us deliver to a third party.
        raise DeliveryRefused(f"{host} pointed at an actor on another hub")

    document = _fetch_json(actor_uri, signing)
    inbox = document.get("inbox")
    if not isinstance(inbox, str) or peer_origin(inbox) != peer_origin(base):
        raise DeliveryRefused(f"{host} published no usable inbox for {name!r}")

    return RemoteRecipient(handle=f"{name}@{host}", actor_uri=actor_uri, inbox=inbox)


def deliver(
    recipient: RemoteRecipient,
    activity: dict[str, object],
    *,
    key: SigningKey,
    key_id: str,
    settings: dict[str, str],
    peers: dict[str, str],
) -> None:
    """Sign and POST one activity. Authorization is decided **here**.

    ``settings`` and ``peers`` are read by the caller immediately before this call and
    passed straight in, so the decision is made against what is true now. When a queue
    arrives it must re-read them and call this again — never cache a decision.
    """
    if not federates(settings):
        raise DeliveryRefused("this hub does not federate")
    if recipient.origin not in peers:
        raise DeliveryRefused(
            f"{recipient.origin} is not a peer of this hub — add it before sending"
        )

    body = json.dumps(activity).encode()
    headers = sign_request(key, key_id, "POST", recipient.inbox, body=body)

    import urllib.error
    import urllib.request

    request = urllib.request.Request(  # noqa: S310 — origin checked in `resolve`
        recipient.inbox,
        data=body,
        method="POST",
        headers={**headers, "Content-Type": "application/activity+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            answered = response.read(64 * 1024)
    except urllib.error.HTTPError as refused:
        detail = ""
        try:
            detail = (json.loads(refused.read() or b"{}") or {}).get("detail", "")
        except ValueError:
            pass
        # Carry the status: the retry queue must tell "they said no" from "they did not
        # answer". A 4xx is a considered rejection and retrying it is pointless.
        raise PeerUnreachable(
            f"{recipient.handle} refused it ({refused.code})"
            + (f": {detail}" if detail else ""),
            status=refused.code,
        ) from refused
    except OSError as unreachable:
        raise PeerUnreachable(
            f"could not reach {recipient.handle} — {unreachable}"
        ) from unreachable

    # **A 200 is not the same as a delivery**, and this body was previously read and
    # discarded. A peer that has seen this activity id before answers
    # `{"delivered": false, "reason": "already seen"}` — which is honest, and which we
    # were recording as success. That is how one message to two recipients on one hub
    # came to report `delivered` twice while reaching one of them (issue #40).
    #
    # Per-recipient activity ids mean a *fresh* send can no longer collide with itself,
    # so reaching this now means a genuine repeat: a retry of something already
    # delivered, which is a no-op rather than a loss. It is still not a delivery, and
    # saying so is what stops the next collision being silent.
    if _said_already_seen(answered):
        raise AlreadyDelivered(
            f"{recipient.handle}'s hub has seen this activity before — "
            "it was not delivered again"
        )


def _said_already_seen(body: bytes) -> bool:
    """Whether the peer told us it had this already. Malformed bodies mean no.

    A peer that answers something we cannot parse has still answered 2xx, and inventing
    a failure from an unreadable body would turn a working delivery into a false alarm.
    """
    try:
        answer = json.loads(body or b"{}")
    except ValueError:
        return False
    return isinstance(answer, dict) and answer.get("delivered") is False
