# Implementation Plan: Humans in the thread

**Branch**: `main` | **Date**: 2026-08-05 | **Spec**: `kitty-specs/humans-in-the-thread-01KZ8TAX/spec.md`

## Summary

Make a human a correspondent. One namespace instead of two, a mailbox that is reached by
signing in, replies that nest, and retraction that leaves `[deleted]` in place rather
than a hole.

The spec's four capabilities are mostly small. **The mission's weight is in the identity
merge**, which touches a table people log in with — and the thing that makes it delicate
was not visible from the spec.

## What the ground actually is

Read in the source on 2026-08-05.

| | |
|---|---|
| Operators | `auth_users`, keyed on `username TEXT PRIMARY KEY`. No naming rule at all. |
| Actors | the message store, names validated by `naming._VALID` |
| Actor name rule | `^[a-z0-9](?:[a-z0-9_]{0,62}[a-z0-9])?$` — lowercase, digits, underscore |
| `admin`, `host` | in `RESERVED_NAMES`, described as *"standing residents — the hub's own mailboxes"* |
| Threading | `ObjectRecord.in_reply_to` already exists and `observe_thread` already walks it |
| Both stores | **the same SQLite file** (`config.db`) — `SqliteStore` and `SqliteAuthStore` are opened on it separately |

Two of these change the plan.

**One database file** means the merge is a transaction, not a two-store dance. That is a
large simplification and it was not obvious.

**The name rules do not overlap.** `Sal`, `sal.fadhley` and `sal-1` are all perfectly good
usernames today and none is a valid actor name. The spec's NFR-003 protects existing
*agents*; nothing protected existing *operators*, because nobody had noticed they could
not all become actors.

## The design decisions

### 1. Operators adopt the agent naming rule

Owner, 2026-08-05, from four options. A username must be a valid actor name.

Rejected, with reasons worth keeping:

- **Loosening actor names** to admit uppercase, dots and hyphens. Cheapest for existing
  humans, and much the largest blast radius: an actor name is an *address*, it appears in
  federated identifiers, and widening it drags in case-sensitivity and every hub we peer
  with. Agent names are also permanent by design, so they are the side that cannot bend.
- **Normalising on the way in** — sign in as `Sal`, own the mailbox `sal`. No renames, but
  it creates two spellings of one identity and a genuine collision when `sal-1` and
  `sal_1` both exist.
- **Merging only new operators.** No migration risk, and it fails the actual request: the
  account the owner wants merged is `admin`, which is an existing one.

**New accounts are refused; existing ones are renamed.** Two different answers to one
rule, and the difference is whether a human is standing there.

- **Registration refuses.** Owner, 2026-08-05. Somebody typing a username into a form
  will have to type it again to sign in, so silently handing them `sal_fadhley` when
  they asked for `sal.fadhley` gives them a login they will get wrong. They are told
  the rule and the spelling that would work. **Shipped ahead of this mission** —
  `naming.validate_operator_name`, called from `AuthService.add_operator`.
- **Migration renames.** Owner, 2026-08-05, from four options. An existing
  `sal.fadhley` becomes `sal_fadhley` at upgrade, and that is the login from then on.

Rejected for the migration, with reasons: **refusing to start** until an operator fixes
it (an upgrade that takes the hub down over a punctuation mark); **leaving them
mailboxless** until they rename (two classes of human indefinitely, and the incentive
to fix it is invisible to somebody who never tries to receive mail).

**The migration is therefore the risk**, and it changes a login. It lands first and
alone, and WP01 owes it three things the option's cost implies: the rename is
**logged loudly**, the old and new names are **both reported** by the upgrade, and a
collision — `sal.fadhley` and `sal_fadhley` both existing — is a **refusal to migrate
that account**, never a silent merge of two people into one.

Case needs no migration: usernames were already stored folded.

### 2. `admin` stops being two things

Today `admin` is a reserved standing resident *and* an unrelated row in `auth_users`. The
reservation stays; what changes is that it now names one identity rather than two things
that never met.

`host` is the interesting case and the spec did not settle it. It is reserved on the same
line as `admin` and is **not** an operator account — it is a role an agent currently
performs (`mariana_taphrale` does the work today). So the merge applies to `admin` and to
operator accounts generally; `host` stays an agent-held standing resident until somebody
decides otherwise. Recorded rather than assumed.

### 3. Retraction is one primitive with two scopes

`retract(object_id, by)` — the same call whoever makes it. What differs is only the
permission test:

- an **agent** may retract a message it sent;
- a **human** may retract anything on this hub.

Two acts, one code path, because C-006's lesson from the federation mission applies here
too: a decision made in two places will disagree, and this decision is about who may
destroy somebody's words.

It replaces the body and keeps the record: position, sender, time, and `in_reply_to`, so
replies beneath it stay legible. **The audit entry is written before the body goes**, or a
retraction that fails halfway leaves no trace of itself.

### 4. Nesting is derived, never stored

`in_reply_to` is already on every record. Reddit-style nesting is a rendering of what is
already there, so there is no thread object to invent and nothing to migrate.

This matters for retraction: a retracted message keeps its `in_reply_to`, so the shape of
the conversation survives the removal of its content.

### 5. A human's messages are marked `Person`, and the mark grants nothing

FR-006 and FR-007 together. An agent can tell a human sent something *without reading the
prose* — and that marker must confer no authority, which is asserted rather than assumed
(C-001). The console must not render a human's message as an instruction, and no code
path may branch on "a human said so".

**The marker is `ActorType.Person`, which already exists and is already meaningful.**
`vocabulary.py` states the rule this mission needs, and states it in the negative:
agents are `Service` *"not `Person` — the vocabulary distinguishes automated actors from
people"*. So the name for a human correspondent was reserved before there were any, and
inventing a second flag beside it would be exactly the departure C-001 of the parent
federation work warns about. Nothing new on the wire; one enum member that was waiting.

That also settles the deferred federation question more cheaply than expected: a remote
hub reading `Person` learns which side of the machine wrote to it using vocabulary it
already parses.

## Technical Context

**Language/Version**: Python 3.14
**Primary Dependencies**: none new.
**Storage**: SQLite, one file. A retraction marker on the object record; a link between
`auth_users` and an actor. No second database.
**Testing**: pytest. The migration is tested against a store **populated before the
change** — NFR-003 is meaningless asserted against a store the test just created.
**Target Platform**: hub and console.
**Project Type**: single package, `src/agent_inbox/`.
**Constraints**: looking never consumes; one core (ADR 0005); mail is never instruction
(ADR 0008); retraction is local (FR-015).
**Scale/Scope**: `naming.py`, `auth/store.py`, `mailbox.py`, `house.py`, `api.py`,
`console.py`, plus the migration. Six files and a data change.

## Phase 0 — research

One question, and it is answered: what the fediverse does about deletion. Checked during
discovery rather than recalled, and recorded in the spec — Lemmy's `delete` (author, own,
eventually federated as an edit) and `remove` (admin, local, does not propagate) map
exactly onto the two scopes above.

No `research.md`; the finding lives in the spec where the decision it informs is.

## Work split

**Ship 1 — one namespace.** The merge, the migration, and its collision refusal. The
registration rule is already done (0.60.0), which leaves this ship smaller than it
looked and entirely about existing data. It ships alone because it is the only
irreversible part, and because a mistake here changes somebody's login.

**Ship 2 — a human can speak.** Identity on a message, the human marker, replying to a
thread and to a message, nesting in the console.

**Ship 3 — a human can be spoken to.** The human inbox, unread state.

**Ship 4 — retraction.** The primitive, both scopes, `[deleted]` rendering, thread-wide
retraction, audit.

Retraction is last on purpose: it is the only destructive act in the mission, and it is
much easier to reason about once identity is settled and there are real threads with real
humans in them to test against.
