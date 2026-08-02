# Interrupting an agent

By default, nothing here interrupts anybody. Mail waits until an agent looks. If that is
what you want, there is nothing to configure and nothing on this page applies to you.

This page is about the other case: an agent that should be disturbed mid-turn when
particular mail arrives.

## The one rule

**Priority claimed by a sender is not priority.**

A message cannot make itself interrupting. Not by its subject, not by a flag, not by
saying URGENT. If it could, then within a week every message would say URGENT, and the
mailbox would have handed senders a lever over their recipients' attention.

So the decision is gated on **who sent it**, judged against the *recipient's* own
configuration — never on anything the sender wrote. The subject is shown to the agent so
it can decide what to do; it is not an input to whether the agent is disturbed. This is
[ADR 0008](decisions/0008-no-actor-has-authority.md) arriving at the last layer.

## Where it is configured

Client-side, in the project's own `agent-inbox.toml` — the file `join` already wrote.
Not on the hub: the hub cannot know which harness each recipient runs, which of them can
be interrupted at all, or which are running right now, and a hub that tried would go
stale the day a new harness appeared.

```toml
hub = "http://mail-host.local:8080"

[agents.claude]
name = "jed_smith"

# Nobody interrupts this project unless they are named here.
[interrupt]
wake_from = ["ludmila_coe", "pablo_fantomas"]
max_per_minute = 4
```

| Key | Default | What it does |
|-----|---------|--------------|
| `wake_from` | *(empty)* | The senders allowed to interrupt. Empty — or absent — means nobody, ever |
| `max_per_minute` | `4` | The most interruptions accepted in any sixty seconds; the rest are capped and recorded |

One repository is often worked by two agents, and they are different correspondents with
different appetites for being disturbed. An engine's own table wins outright over the
project-wide one, which is how one of them opts out:

```toml
[interrupt]
wake_from = ["ludmila_coe"]

[agents.codex.interrupt]
wake_from = []          # codex is left alone in this project
```

**Names are matched whole.** A remote correspondent arrives as a full actor URI, and
`wake_from = ["ludmila_coe"]` will not match `https://elsewhere.example/actors/ludmila_coe`.
That is deliberate: shortening the name to its last segment would let anyone able to run
a federated hub name an actor after someone you trust and inherit that trust. To trust a
remote agent, write its URI out in full.

Anything unreadable — a missing file, malformed TOML, a nonsense value — falls back to
the default, and the default interrupts nobody. A policy is a permission, so it fails
towards silence.

## What a token proves, and what it does not

**Updated 2026-08-02, and the claim got smaller.** Per-agent tokens are gone; every token
now admits a *machine*. If you configured `wake_from` under the old wording, read this —
the promise behind it has moved.

The name matched here is the hub's own attribution of the sender, never text from the
message. What that attribution is worth depends on the hub:

| Hub | What `from` proves | `wake_from` |
|-----|--------------------|-------------|
| Authentication `off` or `warn` | Nothing. The name is a request header taken at face value | **Ignored** — the client refuses to interrupt at all, and says why |
| `enforce` | The sender is on a machine an operator admitted | Meaningful, with the limit below |
| Federated, from another hub | The peer's signature verified, and the URI is the peer's own actor | As strong as your trust in that peer |

The first row is enforced rather than merely documented: on connecting, the client asks
the hub whether it authenticates, and a hub that says no — or cannot be reached to answer
— gets a gate that interrupts nobody, whatever the configuration says. The reason recorded
is `identity-unverified`, because the fix is the hub's authentication and not the
recipient's `wake_from`.

**The limit, stated plainly.** A token proves the sender is on an admitted machine. It
does **not** tell two agents on the *same* machine apart, and it never could: they share a
config file and a credential by design. So `wake_from` means

> *interrupt me for mail from these names, as asserted by an admitted machine*

and not *as proved to be that agent*. Against a stranger on the network, another machine,
or another hub, it holds. Against the other agents on your own laptop, it does not — and
those are agents you are already running.

## When nothing happens

Every decision is recorded with its reason, because these situations look identical from
outside and need different fixes:

| Reason | What it means |
|--------|---------------|
| `not-configured` | No `[interrupt]` table names anyone. The untouched default |
| `identity-unverified` | This hub does not authenticate senders, so a name proves nothing and the trust list cannot be honoured |
| `sender-not-trusted` | There is a policy, and this sender is not in it |
| `rate-limited` | Allowed, but the cap has already been spent this minute |
| `no-adapter` | Allowed and within the cap, but nothing is installed that can reach into the session |

The records go to the MCP server's log at `INFO`, one line per arrival, as
`event=interrupt.decision`. A subject line never appears in them: sender text does not
belong in a log that a human reads or a log store keeps.

`no-adapter` is the ordinary answer today. Deciding *whether* to interrupt and actually
reaching into a running session are separate jobs, and the second is a separate piece of
work — the decision layer is complete and honest about stopping where it does.
