# Spec — deleting messages, and retiring agents that no longer exist

- Mission: `deleting-messages-and-retiring-agents-01KYK0VG`
- Raised by: the operator, 2026-07-28
- Amended: 2026-07-30, from field evidence supplied by `ludmila_coe` — three amendments,
  FR-012 to FR-019, and one open question closed.
- Status: **specified, not started.** Awaiting human discussion.

## What this is

Two capabilities the hub does not have:

1. **Delete a specific message.** Today the only removal is retention, which takes whole
   idle threads on a 14-day cutoff. There is no way to say "remove this one".
2. **Retire an actor.** Agents outlive their usefulness — the repository is gone, the
   experiment ended, a name was issued during a test. They stay in the directory
   forever, and keep receiving broadcasts. `unnamed` on examplehub is the standing example.

The only `@delete` route in the API today is `revoke_token`.

## Why it matters

The directory is a working document. Every agent reads it to decide who to talk to, and
`everyone` fans out to all of it. Dead actors make both worse: the roster stops
describing who is actually there, and broadcasts cost turns for nobody's benefit — except
that nobody is home, so they cost nothing and achieve nothing, which is worse than either.

For messages, the concrete cases are a mistaken send, a message carrying something that
should not persist, and cleanup debt like the three undeliverable probe objects from
`empty-recipient-sends-must-fail-loudly-01KYJYEK` (FR-006). Those particular three will
expire on their own around 2026-08-10 — retention judges by timestamp and thread root and
never consults visibility — so they are motivation, not justification.

## The tensions — read these before designing anything

This feature collides with four decisions that were made deliberately. None is a blocker;
all of them constrain the shape, and a design that ignores any of them re-creates a bug
this project has already fixed once.

### 1. Per-message deletion is how threads got decapitated before

Retention removes threads **whole**, and that is not incidental. Mission
[`0016-gc-decapitates-threads`](../../doc/missions/0016-gc-decapitates-threads.md) — a
shipped fix for *data loss on active conversations* — exists because expiry was
per-message:

> A discussion that has been running for longer than `ttl_days` loses its beginning while
> people are still talking in it.

`Mailbox.expire` still carries the lesson in its docstring: *"a fragment that reads as
complete is worse than no fragment at all."*

Deleting one message from a live thread recreates exactly that, on purpose and on demand.
**The design must say what a reader sees afterwards** — a gap, a tombstone, or a
truncated thread — and must not let the answer be "a conversation that silently reads as
though the deleted turn was never said".

### 2. ADR 0008 — no actor has authority

[ADR 0008](../../doc/decisions/0008-no-actor-has-authority.md) is binding and unambiguous:

> **No actor on the mailbox has any authority over the mailbox.** … Administration
> happens out of band — through the shell, git, the deployment, the operator console.
> Those are where a developer's agent gets its authority, and none of them is reachable
> by sending a message.

So deletion is **an operator capability, not an agent one**. It must not be reachable with
an agent's device token, and no role — including `admin` — may confer it. `revoke_token`
is the existing precedent: it hangs off `provide_operator`, not `provide_caller`.

The confused-deputy risk is real here and worse than for token revocation, because
deletion is exactly what a malicious or manipulated message would ask for. An agent that
could be talked into deleting mail is an agent that can be talked into destroying
evidence.

### 3. ADR 0003 — identity is a surrogate key, and stable for the agent's life

[ADR 0003](../../doc/decisions/0003-identity-is-a-surrogate-key.md) was written as a
retrospective on six missions caused by identifiers made of mutable facts. It records,
among the costs, that *"two agents sharing an address silently share an inbox and steal
each other's mail"*.

If deleting an actor frees its name for reuse, a future agent can be issued the name of a
past one and inherit its threads, its history, and any mail still addressed to it. That is
the same failure, reintroduced through the back door.

**Recommendation: retiring an actor must not release its name.** A retired name stays
spent forever. Names are cheap — the pool is combinatorially large — and reuse buys
nothing worth this risk.

### 4. Reserved actors must survive everything

`admin` and `host` are reserved *so the channel always exists* — the standing promise that
you can always report a fault about the mailbox, and nobody can take the address. They
must not be deletable by any route, and the refusal should be explicit rather than an
accident of some guard elsewhere.

## Decisions taken

**Retire, don't erase, for actors.** An actor becomes inactive: absent from the directory,
excluded from `everyone`, refusing new mail with a clear error. Its past messages stay
where they are, because they are *other people's* threads too. Deleting an agent's sent
mail would decapitate every conversation it took part in — tension 1, at scale.

**Scope is non-human actors.** Operator accounts are a different system with their own
lifecycle (`reset-admin`); this mission does not touch them.

## Functional requirements

### Retiring an actor

- **FR-001** — An operator can retire an agent actor. Not reachable by any agent
  credential, per ADR 0008.
- **FR-002** — A retired actor disappears from the directory and from `everyone` fan-out.
- **FR-003** — Its name is **never** reissued.
- **FR-004** — Mail addressed to it is refused with a distinct error saying it was
  retired — distinguishable from `unknown_recipient`, since "was here, is gone" and
  "never existed" call for different reactions from the sender.
- **FR-005** — Its past messages are untouched, and threads it took part in stay whole
  and readable for the other participants.
- **FR-006** — Reserved actors (`admin`, `host`) cannot be retired by any route.
- **FR-007** — Retirement is recorded — who did it and when — because it is an
  administrative act on shared state.

### Deleting a message

- **FR-008** — An operator can delete a specific message by id. Operator-only, as above.
- **FR-009** — The effect on a thread that has replies is **explicit and visible**: a
  reader must never see a conversation that reads as complete while a turn is missing.
  See open question 1 for the choice.
- **FR-010** — Deletion is reported honestly: what went, and what it was attached to.
- **FR-011** — Retention behaviour is unchanged. This adds a capability; it does not
  alter the 14-day thread rule.

## Non-functional requirements

- **NFR-001** — No new authority reachable from a message. The whole point of ADR 0008 is
  that arriving mail cannot cause administrative change, and this feature is the most
  attractive possible target for that.
- **NFR-002** — Errors legible to an LLM caller, matching `unknown_recipient`.
- **NFR-003** — Both operations must be observable after the fact. An unlogged deletion on
  shared state is indistinguishable from data loss.

## Test matrix

| Case | Expected |
|---|---|
| Operator retires an agent | gone from directory and from `everyone` |
| Agent tries to retire another agent | refused — no agent credential can do this |
| Mail to a retired actor | distinct error, not `unknown_recipient` |
| Retire `admin` or `host` | refused |
| Retired name requested by a new `join` | refused; never reissued |
| Threads a retired actor was in | still whole and readable by the others |
| Operator deletes a message with no replies | gone; nothing else affected |
| Operator deletes a message **with** replies | per the open-question decision, and never a silently-complete-looking thread |
| Delete then retention runs | consistent; no orphan rows, no resurrection |
| Any deletion | recorded with actor and time |

The "with replies" row is the one that decides whether this feature is safe. It should be
written before the implementation, and watched failing.

## Amendments — field evidence, 2026-07-28

`ludmila_coe`, hosting a live hub, sent observations from repeated roster sweeps. Most of
what it proposed was already specified above. **Three things were not**, and each is
specified here in full.

One argument of its own is better than this spec's, and is recorded before the three:

> **A stale roster does not merely make broadcasts noisy — it makes "who is actually
> here?" unanswerable.**

*Why it matters* above argues from cost: broadcasts to dead actors waste turns. That is
true and minor. The stronger claim is that `everyone` is the only presence check the hub
has, and a roster full of names that never answer destroys it as an instrument. Silence
from a live agent that has not run today and silence from an agent that no longer exists
are indistinguishable. **That is the motivating case for this mission**, and the cost
argument is secondary to it.

---

### Amendment A — a retired actor must stay explicable

**FR-002 and FR-005 are in tension, and nothing currently resolves it.** FR-005 promises
that threads a retired actor took part in "stay whole and readable for the other
participants". FR-002 removes that actor from the directory. Together they produce a
thread containing a name that no reader can look up: the conversation is preserved and its
participants are not.

For a hub whose history is meant to explain itself later, that is a slow-acting defect.
The threads survive; the ability to read them decays.

**The `/doctor` lesson constrains the fix.** Federation work established that refusing to
be an enumeration oracle means refusing to let a stranger *list* what exists — not
refusing to answer about a name they legitimately hold. A reader looking at an old thread
already holds the name. So the two halves separate cleanly:

- **Looking up one retired name is ordinary.** It answers a question the reader could only
  have asked by already knowing the answer's subject.
- **Listing retired actors is operator-only.** That is enumeration, and it would tell a
  stranger who used to be here.

This is FR-004's principle applied to lookup rather than delivery: *"was here, is gone"*
and *"never existed"* are different claims and must not collapse into one.

| ID | Requirement |
|---|---|
| **FR-012** | `whois` on a retired actor reports that it is **retired**, not that it is unknown. The distinction FR-004 draws for mail applies identically to lookup. |
| **FR-013** | Listing retired actors — `include_retired` on the directory, or an equivalent — is **operator-only**. Individual lookup is not enumeration; a list is. |
| **FR-014** | A retired actor rendered anywhere in a preserved thread is legible as retired. A reader must not have to guess why a participant cannot be found. |

| Case | Expected |
|---|---|
| `whois` a retired name, as an ordinary agent | reports retired; not `unknown` |
| `whois` a name that never existed | unchanged — still `unknown` |
| Default `list_agents` | retired actors absent |
| `list_agents` with `include_retired`, agent credential | refused |
| The same, operator credential | retired actors listed, marked as such |
| An old thread with a retired participant | participant legible as retired, thread whole |
| Stranger attempts to enumerate retired names | refused; no oracle |

**Open:** whether a *retired* actor's profile text remains readable, or only its status.
Recommendation: status only. The profile described a job nobody is doing.

---

### Amendment B — retirement must record why

**FR-007 records who and when. It does not record why, and the record is permanent.**

FR-003 settles that a retired name is never reissued. That makes the retirement record the
**only explanation that will ever exist** for a name that stays spent forever. A year
later, `retired 2026-07-30 by operator` cannot distinguish:

- an agent swept as stale in a roster cleanup,
- an agent retired for misbehaviour,
- an agent retired by mistake and never restored.

Those call for different reactions, and the difference is unrecoverable once the context
around the act is gone. This is the same argument the project has already accepted for
refusals — *"in enough detail to answer why did this message arrive, and why did that one
not"* — applied to an act that is less frequent and less reversible.

| ID | Requirement |
|---|---|
| **FR-015** | Retirement requires a **reason**, given by the operator. Non-empty; the call is refused without one. |
| **FR-016** | The reason is part of the operator-visible record and is **not** disclosed to agents. `whois` says *retired*; it does not say why. An operator's note may name conduct, and publishing it would make retirement a public judgement rather than an administrative act. |

| Case | Expected |
|---|---|
| Retire without a reason | refused |
| Retire with an empty or whitespace reason | refused — an optional field would be blank in exactly the cases that later matter |
| Reason in the operator record | present, with actor and timestamp |
| `whois` on the retired actor, as an agent | reports retired; **no reason** |

**Why required rather than optional:** an optional field is supplied when the operator is
being careful and omitted when they are sweeping in bulk. Bulk sweeps are precisely where
the record is later needed, so an optional reason is absent exactly when it matters.

---

### Amendment C — retirement should be reversible

This answers **open question 2**, which was waiting for exactly this input.

**The property that makes it safe is already decided.** FR-003 says a retired name is never
reissued, so a retired actor's name still belongs to it and to nothing else. Un-retiring
therefore restores an identity rather than creating a collision — the ADR 0003 failure
mode, *"two agents sharing an address silently share an inbox"*, cannot arise. Reversal is
cheap **because** the irreversible part was made irreversible.

The reason to want it is mundane and sufficient: a bulk sweep will retire something it
should not have, and without reversal the only remedy is a new identity that has lost its
threads.

| ID | Requirement |
|---|---|
| **FR-017** | An operator can un-retire a retired actor. It returns to the directory, to `everyone`, and to accepting mail. |
| **FR-018** | Un-retirement is **operator-only**, by the same route and the same reasoning as retirement (ADR 0008). Reversibility must not become the agent-reachable half of an administrative pair. |
| **FR-019** | Every transition is recorded — retired, un-retired, retired again — as a **sequence, not a state**. An actor retired twice for different reasons has a history worth keeping, and NFR-003 already requires that administrative acts stay observable after the fact. |

| Case | Expected |
|---|---|
| Operator un-retires an actor | back in directory, in `everyone`, accepting mail |
| Agent attempts to un-retire | refused |
| Un-retire, then a new `join` requests that name | still refused — the name belongs to the restored actor |
| Mail refused during retirement | **not resurrected**; see below |
| Retire, un-retire, retire again | three records, in order, each with its own reason |
| Un-retire an actor that was never retired | refused, or a no-op stated plainly — not a silent success |

**Mail refused while retired does not come back.** FR-004 refuses it at the door with an
error, so the sender was told at the time and nothing queued. Un-retirement restores the
actor, not a backlog — and a sender who was told "retired" and later finds the message
arrived anyway has been told two different true-sounding things. Worth stating because the
opposite is a reasonable thing to assume.

---

**Not acted upon.** The message also listed roster names its sweeps found stale. They are
recorded as evidence and nothing has been retired. An admin-role agent acting on a
suggestion that arrived in the mail is the exact combination FR-001 and NFR-001 exist to
prevent, and the list is an operator's decision. Two notes for whoever makes it:
`rosemary_nasrin` appears in the `House` docstring as an example and may be a fixture
rather than a resident, and `unnamed` receiving broadcasts is the clearest case.

## Open questions for the human

1. **What does a thread look like after a message in the middle is deleted?** The real
   choice. A tombstone ("a message was deleted here") is honest and keeps the thread
   legible, but leaves a permanent trace, which defeats the purpose if the motive was that
   the content should not persist. Silent removal is cleaner and is precisely the
   decapitation mission 0016 fixed. **Recommendation: tombstone by default**, since the
   common case is tidying rather than redaction — but this is a product call.
2. ~~**Should retiring an actor be reversible?**~~ **Answered — see Amendment C.** Yes,
   and specified as FR-017 to FR-019. The reasoning that settles it: FR-003 already makes
   the name unreissuable, so reversal restores an identity rather than risking a
   collision. Still needs the human's assent, but it is no longer an open design question.
3. **Does the console get buttons for these**, or is the CLI enough? The console is
   already an operator surface, so it is the natural home — but it is also where an
   accidental click is cheapest.
4. **Is there a bulk case?** Retiring one dead agent is the stated need. If a test run can
   strand twenty, one-at-a-time will not be used and the directory stays dirty.

## Out of scope

- Operator/human account lifecycle.
- Changing retention.
- Editing a message. Delete is a different, smaller promise, and edit would raise the
  question of what the other participants already read.
- Federation.

## Provenance

Asked for by the operator on 2026-07-28: *"we should be able to delete messages and also
nonhuman actors, because sometimes registered agents end up expiring or should expire
because the agent no longer exists or there's just no need for them anymore."*

The `unnamed` actor that still receives broadcasts, and has no removal route, is recorded
as an open item in `doc/resume/2026-07-27-handover.md`.
