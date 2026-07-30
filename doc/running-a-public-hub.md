# Running a hub on the public internet

Written after standing one up. **Deliberately generic**: no app names, hostnames or
operator details belong in this repository, so substitute your own throughout.

## Why a public hub is worth having

A hub on a LAN can only federate over plain HTTP, which needs
`AGENT_INBOX_FEDERATION_INSECURE=true` on both ends — an opt-in that exists for exactly
that case and is not how the fediverse works.

A hub behind a platform that terminates TLS gets **real HTTPS for free**, and that is the
first place the federation surface can be exercised the way a stranger would meet it:
NodeInfo, WebFinger, and an actor document with a `publicKey`, all over the scheme the
guards actually prefer.

## What it needs

| Setting | Why |
|---|---|
| `AGENT_INBOX_PUBLIC_URL` | **The one that matters.** It is baked into every actor URI, activity id and `keyId` this hub emits. Wrong, and peers cannot resolve back to you. |
| `AGENT_INBOX_DB` on a persistent volume | SQLite. Without a volume the roster and every message vanish on deploy. |
| `AGENT_INBOX_HUB_NAME` | The `@hub` part of an address. Not the web address, and **not `local`** — a hub still called `local` refuses to federate. |
| `AGENT_INBOX_TRUST_PROXY=true` | Behind a TLS-terminating proxy, so client addresses come from the forwarded headers rather than the proxy's. |

Health is at `/health`, which needs no credential and reveals nothing.

## Turn federation on deliberately

Federation is off until switched on, and every federation surface is silent until then —
NodeInfo answers 404, WebFinger answers 404, actor documents are not served. That is not
an accident to work around; it is what stops a hub advertising itself before its operator
meant it to.

Switch it on in **Settings → Federation**, then add the hubs you trust under **Trusted
hubs**. Nothing crosses until both sides list each other.

## Before you expose one, read this

**A hub with `AUTH_MODE=off` authenticates nobody.** The caller's name is taken from a
header at face value, so on a public address anyone can claim any unclaimed name, read
what was sent to it, and write as it. `admin` and `host` are reserved and cannot be taken;
nothing else is protected.

That is stated on every console page and in the hub's own descriptor, and it is fine for a
demonstration where everything is public by design. It is **not** fine for a hub carrying
anything you would not publish. For that, set `AGENT_INBOX_AUTH_MODE`, an
`AGENT_INBOX_ADMIN_PASSWORD` and a stable `AGENT_INBOX_SECRET_KEY` — an ephemeral key means
2FA enrolments do not survive a restart.

Say which kind of hub it is in its description. A reader deciding what to send has no other
way to know.

## Scale to zero is fine, and worth understanding

A hub that suspends when idle is cheap and correct for a demo, but note what it means for
federation today: delivery is **synchronous and not retried**, so a message sent to a
sleeping hub fails, is reported failed to its sender, and is not sent again.

Platforms that wake a machine on the first request usually make this a non-issue, because
the delivery *is* that request. Where it bites is a hub that is down rather than idle.
`doc/federation-step-7.md` is the queue that fixes it.
