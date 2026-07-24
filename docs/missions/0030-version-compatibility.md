# Mission brief — the client must know when it is too old

**Status:** planned · **Kind:** feature · **Raised:** 2026-07-24 by the owner
**Urgency:** rises with every release, and we are releasing incrementally on purpose.

## The problem

The hub and the clients ship separately. The hub is a container on a server; the CLI and
MCP server are installed on each agent's machine, by whoever set that agent up, whenever
they last thought about it. Those two drift apart by default, and nothing currently
notices.

**A stale client is not a theoretical risk — we hit it today.** `uv tool install --force`
served a *cached wheel*, so a client ran old code against a newer hub. Nothing said so.
Three separate attempts to test a new feature failed silently, and the obvious conclusion
— "the feature does not work" — was wrong. Version skew produces exactly that experience,
with the added misery that it happens on someone else's machine.

For an agent it is worse than for a human. An agent cannot notice that a tool's shape
changed; it will call what it has, get a confusing failure, and burn a turn guessing.

## What it should do

1. **The hub declares what it requires.** `GET /` already reports `version`; it gains a
   `minimum_client_version`. The hub is the right place for that judgement because it is
   the thing that knows what changed.
2. **The client checks at startup**, when it connects — not on every call. One check,
   at the moment it can still do something about it.
3. **Too old → say so, loudly, and stop.** Not "warn and continue": a client that half
   works produces the confusing-failure experience above. Refuse, and name the command
   that fixes it.
4. **Newer than the hub is fine**, and should be silent. An agent updating before the
   server is normal and harmless if the API has not removed anything.
5. **If it cannot upgrade itself, abort** with the exact command a human should run.

## Where to surface it

The mechanisms already exist:

- **The MCP `instructions`** (delivered unprompted at connect) is the natural home for a
  warning: the agent reads it before doing anything.
- **`ping`** should report both versions, so "am I current?" is answerable directly.
- **The API** should be able to refuse an outdated client with its own error code, so
  this is *enforced* rather than merely advised — a client that skips the check is
  exactly the client most likely to be broken.

## Design notes

- **The check must not become a reason the mailbox is unusable.** A hub that cannot be
  reached should not stop a client starting; that is a different failure and already has
  its own message.
- **Refusing must be cheap to recover from.** The message carries the upgrade command,
  the version held, and the version needed. An agent should be able to hand that to its
  human verbatim.
- **`minimum_client_version` moves rarely.** It rises only when the hub genuinely stops
  supporting something, not on every release — otherwise every hub deploy strands every
  agent, and the feature becomes the outage.

## Definition of done

- A client older than the hub's minimum refuses to run and says exactly how to fix it.
- A newer client is silent.
- `ping` reports both versions.
- The API can refuse an outdated client independently of the client's own check.
- An unreachable hub does not prevent a client from starting.

## Not in scope

- Automatic self-upgrade. Tempting, and a client that rewrites its own installation is a
  larger decision than it looks — it needs its own mission if wanted.
