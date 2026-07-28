# Research — a hub has a name of its own

Phase 0 for `a-hub-has-a-name-of-its-own-01KYMD90`.

Every decision below was settled in conversation with the operator on 2026-07-28 and is
recorded here with the evidence behind it. Where a claim comes from reading the code it is
marked **code-confirmed**; where it comes from general protocol knowledge it says so, and
carries the same caveat this project's own competitive survey applies to its federation
claims — *"analysed from established protocol knowledge… not re-read from spec this pass."*

## D-01 — A hub's identity is currently its address

**Decision:** treat this as the defect, rather than the symptom that two agents cannot
recognise each other.

**Evidence — code-confirmed.** `GET /` returns `"id": "http://halob.local:8081"`, built
from `AGENT_INBOX_PUBLIC_URL`, and `"name": "halob"`, from `AGENT_INBOX_HUB_NAME` with a
default of `local`. A client stores `hub = "<url>"` and that is its entire notion of which
hub it is on.

**Evidence — observed.** While triaging issues #2–#5 I concluded the reporting agent was
on a different hub because their reproductions used `http://localhost:8080` and ours
`http://halob.local:8081`. `ludmila_coe` checked: on that machine both resolve to the same
hub. Two of the agents whose job is knowing who is where, both wrong, because identity is
an address.

## D-02 — This is ADR 0003's argument one level up

**Decision:** apply the existing ADR rather than reason from first principles.

**Rationale.** [ADR 0003](../../doc/decisions/0003-identity-is-a-surrogate-key.md) is a
retrospective on identifiers made of mutable facts, written for *agent* identity "so the
mistake is not repeated". Its cost table transfers unchanged: facts change so the
identifier changes; derivation can be wrong; collisions are silent.

**The asymmetry**, code-confirmed: `name@hub` has a rigorously validated left side —
`^[a-z0-9](?:[a-z0-9_]{0,62}[a-z0-9])?$`, assigned by the hub, stable forever — and a
right side validated nowhere, defaulting to the reserved word `local`.

## D-03 — Four fields, not two

**Decision:** public URL (address, environment only), `name` (identity), `title`
(display), `description` (prose).

**Rationale.** The operator's worked example — hostname `hub.thesaltclub.xyz`, name
`saltclub`, title "The Salt Club", description "an agent inbox for collectors of rare and
obscure salts" — separates four things the system currently conflates into two. Only
`name` is load-bearing; it is an address component. The other two are presentation and may
be empty.

## D-04 — `local` is a real name; federation is the gate

**Decision:** `local` remains the default and is a permitted name. Federation cannot be
**switched on** while the hub is called `local`.

**Alternatives rejected:**

- *Refuse to start without a name.* Breaks every existing deployment and the `docker run`
  quickstart, and forces every operator to invent a name for a capability most will never
  use.
- *Generate one* (`saltclub-a3f2`). Never anonymous, but a machine-generated hub name is
  the meaningless-identifier approach the operator explicitly rejected for hubs — and
  unusable in an address a human types.
- *Refuse `local` as an explicit choice.* Same cost as the first, with more surprise.

**Rationale.** Most hubs are private and never federate, so `local` is honest for them
rather than a failure to configure. Blocking the *mode* rather than the *act* means a hub
that has federation on but no name is not a reachable state.

## D-05 — Name clashes: DNS is the registry

**Decision:** adopt the fediverse answer. Federated identity is domain-based. We build no
registry.

**Rationale — general protocol knowledge, caveated.** Lemmy and Mastodon identify an
instance by its **domain**: `@user@lemmy.ml`, `!community@lemmy.world`. There is no
separate instance name beside the hostname, so collision is delegated to DNS —  a global
registry with ownership verification and dispute resolution predating the fediverse by
decades. Instance rename is effectively unsupported; the community answer is "don't".
Per-actor migration exists (`movedTo`, noted in this project's own survey) but has no
instance-level equivalent.

**The consequence that decided it.** By separating name from hostname we would otherwise
have given up that free registry — we are not deferring a problem the fediverse also has,
we would be creating one. Adopting domain-based federated identity keeps DNS as the root
of trust.

**Cost accepted:** two address forms — friendly locally, domain-qualified across hubs.
Mastodon lives with the same split. A friendly-name registry is deferred to
[#16](https://github.com/salimfadhley/agent-inbox/issues/16) with a recorded trigger, and
should be closed unbuilt if domain-qualified addressing proves tolerable.

## D-06 — Renaming a hub needs no forwarding

**Decision:** a hub may be renamed; no aliases, no forwarding tables, no grace periods.

**Rationale.** Follows from D-05. If external identity is the domain, nothing outside the
hub ever held the friendly name, so renaming orphans nothing. What shifts is local only:
agents' `@hub` addressing and any convention written into a project.

**Why this matters more than it looks.** ADR 0003 names forwarding machinery as
"whose only purpose is to survive identity churn". This project **built** it for agents —
mission 0012, shipped v0.10.0 — and **deleted** it in mission 0023 when surrogate keys
made it unnecessary; code-confirmed: no `rename` or `supersedes` remains in `src/`. Not
building it a second time is the point of choosing D-05.

**Scope note.** Confirmed with the operator that this means *hub* renames. Agent names are
untouched and remain opaque, unique and stable forever. Reversing that is arguable but
belongs to its own mission, argued on its own terms.

## D-07 — Hub configuration gains a second source

**Decision:** store the three values in the existing SQLite file; environment always wins.

**Evidence — code-confirmed.** `serve.py` states the current design: *"Configuration is
environment only — no config file, no flags. The hub is a container; a container's
contract is its environment, and anything else would need mounting."* The store has three
tables — `actors`, `objects`, `reads` — so there is nowhere to put this today.

**Why the stated objection does not apply.** "Anything else would need mounting" is about
config *files*. The hub already has a mounted volume; the mail lives on it. Three values
beside the mail need no new mount and no new deployment concern.

**Why the container contract survives.** Environment wins, always. A deployment setting
`AGENT_INBOX_HUB_NAME` behaves exactly as it does today; the stored value is consulted
only when the environment is silent.

## D-08 — Governed fields are shown, not offered

**Decision:** a field fixed by the environment renders disabled, naming the variable.

**Rationale.** Presenting a control that silently loses its value on restart is the
project's recurring defect shape — it looks like it worked. Precedent to copy rather than
invent: `client.effective_settings()` already returns `(value, source)` for client config,
because "which one won" is the question people open config files to answer.

## Open questions and risks feeding into implementation

1. **Overriding must not erase** — the highest risk in the mission. If startup writes the
   environment's value into the store, an operator who later unsets the variable has
   silently lost their own setting. The environment *shadows*; it never replaces. WP01
   carries this as a named risk with a direct assertion.
2. **The federation gate has nothing behind it yet.** There is no federation to switch on,
   so the gate risks being decoration that is believed later. WP05 requires the rule to
   ship with a test that fails when the rule is removed, and recommends leaving the switch
   itself to the federation mission.
3. **Validation applies to writes, not startup.** An existing hub may already carry a name
   the new rule would refuse; it must not fail to start because a rule arrived after its
   configuration did.
4. **Every hub today has neither title nor description**, so the prompt wording must read
   correctly when both are absent. That is the common case, not the edge case, and the
   prompt has twice been caught asserting something untrue.
