# Spec — the onboarding prompt must tell the truth about authentication

- Mission: `prompt-must-tell-the-truth-about-auth-01KYKZM4`
- Reported by: `ludmila_coe` (host), 2026-07-28 07:48 UTC, with a repro, to `admin`
- Confirmed by: `nicole_ruzickova` against halob 0.23.1
- Related: [`auth-mode-truthful-error-text-01KYJZ81`](../auth-mode-truthful-error-text-01KYJZ81/spec.md)
  — same *auth-mode truthfulness* theme, deliberately separate (see below)
- Status: **specified, not started.**

## What this is

The hub says one thing about itself and its own onboarding prompt says the opposite.

`GET /` on halob 0.23.1:

```json
{"authenticated": true,
 "note": "This hub requires authentication: agents present a device token as a Bearer credential…"}
```

`/prompts/agent`, line 294 of the page every agent is told to read:

> **This mailbox does not authenticate.** Anyone who can reach it can claim to be anyone.
> That is fine on a trusted network, and it is not a secret channel.

## Why it matters more than the sibling defect

`auth-mode-truthful-error-text-01KYJZ81` is the same *kind* of wrong. This one is worse
on every axis that counts:

- **Reach.** That error text appears on an uncommon 400. This appears on the page the
  project instructs *every* agent to read *at the start of every session*.
- **It is load-bearing.** The prompt is the one document this project tells people not to
  copy, precisely so it always reflects the running hub. `doc/agent-prompt.md` exists to
  make that argument.
- **It falsifies a published claim.** `README.md` says the prompt is generated "from the
  running version, so what an agent reads always matches what is deployed", and "never
  goes stale the way a pasted copy does". For auth posture, both sentences are false.
- **It teaches the wrong threat model.** An agent told the channel is unauthenticated may
  reasonably decide a credential is not worth having, treat what arrives as more suspect
  than it is, or describe the hub's properties wrongly to its own human.

## Cause — confirmed by reading, not inferred

The signature is the whole story:

```python
def onboarding(hub_url: str, prompt_url: str = "", version: str = "") -> str:
```

**The generator is never told the auth mode.** The sentence at `prompts.py:394` is a
hardcoded literal, so the prompt cannot describe an authenticating hub even in principle.
This is not a conditional that went wrong; it is a missing input.

That distinction matters for scoping: the sibling error-text mission can derive from a
value the hub already has at the point of failure, while this one requires plumbing the
mode into prompt generation and through every caller
(`console.py:1117`, `console.py:1139`, `release_gate.py:86`).

**The wrong behaviour is currently pinned by a test.** `tests/test_console.py:512`:

```python
assert "does not authenticate" in console.get("/prompts.txt").text
```

Anyone fixing this must change that assertion. Left as-is it would make the correct
behaviour fail CI — the test encodes the bug, so it has to be part of the work rather
than a surprise found halfway through.

## Decisions taken

**Separate mission from the error-text one, cross-linked.** Answering ludmila's question
directly: treat it as a distinct prompt-generation issue, not a sub-case of the
watchpoint. Different surface, different blast radius, and different fixes — one needs a
new input plumbed through three callers, the other needs derivation from a value already
in hand. Bundling would force one accept-or-reject decision over work of very different
size and risk.

**Derive, never restate.** Same rule as the sibling: the prompt must describe the posture
by asking the hub, not by carrying its own sentence about it.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | The onboarding prompt describes the auth posture of the hub actually serving it. On an enforcing hub it must not claim the mailbox does not authenticate. | planned |
| FR-002 | `onboarding()` takes the auth mode as an input. Every caller supplies it — the console prompt page, the console's copyable text, and the release gate. | planned |
| FR-003 | All three modes (`off`, `warn`, `enforce`) produce coherent text. `warn` is the one most likely to be got wrong and shares an open question with the sibling mission. | planned |
| FR-004 | On an authenticating hub the prompt says what an agent must actually *do* — present a device token — rather than only dropping the caution. Removing a false sentence without adding the true one leaves an agent no better off. | planned |
| FR-005 | `tests/test_console.py:512` is corrected rather than deleted: it should assert the caution appears on an **open** hub and is absent on an enforcing one. | planned |
| FR-006 | The README claims that the prompt "always matches what is deployed" and "never goes stale" are made true, or narrowed to what is actually guaranteed. | planned |
| FR-007 | A test pins prompt text against hub posture, so this cannot drift back silently. Prompt content is currently asserted only in fragments. | planned |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | No network call to render a prompt. | The mode is passed in, not fetched — the console already holds it from `hub_info` | planned |
| NFR-002 | The release gate keeps working. | `release_gate.py:86` calls `onboarding()` and must not break on the new signature | planned |

## Test matrix

| Case | Expected |
|---|---|
| Enforcing hub, `/prompts/agent` | no "does not authenticate"; says a device token is required |
| Open hub, `/prompts/agent` | caution present, as today |
| `warn` hub | coherent with warn semantics — blocked on the shared open question |
| Prompt vs `GET /` | the prompt's posture and `authenticated` never disagree |
| Console copyable prompt text | same posture as the served page |
| Release gate | still extracts the install floor unchanged |

The fourth row is the durable one, and it is the same shape as FR-003 in the live-smoke
mission: assert the hub's surfaces agree with each other rather than pinning each
separately. Two surfaces pinned independently can both pass while contradicting.

## Open questions for the human

1. **`warn` mode's caller-facing meaning** — shared with
   `auth-mode-truthful-error-text-01KYJZ81`, and should be answered once for both.
2. **Does the prompt need to change what it says about trust generally**, or only about
   authentication? The current caution bundles "anyone can claim any name" with "this is
   not a secret channel". The second remains true on an enforcing hub; only the first
   stops being.

## Out of scope

- Error strings — the sibling mission.
- Changing what is authenticated.
- The `admin` postbox report itself; ludmila has already routed it.

## Provenance

Reported by `ludmila_coe` at 07:48 UTC to `admin` with a repro, and raised with admin
directly at 09:05 UTC asking whether it belonged to the existing watchpoint or was its
own issue. Confirmed against halob 0.23.1 the same morning, and the cause read out of
`prompts.py` rather than guessed — per the reporting split she proposed in the same
message, this spec's cause is **code-confirmed**, not a hypothesis.
