---
work_package_id: WP01
title: The hub emits
dependencies: []
requirement_refs:
- FR-001
- FR-002
- FR-003
- FR-004
- FR-006
- FR-007
- FR-008
- FR-009
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
- T006
- T007
- T008
phase: Phase 1 - The hub emits
agent: python-pedro
history:
- at: '2026-08-01T20:55:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/notify.py
create_intent:
- src/agent_inbox/notify.py
- tests/test_events_stream.py
execution_mode: code_change
owned_files:
- src/agent_inbox/notify.py
- src/agent_inbox/api.py
- src/agent_inbox/house.py
- tests/test_events_stream.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP01 – The hub emits

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro` · **Role**: `implementer` · **Agent/tool**: `python-pedro`

---

## Objective

A client holds `GET /actors/{name}/events` open and is told, within a second, that mail
arrived for it. The event carries **who it is from, what it is about, and its id** — never
the body. Nothing else about the hub changes: polling works exactly as before, mail is
exactly what it was, and a hub with nobody listening behaves identically to today's.

This WP ships on its own. A hub that emits events into an empty room is harmless, fully
testable, and is what makes T008's measurement possible at all.

## Context you need before you start

**Phase 0's second question is already answered.** Litestar 2.24 (already a dependency)
provides `litestar.response.ServerSentEvent`, which takes an async iterable of
`ServerSentEventMessage(data=..., event=..., id=...)` and handles the wire format. Do not
hand-roll `text/event-stream`. There is **no new runtime dependency in this WP** — if you
find yourself adding one, stop and say why.

**What Litestar does not give you is the fan-out.** The stream generator for Alice's
connection needs to be woken by a `POST /actors/bob/outbox` happening on a *different*
request, in the same process. That is T001, and it is about fifty lines: a dict from actor
name to a set of per-connection `asyncio.Queue`s.

**`House.send` is the only correct emit point.** `src/agent_inbox/house.py:190` is where
mail becomes stored fact, and both paths reach it:

- a local send — `api.py:780`, from `POST /actors/{name}/outbox`
- a **federated arrival** — `api.py:1130`, from `POST /actors/{name}/inbox`

It also already computes `sent.local_recipients` (house.py:232), which is exactly the list
of people to tell, with remote URIs already excluded. Emitting in the API handler instead
would silently miss every federated message; emitting in `Mailbox.send` would put a
transport concern inside the store layer.

## Subtasks

### T001 — The connection registry

New module `src/agent_inbox/notify.py`. It owns one thing: which connections are open, for
whom, and how to hand them an event.

- Keyed by **resolved local actor name**, the same string `local_recipients` holds. Not the
  path parameter, not the header — resolve once, at the door.
- Each connection gets its own bounded `asyncio.Queue`. One slow client must not stall a
  send or another client's stream.
- **A full queue drops the event, and says so** — it must never block and never raise into
  the caller. A client so far behind that it has missed events is a client that should fall
  back on polling, which is exactly what FR-003 keeps first-class. Log the drop; do not
  silently pretend it was delivered.
- Registration is a context manager or an explicit pair, and **unregistration must happen on
  every exit path**, including cancellation. A registry that leaks entries when clients
  disconnect is the resource leak FR-007 exists to make visible, and it will present as
  working.
- Expose `count()` (total open) and per-actor count, and a cap.

Keep it free of Litestar and of `House`. It should be testable with nothing but `asyncio`,
because that is what makes T004–T006 cheap to write honestly.

### T002 — The route

`GET /actors/{name}/events` in `api.py`, alongside the existing `inbox` route, with
`dependencies={"caller": Provide(provide_caller)}` and the same `owns(name, caller, wire)`
check every per-actor route uses (api.py:110). Two failure modes are **security cases**, not
ergonomics:

- **No credentials** → refused, exactly as the existing routes refuse.
- **Credentials for another identity** → 403, and no event ever reaches that connection.
  `owns` already produces the right refusal; use it rather than a new check that has to be
  kept in agreement with it.

The response is `ServerSentEvent` over a generator that:

1. registers with the registry (T001),
2. yields events as they arrive,
3. **unregisters in a `finally`**, so a client vanishing mid-stream is cleaned up.

Send a periodic keep-alive comment. Proxies and Fly's TLS terminator close idle connections,
and a stream that dies after N idle seconds is a stream that only works while it is busy —
which is precisely backwards. This is also what T008 measures.

### T003 — Emit from `House.send`

After `await self._record(...)` in `House.send`, tell the registry about `sent.record` for
each of `sent.local_recipients`.

**It must be unable to fail a send.** Wrap it so that nothing it does can propagate — a hub
that refuses mail because nobody could be told about it has inverted its own priorities, and
that inversion is the single worst outcome available in this WP. Log the failure; never
raise it.

**After the write, never before.** Same ordering as the mark-read work in #33: an event that
says mail exists before it exists is a lie a client can act on.

Do **not** notify the sender about their own copy unless they are genuinely a recipient.

### T004 — The disclosure tests

`tests/test_events_stream.py`. These are the security cases and they carry the weight:

- mail addressed to someone else produces **no event** on this connection;
- a connection with **no credentials** is refused;
- a connection presenting **another identity's** credentials is refused, and no event leaks;
- a `cc` recipient is told, because they *are* a recipient — check this against what the
  visibility rules already say rather than inventing a second answer.

**Prove these by removal.** Delete the `owns` check locally and watch the leak test fail. A
disclosure test that would pass with the guard removed is not testing the guard.

### T005 — The content tests

- **No body** (FR-002). Assert on the whole event payload, not on the absence of one key —
  a test that checks `"content" not in event` passes happily when the body arrives under
  another name.
- **Actionable without a second round trip** (FR-008, the review's C1): the id is sufficient
  to fetch the message, and the subject is sufficient to decide whether to. Assert both
  halves — that the id round-trips to the real message, and that the subject matches what
  was sent.
- **Mail is unchanged** (FR-009, the review's C2): a message that arrived while a client was
  connected reads, expires, and discloses identically to one that did not. Send two
  messages, one with a stream open and one without, and assert the stored records and the
  inbox views are equivalent.

### T006 — The count and the cap

- The open-connection count is **observable** — it belongs with the other operator-visible
  facts (`/observe/stats` is the obvious home; follow whatever that route already does
  rather than adding a route of its own).
- A cap, and reaching it **refuses clearly and leaves existing connections unharmed**. Test
  that: the refusal must name the cap, and the connections already open must still receive
  events afterwards.

Say what the count means, in the text that reports it: **a connected session**, never "this
agent is present". The spec is explicit that presence vocabulary belongs to issue #7, and a
count labelled "online" is that decision made by accident.

### T007 — Directive 4

Outside model review before this WP closes:

```
perl -e 'alarm 300; exec @ARGV' codex exec "<one narrow question>" < /dev/null
```

Ask one narrow question. The highest-value one here is whether the emit in `House.send` can
fail a send under any path — cancellation, a full queue, a client disconnecting mid-emit —
because that is the failure this WP most needs not to have.

### T008 — After deploying: does it survive, and how late is it

**This runs after the release, not before.** It is the plan's Phase 0 question 1 and the
review's finding A1, and neither could be measured before the route existed.

With the version deployed to both hubs:

- Hold the stream open with `curl -N` against **both** hubs for long enough to cross any
  idle timeout, and record what actually happens — whether the connection survives, and if
  not, after how long and killed by what.
- Measure the **latency** from send to event, and record the real number. The spec says
  "within a second"; either the measurement supports that as a test criterion or the spec
  should say it is an aspiration. Do not leave the only number in the spec unmeasured for a
  second mission.
- Record the answer in the mission directory. A number nobody wrote down is a number that
  will be re-measured.

## Definition of Done

- The four gates pass: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`,
  `uv run pyright`.
- A client holding the stream gets an event within a second, carrying sender, subject and id
  and no body.
- No test in the existing suite changes behaviour. Polling clients are untouched.
- The emit cannot fail a send, and there is a test that says so.
- T007's review is clean or its findings are closed.
- Released and deployed to **both** hubs, and proved with `verify-deployment`, before WP02
  starts. T008 is done against that deployment.

## Reviewer guidance

Look hardest at three things:

1. **Can the emit fail a send?** Follow every path out of `House.send`.
2. **Can a connection outlive its registration?** A client that disconnects during a slow
   yield must still be removed.
3. **Does the event contain anything the recipient should not see?** Every field on the wire
   should be one somebody chose to put there.
