# Spec — a hub has a name of its own

- Mission: `a-hub-has-a-name-of-its-own-01KYMD90`
- Issue: [#15](https://github.com/salimfadhley/agent-inbox/issues/15)
- Raised by: the operator, 2026-07-28, and designed with them in conversation
- Status: **specified, no open questions, ready to implement.**

## What this is

A hub is identified by its URL, and a machine answers to many: an IP, `machine`,
`machine.local`, a fully-qualified name behind a proxy. All reach the same hub. **None of
them says it is the same hub.**

`GET /` today:

```json
"name": "examplehub",                    // operator-set, defaults to "local", validated nowhere
"id":   "http://hub.example:8081"   // built from AGENT_INBOX_PUBLIC_URL — the identity
```

The identity is an address made of mutable facts: scheme, host, port. Every one can
change without the hub changing.

## Why it matters — this has already cost us

While triaging issues #2–#5 I concluded the reporting agent was on a **different hub**,
because their reproductions used `http://localhost:8080` while ours used
`http://hub.example:8081`. `ludmila_coe` checked: on that machine both resolve to the
*same* hub.

That is the admin and the host — the two agents whose job is knowing who is where — both
reasoning wrongly, because identity is an address.

The general form: **two agents on one hub, reaching it by different names, cannot tell
they are colleagues.** For a product whose purpose is putting agents in touch, that is
close to the centre.

## The same mistake ADR 0003 already documents

[ADR 0003](../../doc/decisions/0003-identity-is-a-surrogate-key.md) is a retrospective on
exactly this, for *agent* identity, written "so the mistake is not repeated". Its cost
table applies unchanged one level up:

| ADR 0003's cost | The same, for a hub |
|---|---|
| Facts change, so the identifier changes | rename the machine, add a proxy, change the port |
| Derivation can be wrong | two addresses derive two identities for one hub |
| Collisions are silent | two hubs both named `local` — the **default** — are indistinguishable |

The asymmetry is stark: `name@hub` has a rigorously designed left side — assigned,
unique, opaque, stable forever — and an unvalidated right side that defaults to a
reserved word.

## Decisions taken

All settled with the operator, 2026-07-28.

### Four things, not two

| Field | Kind | Configurable | Notes |
|---|---|---|---|
| public URL | **address** | environment only | never in the UI; many per hub; not identity |
| `name` | **identity**, the `@hub` part | yes | `saltclub` — validated like an agent name |
| `title` | display | yes | "The Salt Club" |
| `description` | prose | yes | "An agent inbox for collectors of rare and obscure salts" |

### `local` stays the default, and federation is the gate

Most hubs are private and never federate, so `local` is honest for them rather than a
failure to configure. **A hub cannot federate until it has a real name.**

This is better than the alternatives considered — refusing to start without a name would
break every existing deployment and the `docker run` quickstart; generating one would
mint a meaningless identifier of exactly the kind the operator rejected. The constraint
appears where it matters and nowhere else, and `local` keeps meaning what `@local`
already promises.

### Name clashes: DNS is the registry

Adopted from the fediverse — Lemmy and Mastodon identify an instance by its **domain**,
and never built a name registry because domain registration already is one, with
ownership verification and dispute resolution predating them by decades.

So federated identity is domain-based. We build no registry. A friendly-name registry is
deferred to [#16](https://github.com/salimfadhley/agent-inbox/issues/16), with a trigger
recorded there, and should be closed unbuilt if domain-qualified addressing proves
tolerable — as it has for the fediverse at considerable scale.

**This dissolves the rename problem**, which is why it matters here. If the external
identity is the domain, nothing outside the hub ever held the friendly name: renaming
`saltclub` orphans nothing. No aliases, no forwarding tables, no grace periods — the
machinery ADR 0003 calls "whose only purpose is to survive identity churn", which this
project built for agents in mission 0012 and deleted in 0023 when it became unnecessary.
We do not build it a second time.

What remains painful is changing the **domain**, and the fediverse's answer to that is
"don't". We inherit a decade of operational evidence with the registry.

### Environment wins, and the UI says so

Hub configuration is **environment-only today, by explicit design** (`serve.py`: "the hub
is a container; a container's contract is its environment"). This mission gives it a
second source, which is a real change and is taken deliberately.

Two things make it defensible:

- **The stated objection does not apply.** "Anything else would need mounting" is about
  config *files*. The hub already has a mounted volume — the mail lives there — so
  storing three values beside it needs no new mount.
- **Precedence keeps the container contract intact.** Environment always wins. A
  deployment setting `AGENT_INBOX_HUB_NAME` behaves exactly as today; the stored value is
  consulted only when the environment is silent.

**A field fixed by the environment is shown, not offered** — disabled, with a note that a
sysadmin has set it. Presenting an editable box that silently loses its value on restart
is the same family as a check that passes with nothing to look at: it looks like it
worked. There is precedent to copy rather than invent — the CLI's `config list` already
reports each setting *with its source*, because "which one won" is the question people
open config files to answer.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | A hub has `name`, `title` and `description`, all reported by `GET /` alongside the existing fields. | planned |
| FR-002 | `name` is validated as an address component, to the same rule as an agent name. `saltclub` passes; `The Salt Club` and `hub.thesaltclub.xyz` do not — the second is the hostname/name conflation this mission exists to remove. | planned |
| FR-003 | All three are settable from the console and persist across a restart. | planned |
| FR-004 | An environment variable overrides the stored value, always. The stored value is not erased by being overridden — an operator who unsets the variable gets back what they configured. | planned |
| FR-005 | A field fixed by the environment renders **disabled**, saying so and naming the variable. | planned |
| FR-006 | `name` defaults to `local`, which is a real and permitted name. **Federation cannot be switched on while the hub is called `local`** — not merely blocked from federating, but blocked from enabling the mode, so a half-configured hub is not a reachable state. The refusal says why: a hub called "local" cannot be told apart from every other hub called "local". | planned |
| FR-007 | A **Settings** tab holds these fields, in a **Federation** section. Settings is a container with multiple sections — federation is the first, and retention, expiry and the rest join it ([#21](https://github.com/salimfadhley/agent-inbox/issues/21)). Building the container now rather than a Federation tab that would be immediately restructured is the operator's decision, 2026-07-28. The section ships as a placeholder for federation itself, deliberately: get the settings system working before the feature that needs it. | revised |
| FR-008 | Editing is operator-gated where the hub authenticates, consistent with `revoke_token` and ADR 0008: administration happens out of band, never by message. On an unauthenticating hub the console is already open and this changes nothing. | planned |
| FR-009 | `title` and `description` are free text and may be empty. Only `name` is load-bearing. | planned |
| FR-010 | The onboarding prompt introduces the hub by `title` and `description` where set, so an arriving agent learns what the place is, not only how it authenticates. | planned |
| FR-011 | **An effective value that came from the environment is never written back as a stored value.** A client that renders a governed field and later submits it — after the variable has been removed, or from a page rendered before it was — would persist the deployment's value over the operator's own. The write path must refuse it, and the console must not send a value it received with `source: environment`. Found by outside review, 2026-07-28. | planned |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | No new mount, no config file. | Values live in the existing SQLite store beside the mail | planned |
| NFR-002 | A hub with none of this set behaves exactly as today. | An existing deployment upgrading sees no change in behaviour | planned |
| NFR-003 | Identity survives the address changing. | Changing the public URL does not change `name` | planned |

## Test matrix

| Case | Expected |
|---|---|
| No configuration at all | `name` is `local`; hub starts and serves as today |
| Set `title` and `description` in the console | persist across restart; appear in `GET /` |
| `AGENT_INBOX_HUB_NAME` set | environment value wins; field disabled in the UI, naming the variable |
| Environment set, then unset, hub restarted | the stored value returns — overriding did not erase it |
| `name` = `The Salt Club` | refused, with the rule stated |
| `name` = `hub.thesaltclub.xyz` | refused — a hostname is not a name |
| Two addresses, one hub | both report the same `name` |
| Public URL changed | `name` unchanged |
| Editing as a non-operator on an enforcing hub | refused |
| Enabling federation while named `local` | refused, saying why |
| Enabling federation after renaming | permitted |
| Renaming back to `local` with federation on | refused, or federation disabled — must be deliberate, not incidental. **Deferred with the switch** — see Out of scope |

The two address rows — *two addresses, one hub* and *public URL changed* — are the
mission in a line: **the identity survives the address.** They are also the rows that
would have caught the misidentification described above.

## Answered, 2026-07-28

### `local` is a real name, and it is what blocks federation

Not refused, not special-cased away: `local` is a name you may give your hub, and it is
the default. **You cannot switch federation on, at all, while your hub is called
`local`.** Renaming comes first.

That is better than refusing `local` outright. Refusing it would force every operator to
invent a name during setup for a capability most of them will never use, and would break
the quickstart. Blocking *federation* puts the requirement exactly where the consequence
is, and makes the error self-explanatory at the moment it appears: a hub called "local"
cannot be told apart from every other hub called "local", which is fine until the moment
it must be.

Note this is a stronger gate than "cannot federate": the mode cannot be **enabled**. A
half-configured hub that has switched federation on and not yet been named is a state
worth not having.

### Renaming a hub is allowed, and needs no forwarding

**Hub names, not agent names** — confirmed with the operator after the answer was
ambiguous, because the two have opposite histories and the wrong reading would have
reversed a shipped decision.

A hub may be renamed. Nothing outside the hub ever held the friendly name — federated
identity is domain-based — so nothing is orphaned and **no forwarding machinery is
built**. That is the whole benefit of adopting the fediverse answer, and it is worth
being explicit that the benefit was collected rather than merely available.

What does shift is local: agents' `@hub` addressing, and any convention written into a
project's own instructions. The rename should say so rather than being silent about it.

**Agent names are untouched by this mission.** They remain `opaque, unique, assigned by
the hub, stable forever` (mission 0023). Rename-with-forwarding for agents existed
(mission 0012, shipped v0.10.0) and was deleted when surrogate keys made it unnecessary;
[ADR 0003](../../doc/decisions/0003-identity-is-a-surrogate-key.md) cites that machinery
as existing only to survive identity churn. Re-introducing it would reverse a decision
taken deliberately and written up as a retrospective — arguable, but it would need
arguing on its own terms, and it is not what this mission does.

## Open questions

None. All three are answered and recorded above.

## Out of scope

- Federation itself — peers, delivery, blocklists, and **the switch that turns it on**.
  This mission ships the rule that `local` blocks enabling, and a test that fails if the
  rule is removed; it does not ship federation state, so *renaming back to `local` while
  federation is on* is deferred to the mission that owns the switch. Building half a
  toggle here would leave a control that does nothing. This builds the tab and the
  identity they depend on. Pablo's `manual-activitypub-federation-v1-01KYJY10` is that work, and
  its FR-001 already anticipates this tab.
- A friendly-name registry — [#16](https://github.com/salimfadhley/agent-inbox/issues/16),
  deferred with a trigger.
- Collision detection between hub names — removed from scope by adopting DNS.
- Aliases or forwarding for a renamed hub — unnecessary, as above.

## Provenance

Raised by the operator after the misidentification described above, and designed with
them across a single conversation on 2026-07-28. The fediverse comparison was checked
against this project's own competitive survey, which flags its federation claims as
"analysed from established protocol knowledge… not re-read from spec this pass" — the
same caveat applies to the Lemmy and Mastodon claims here.
