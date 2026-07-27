# Spec — a send with no recipients must fail loudly

- Mission: `empty-recipient-sends-must-fail-loudly-01KYJYEK`
- Raised by: `ludmila_coe` (host), ranked **#1** on her improvement list, 2026-07-27
- Characterised by: `nicole_ruzickova`, against halob 0.21.1
- Status: **shipped.** See "What actually shipped" at the foot of this document — the
  operator changed the design when approving it, and self-send now *delivers*.

## What this is

The hub accepts a message that it will deliver to nobody, stores it, and returns
success. Nothing anywhere reports that the message went nowhere.

The reproducing case is a self-send — an agent addressing itself. The sender is stripped
from the delivery audience, the remaining audience is empty, and the empty set is not
treated as a failure.

## Why it matters

Not because agents need to message themselves. They do not.

It matters because **a success response is evidence, and this one is false**. The caller
receives an object id and a 201, which is exactly what a real delivery returns. Any
process that builds on that response builds on a lie.

The concrete case that produced this report: a wake-latency experiment was going to be
armed with a timed self-send as its stimulus. Had the send been trusted, the experiment
would have sat waiting for mail that was never going to arrive, and reported *"idle wake
does not work"* — a false negative about a working feature, backed by a green send.

This is the same defect shape recorded in `AGENTS.md`: **a check that passes because it
had nothing to look at.** Three separate defects on 2026-07-27 had this shape. This is
the fourth, and unlike the others it hands the false evidence to a caller.

## Evidence

Reproduced on all three client surfaces against halob 0.21.1. This is hub-side; the
clients are innocent.

| Surface | Call | Result |
|---|---|---|
| MCP | `send_message(to="nicole_ruzickova")` | success, `objects/d5bb641ca8614c01898b0eac5b423fcc`, `"to": []` |
| CLI | `agent-mailbox send nicole_ruzickova …` | success, `objects/dfab2fc958124d65ae32e85f6c3a3e9f`, `"to": []` |
| Raw API | `POST /actors/nicole_ruzickova/outbox` | **HTTP 201 Created**, `objects/34189524367742c182a74a8ac274b128` |

The raw API response shows the divergence the client responses hide:

```json
"to": [], "cc": [], "audience": ["nicole_ruzickova"]
```

The requested audience is recorded faithfully. The delivery list is empty. The object is
created and persisted. No delivery row is ever written, which is why it never appears in
any inbox and why nothing errors.

**Invalid-recipient handling is not broken and must not be changed.** A send to an
unknown name is already refused, clearly:

```
nobody here is called 'definitely_not_an_agent_xyz' — check the name, or call
`directory` to see who has joined [unknown_recipient]
```

That is the loud failure this mission wants. The self-send path simply does not reach it.

## Decisions taken

**The invariant is `to` vs `audience`, not "reject self-sends".**

> A response may not report success if `audience` is non-empty and `to` is empty.

Stating it this way rather than enumerating cases is deliberate. It catches:

- sender-stripping producing an empty audience (the observed case);
- a group or alias that expands to zero members (**not yet tested — see open questions**);
- any future audience-resolution rule, without anyone remembering to add a test for it.

Asserted at the API boundary, one assertion covers the whole class. Enumerating known
causes would leave the next cause silent, which is how this one survived.

**Whether self-send should deliver is a separate product question, and is out of scope.**
This mission makes the outcome honest. If self-delivery is later wanted — an agent
leaving itself a note across sessions is not absurd — that is its own mission with its
own reasoning. Do not let it in through this door: an implementer who "fixes" this by
making self-send deliver has changed messaging semantics on the strength of a bug report.

## Functional requirements

- **FR-001** — A send whose resolved delivery list is empty, while its requested audience
  is non-empty, must fail. It must not return 2xx and must not persist a delivered object.
- **FR-002** — The failure must be a distinct, named error, in the shape already used by
  `unknown_recipient`, so a caller can branch on it rather than parse prose.
- **FR-003** — The error must say what happened in terms the caller can act on: who was
  requested, that nobody could be delivered to, and why. "Invalid request" is not enough.
- **FR-004** — All three surfaces (MCP tool, CLI, HTTP API) must surface the failure. No
  surface may translate it into a success or a silent no-op.
- **FR-005** — Existing correct behaviour must not regress: unknown recipients keep their
  current error, and ordinary sends and broadcasts are unaffected.
- **FR-006** — The three probe objects created while characterising this defect
  (`d5bb641c…`, `dfab2fc9…`, `34189524…` on halob) are undeliverable and should be
  removed as part of shipping this, or explicitly left with a reason.

## Non-functional requirements

- **NFR-001** — No new round trip on the ordinary send path. This is a check on a value
  the hub already computes, not a new lookup.
- **NFR-002** — The error must be as legible to an LLM caller as `unknown_recipient` is.
  The audience for these messages is an agent deciding what to do next.

## Test matrix

The regression test must be watched failing with its own fix removed before it is
believed. That rule exists because a test written for this class of defect is itself
prone to passing vacuously.

| Case | Expected |
|---|---|
| Self-send, MCP | named error, no object persisted |
| Self-send, CLI | named error, non-zero exit |
| Self-send, raw API | 4xx with the named error code, **not 201** |
| Send to unknown name | unchanged `unknown_recipient` error |
| Ordinary send to another agent | unchanged success, `to` non-empty |
| Broadcast to `everyone` | unchanged success, `to` non-empty |
| Group/alias expanding to empty | named error — **blocked on the open question below** |
| API-boundary invariant | no response with `audience` non-empty and `to` empty, across the whole suite |

The last row is the one that outlives this mission. Prefer implementing it as a shared
assertion the send tests run through, so a future audience rule cannot regress silently.

## Open questions for the human

1. **Does a group or alias abstraction exist that can resolve to empty**, separately from
   sender-stripping? If yes it belongs in the acceptance test. If no, ludmila's advice —
   which I agree with — is to write the API-boundary assertion generically anyway, so a
   later empty group cannot regress silently.
2. **Should self-send deliver instead of failing?** Recommended answer: no, not in this
   mission. Recorded so the decision is explicit rather than assumed.
3. **Priority against the rest of ludmila's list**, in particular the auth-aware live
   smoke suite. Her ranking put this first, but was made before the evidence showed it was
   hub-side rather than MCP-only.

## Out of scope

- Making self-send deliver (see above).
- The auth-aware live smoke suite — a separate item on the same list.
- The auth-mode-contradicting error text (`This hub does not authenticate` returned by a
  hub that does) — related in shape, separate defect, separate mission.
- Any change to `unknown_recipient` handling, which is already correct.

## Provenance

Reported by `ludmila_coe` as the top item of a ranked improvement list drawn from
host-side friction across multiple agents. Classified on request, across MCP, CLI and raw
API, on 2026-07-27. The `to`/`audience` invariant is the acceptance criterion agreed
between host and admin in that exchange.

Per the operator's standing instruction, this was written up for human discussion and
was **not** implemented on the strength of the report alone. The human then approved it,
with a change — recorded below.

---

## What actually shipped

The operator approved the blanket-with-distinguished-errors option **and rejected the
premise of open question 2**: *"I think there's a legitimate testing use case in
messaging yourself."*

That is the case that produced this report in the first place — arming a wake experiment
needed mail to actually arrive — so the answer above ("self-send should fail") was wrong.
The shipped design is therefore not what this spec proposed:

**Explicit self-address delivers. Incidental self-inclusion still does not.**

| Case | Before | Now |
|---|---|---|
| Addressing yourself by name | success, delivered to nobody | **delivered**, appears in your own inbox |
| Inside your own group's fan-out | not delivered to you | unchanged — not delivered to you |
| Group with no other members | success, `to: []` | `delivers_to_nobody`, 422 |
| `everyone` on a mailbox of one | success, `to: []` | `delivers_to_nobody`, 422 |
| Unknown name | `unknown_recipient` | unchanged |

The distinction is the **typed** audience, not the resolved one: writing your own name is
deliberate, being swept into your own fan-out is not. Scenario 6 — never being handed back
what you just said — survives intact for the case it was written for. This is why
`audience` is stored unresolved (ADR 0006); that decision paid for itself here.

### Two things this got wrong first

**The status code.** `mailbox_error_handler` does `STATUS_BY_CODE.get(exc.code, 500)`, so
a new code that nobody maps becomes a **500** — the hub reporting its own fault for the
caller's empty audience. Caught by writing the API test instead of reasoning that "the
handler is generic, so it propagates". It does propagate; it propagates wrongly.

**The `everyone` case is not reachable over the API.** A real hub always carries its
reserved actors (`admin`, `host`), so a broadcast is never genuinely empty. The first API
test asserted a 422 and got a correct 201. Only the empty-group case reaches this error on
a real hub; the lone-`everyone` case is reachable from a bare `Mailbox`, which is where it
is tested.

### Verification

The regression tests were watched failing with the fix removed, per the rule above: 8 of
10 failed. The two that did not are the scenario-6 guard, which asserts behaviour that was
already correct and had to keep working — a test that passes both ways is doing its job
there, but it would have been worthless as evidence for the new behaviour.

Still open, unchanged: **FR-006**, the three undeliverable probe objects on halob. They
predate the fix and are not removed by it.

