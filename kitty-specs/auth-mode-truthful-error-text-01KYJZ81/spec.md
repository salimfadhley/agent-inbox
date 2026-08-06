# Spec — error text must derive from the hub's actual auth mode

> **Audited and closed 2026-08-03.** Verified implemented in the code, not merely
> specified. This folder is history; nothing in it is outstanding work.

- Mission: `auth-mode-truthful-error-text-01KYJZ81`
- Raised by: `ludmila_coe` (host), **#3** on her revised list, 2026-07-27
- Evidence from: `nicole_ruzickova`, against examplehub 0.21.1
- Related: [`auth-aware-live-smoke-suite-01KYJZ80`](../auth-aware-live-smoke-suite-01KYJZ80/spec.md) — same `auth-mode truthfulness` theme, deliberately separate mission
- Status: **specified, not started.** Awaiting human prioritisation.

## What this is

A hub that requires authentication tells callers, in an error message, that it does not.

Observed on examplehub, which runs `AGENT_MAILBOX_AUTH_MODE=enforce`. Posting to an outbox
with a valid bearer token but no name header:

```json
{"status_code": 400,
 "detail": "missing X-Agent-Name header — send your name, for example 'rosemary_nasrin'.
            This hub does not authenticate; it takes the header at its word."}
```

The same hub, given no token at all, answers:

```json
{"code": "not_authenticated",
 "detail": "this hub requires authentication — present a device token as
            `Authorization: Bearer <token>`, or log in at the console"}
```

Both responses come from the same hub, moments apart. They contradict each other.

## Why it matters

The sentence is not merely wrong, it is **wrong in the direction that costs debugging
time**. A caller told "this hub does not authenticate" concludes their credential is
irrelevant, and goes looking for the fault in the header, the client, or the route —
anywhere except the auth configuration that actually governs the request.

It is also a trust problem in a system where the hub's self-description is load-bearing.
`GET /` advertising `authenticated: true` is what the sibling live-suite mission proposes
to build assertions on. A hub that describes its own auth mode inconsistently across
surfaces undermines the thing that makes that suite possible.

The likely mechanism, unconfirmed: the string is a hardcoded constant written when the
hub had no authentication, rather than derived from the mode the hub is running in. If so
it will have been wrong on every enforcing deployment since auth shipped, which nobody
noticed because it appears only on a 400 that is itself uncommon.

## Decisions taken

**Derive, do not duplicate.** Every message that describes the auth posture must read the
running mode rather than restate it in prose. A second literal describing auth behaviour
is a second thing to forget, which is how this one survived.

**Scope is truthfulness, not redesign.** This mission does not change what is
authenticated, does not add routes, and does not restructure the error envelope. It makes
existing messages agree with the hub they came from.

## Functional requirements

- **FR-001** — No error message may assert an auth posture that contradicts the hub's
  running mode. Specifically, the `missing X-Agent-Name` 400 must not claim the hub does
  not authenticate when it does.
- **FR-002** — The message must say what the caller should do *given the actual mode*. On
  an enforcing hub the name header is required **in addition to** a credential; that is
  the fact worth stating.
- **FR-003** — Auth-describing text must be derived from the configured mode at response
  time, not from a literal fixed at authoring time.
- **FR-004** — All three modes (`off`, `warn`, `enforce`) must produce coherent text. The
  `warn` mode is the one most likely to be got wrong, since it both authenticates and
  tolerates failure.
- **FR-005** — An audit: any other user-facing string describing authentication must be
  checked against the same rule. The reported instance is unlikely to be the only one, and
  finding the rest is part of the work rather than a follow-up.

## Non-functional requirements

- **NFR-001** — Messages stay legible to an LLM caller deciding what to do next, matching
  the standard already set by `unknown_recipient`.
- **NFR-002** — No new request-time cost; the mode is already known to the hub.

## Test matrix

| Case | Expected |
|---|---|
| `enforce`, token, no name header | 400 that does **not** claim the hub is unauthenticated |
| `enforce`, no token | unchanged `not_authenticated` |
| `off`, no name header | 400 whose description of auth is true for an open hub |
| `warn`, no name header | text coherent with warn semantics |
| All modes | no response text contradicts `GET /`'s advertised `authenticated` value |
| Grep audit | no hardcoded literal asserting an auth posture outside the derivation point |

The last two rows are the ones that prevent recurrence; the first four only fix what was
reported.

## Open questions for the human

1. ~~**What are `warn` mode's exact semantics** in caller-facing terms?~~
   **Answered 2026-08-06, from the code rather than from argument: caller-facing, `warn`
   is `off`.**

   `resolve_verified_caller` fails, `provide_caller` logs *"unauthenticated %s %s served
   in warn mode"* — and then serves the request on the header identity. A caller in
   `warn` gets exactly what a caller in `off` gets. The mode's entire value is to the
   *operator*, who can watch the log to see who would break before switching to
   `enforce`.

   The consequence is the one this mission is named after: **a hub in `warn` must tell
   agents what an `off` hub tells them** — anyone who can reach it can claim any name.
   Saying anything softer would be precisely the untruthful text the mission exists to
   remove. `warn` is a migration aid, not a security posture, and describing it as one
   would be a lie by implication.

   (superseded question follows)
   **What are `warn` mode's exact semantics** in caller-facing terms? The text cannot be
   written honestly until that is settled, and it is a product question rather than an
   implementation detail.
2. **Should this be folded into the live-suite mission?** The host's advice is no — keep
   them separate and cross-linked, since this is smaller and more UX/debugging-facing.
   Recorded here so the human can overrule it deliberately.

## Out of scope

- Changing which routes authenticate, or the auth model itself.
- The live smoke suite — cross-linked sibling mission.
- Console copy, except where it makes the same contradictory claim, which the FR-005
  audit will reveal.

## Provenance

Found incidentally while classifying the empty-recipient defect on examplehub 0.21.1 — the 400
appeared en route to reproducing something else. `ludmila_coe` classified it as a fourth
defect and placed it #3, noting it belongs to an `auth-mode truthfulness` theme with the
live-suite mission.

Per the operator's standing instruction: written up for human discussion, **not** to be
implemented on the strength of the report.
