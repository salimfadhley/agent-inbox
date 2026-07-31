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

## Scale to zero: fine for the console, think twice for the hub

A service that suspends when idle is cheap, and for the **console** it is straightforward:
a person opening it will wait a second or two for it to wake, and can see that it is
loading.

For the **hub** the calculation is different, because the things that talk to a hub are
machines and a machine has nobody to wait for it. An agent calling `check_inbox` at the
top of its turn meets a cold start as a *failure*, not a pause — and it cannot tell "no
mail" from "could not ask" (issue #31). It has no good move from there.

**Federated delivery is retried** as of federation step 7: a message to a peer that is
asleep, restarting or briefly unreachable is queued and re-attempted with backoff for a
few minutes, so a sleeping *peer* is no longer a lost message. Note what that does and
does not cover:

- it protects the **sender**, who is another hub with a queue;
- it does nothing for an **agent client**, which has no queue and gets an error.

So the queue makes a sleeping hub survivable for federation while leaving it unpleasant
for the agents actually using it. A reasonable arrangement is the hub always-on and the
console scaled to zero.

If you do keep the hub scaled to zero, be aware the retry window is a few minutes and is
held **in memory** — it does not survive a restart, and the sender is told so.
