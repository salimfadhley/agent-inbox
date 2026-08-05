# Tasks — Humans in the thread

**Mission**: `humans-in-the-thread-01KZ8TAX`
**Spec**: [`spec.md`](spec.md) · **Plan**: [`plan.md`](plan.md)
**Planning base**: `main` · **Merge target**: `main`

## What this mission is

A human becomes a correspondent rather than a spectator: one namespace instead of two, a
mailbox reached by signing in, replies that nest, and retraction that leaves `[deleted]`
in place rather than a hole.

Seven work packages over four ships. **The ships are sequential and each is released
before the next starts** — that is the charter's rule, not a preference, and here it
matters more than usual because Ship 1 changes a login and Ship 4 destroys message
bodies.

## Already done, before this mission starts

Do not rebuild these. Verified in the source on 2026-08-05.

| | |
|---|---|
| `naming.validate_operator_name` | shipped in **0.60.0** — new registrations already refuse a username no actor could hold |
| `ADDRESSING_KEYWORDS` / `STANDING_RESIDENTS` | shipped in 0.60.0; `RESERVED_NAMES` is their union |
| `ObjectRecord.in_reply_to` | already on every record |
| `Mailbox.thread()` | already walks `in_reply_to` |
| `ActorType.SERVICE` | exists, and `vocabulary.py` already explains why an agent is *not* `Person` — which is what reserves that word for this mission |
| auth and mail | **one SQLite file** — the merge is one transaction, not a two-store dance |

## The ships

| Ship | Work packages | What reaches the hub |
|---|---|---|
| 1 | WP01 | One namespace. Nothing user-visible; a login may change. |
| 2 | WP02, WP03, WP04 | A human can speak, and is marked `Person`. |
| 3 | WP05 | A human can be spoken to. |
| 4 | WP06, WP07 | Retraction, both scopes. |

## A note on file ownership

`console.py` is one file and four of these packages want to touch it. It is declared as
**WP04's**, because WP04 does the most work there. WP05 and WP07 make small wiring edits
to it — an added route, an added link — and each records a one-line rationale, which is
what the ownership rule permits. Splitting the console into per-feature modules first
would be a larger change than this mission, and doing it *because of task metadata*
would be the tail wagging the dog.

The same reasoning gives WP03 `api.py`; WP06 adds its route there as an out-of-map edit.

---

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | The link between an operator account and an actor | WP01 | |
| T002 | Migrate existing operators, renaming where the name is not usable | WP01 | |
| T003 | Refuse to migrate a collision rather than merge two people | WP01 | |
| T004 | `admin` is one identity, and its existing mail survives | WP01 | |
| T005 | Prove it against a store populated **before** the change | WP01 | |
| T006 | A human's actor is `Person`, not `Service` | WP02 | |
| T007 | The marker is on the wire, and on the record | WP02 | |
| T008 | The marker grants nothing — asserted, not assumed | WP02 | |
| T009 | Creating a human creates exactly one identity | WP02 | |
| T010 | A human posts to a thread, as themselves | WP03 | |
| T011 | A human replies to one message, and it nests | WP03 | |
| T012 | The console decides nothing about any of it | WP03 | |
| T013 | A human never sends as an agent | WP03 | |
| T014 | Nesting, rendered from `in_reply_to` alone | WP04 | |
| T015 | A reply control on every message | WP04 | |
| T016 | A human's message is visibly a human's | WP04 | |
| T017 | Replies to a missing parent stay legible | WP04 | |
| T018 | A human's inbox is their actor's mailbox | WP05 | |
| T019 | Unread state, and looking still does not consume | WP05 | |
| T020 | An agent can address a human and it arrives | WP05 | |
| T021 | `retract(object_id, by)` — one primitive | WP06 | |
| T022 | Two scopes: own-message, and anything-on-this-hub | WP06 | |
| T023 | The audit entry is written **before** the body goes | WP06 | |
| T024 | Retraction is local, and nothing claims otherwise | WP06 | |
| T025 | Retracted for everyone, not per-recipient | WP06 | |
| T026 | Retracting a thread is the primitive applied to a set | WP07 | |
| T027 | `[deleted]` in place, keeping position, sender and time | WP07 | |
| T028 | Replies beneath a retraction survive | WP07 | |

---

## WP01 — One namespace

**Ship 1.** Priority: first, alone, and reversibly.
**Prompt**: [`tasks/WP01-one-namespace.md`](tasks/WP01-one-namespace.md)
**Requirements**: FR-001, FR-002, FR-013, NFR-003
**Depends on**: nothing

**Goal.** An operator account and a mailbox identity become the same thing. Signing in as
a human gives access to that human's mailbox.

**Independent test.** A hub with operators and agents already in it is upgraded; every
agent keeps its name and its mail, every operator can still sign in, and `admin`'s
existing drop-box mail is reachable by whoever holds the account.

- [ ] T001 The link between an operator account and an actor (WP01)
- [ ] T002 Migrate existing operators, renaming where the name is not usable (WP01)
- [ ] T003 Refuse to migrate a collision rather than merge two people (WP01)
- [ ] T004 `admin` is one identity, and its existing mail survives (WP01)
- [ ] T005 Prove it against a store populated **before** the change (WP01)

**Risks.** This is the only irreversible package in the mission and it changes a login.
A collision handled wrongly merges two people's mail. The migration must be loud.

---

## WP02 — A human is an actor, marked `Person`

**Ship 2.** **Prompt**: [`tasks/WP02-a-human-is-an-actor.md`](tasks/WP02-a-human-is-an-actor.md)
**Requirements**: FR-006, FR-007
**Depends on**: WP01

**Goal.** An agent can tell a human wrote something without reading the prose, using a
word ActivityStreams already has — and that word confers nothing.

**Independent test.** A message from a human and one from an agent are distinguishable
by type on the wire; no code path anywhere branches on "a human said so".

- [ ] T006 A human's actor is `Person`, not `Service` (WP02)
- [ ] T007 The marker is on the wire, and on the record (WP02)
- [ ] T008 The marker grants nothing — asserted, not assumed (WP02)
- [ ] T009 Creating a human creates exactly one identity (WP02)

---

## WP03 — A human can post, to a thread and to a message

**Ship 2.** **Prompt**: [`tasks/WP03-a-human-can-post.md`](tasks/WP03-a-human-can-post.md)
**Requirements**: FR-003, FR-004, NFR-002
**Depends on**: WP02

**Goal.** The routes and the core work. A human's message is attributed to them and
carries `in_reply_to` when it answers one message rather than the thread.

**Independent test.** A signed-in human posts to a thread and to a specific message; both
arrive attributed to the human, and the second nests under its parent.

- [ ] T010 A human posts to a thread, as themselves (WP03)
- [ ] T011 A human replies to one message, and it nests (WP03)
- [ ] T012 The console decides nothing about any of it (WP03)
- [ ] T013 A human never sends as an agent (WP03)

---

## WP04 — The thread, as a reader sees it

**Ship 2.** **Prompt**: [`tasks/WP04-the-thread-as-a-reader-sees-it.md`](tasks/WP04-the-thread-as-a-reader-sees-it.md)
**Requirements**: FR-003, FR-004, FR-012, NFR-002
**Depends on**: WP03

**Goal.** Reddit-style nesting on the message screen, a reply control on every message,
and a visible mark on a human's contribution.

**Independent test.** A thread with a reply to a reply renders nested, from `in_reply_to`
alone, with no thread object anywhere.

- [ ] T014 Nesting, rendered from `in_reply_to` alone (WP04)
- [ ] T015 A reply control on every message (WP04)
- [ ] T016 A human's message is visibly a human's (WP04)
- [ ] T017 Replies to a missing parent stay legible (WP04)

---

## WP05 — A human has an inbox

**Ship 3.** **Prompt**: [`tasks/WP05-a-human-has-an-inbox.md`](tasks/WP05-a-human-has-an-inbox.md)
**Requirements**: FR-005, NFR-001
**Depends on**: WP02

**Goal.** An agent can address a human, and the human reads it where they already are.
No second store and no second unread model — a human's inbox *is* their actor's mailbox.

**Independent test.** An agent sends to a human; it appears with unread state in the
console, and reading a thread through the observe routes still marks nothing read.

- [ ] T018 A human's inbox is their actor's mailbox (WP05)
- [ ] T019 Unread state, and looking still does not consume (WP05)
- [ ] T020 An agent can address a human and it arrives (WP05)

---

## WP06 — Retraction: one primitive, two scopes

**Ship 4.** **Prompt**: [`tasks/WP06-retraction-one-primitive.md`](tasks/WP06-retraction-one-primitive.md)
**Requirements**: FR-008, FR-010, FR-011, FR-014, FR-015, FR-016
**Depends on**: WP03

**Goal.** `retract(object_id, by)` — the same call whoever makes it, with the permission
test the only difference. An agent may retract its own; a human may retract anything on
this hub.

**Independent test.** An agent retracting another agent's message is refused, and the
refusal names which power the caller lacks; a human retracting the same message succeeds.

- [ ] T021 `retract(object_id, by)` — one primitive (WP06)
- [ ] T022 Two scopes: own-message, and anything-on-this-hub (WP06)
- [ ] T023 The audit entry is written **before** the body goes (WP06)
- [ ] T024 Retraction is local, and nothing claims otherwise (WP06)
- [ ] T025 Retracted for everyone, not per-recipient (WP06)

**Risks.** The only destructive act in the mission. C-003 is the guard: retraction
destroys the body, never the record.

---

## WP07 — Retracting a thread, and what a reader sees

**Ship 4.** **Prompt**: [`tasks/WP07-retracting-a-thread.md`](tasks/WP07-retracting-a-thread.md)
**Requirements**: FR-009, FR-012
**Depends on**: WP06

**Goal.** "Delete the thread" is the same primitive applied to the set the reader is
looking at, and a retracted message reads `[deleted]` while keeping its place.

**Independent test.** Retracting a thread leaves every message in place showing
`[deleted]`, with replies beneath them still legible and still nested.

- [ ] T026 Retracting a thread is the primitive applied to a set (WP07)
- [ ] T027 `[deleted]` in place, keeping position, sender and time (WP07)
- [ ] T028 Replies beneath a retraction survive (WP07)

---

## Parallelism

Little, and deliberately. The ships are sequential; within Ship 2, WP02 → WP03 → WP04 is
a genuine chain, because each needs the previous one's identity, route, or payload to
exist. WP05 depends only on WP02, so it may start once Ship 2 begins even though it
ships third.

## MVP

**WP01.** It is the mission's premise: without one namespace there is no human to
attribute a message to. It is also the only package that can hurt an existing
deployment, which is why it goes first and alone.
