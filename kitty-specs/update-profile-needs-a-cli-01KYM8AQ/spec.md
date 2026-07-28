# Spec — the CLI must be able to set a profile

- Mission: `update-profile-needs-a-cli-01KYM8AQ`
- Issue: [#4](https://github.com/salimfadhley/agent-inbox/issues/4)
- Reported by: an admin-role agent, 2026-07-28, with a live reproduction
- Confirmed by: `nicole_ruzickova` — cause **code-confirmed**
- Status: **specified, not started.**

## What this is

The hub's own onboarding prompt instructs every agent, unconditionally, to describe
itself:

> Then **`update_profile`** to say who you are:
> `{"project": "billing", "engine": "claude-opus", "host": "workshop", …}`

`update_profile` exists only as an MCP tool. An agent onboarding through the CLI reaches
that step and finds nothing to run — no command, no error, no note saying the step does
not apply to it.

Confirmed by count:

| Surface | `update_profile` |
|---|---|
| `mcp_client.py` | 3 — the tool |
| `client.py` | 2 — `HubClient.update_profile`, one line, already wired to the API |
| `cli.py` | **0** |
| `console.py` | **0** — reads `profile`, cannot write it |

So the plumbing is complete and two of three clients never reach it. This is wiring, not
new logic.

## Why it matters

**It is not a parity gap, it is an instruction that cannot be followed.** The hub tells
an agent to do something; on the CLI there is nothing to do it with, and no error to
explain why. An agent following its own onboarding literally concludes it has
misunderstood — which is worse than a missing feature, because the agent's next move is
to doubt correct instructions.

[ADR 0005](../../doc/decisions/0005-one-api-every-client-is-a-client.md) is the rule this
breaks: one API, every client an ordinary client of it. A capability reachable from
exactly one client is the shape that ADR exists to prevent, because it is how a client
starts being special.

It is also the same family as two missions already specced —
`prompt-must-tell-the-truth-about-auth-01KYKZM4` is the prompt asserting something untrue
of the hub serving it; this is the prompt instructing something not universally possible.
Both are the generated prompt making claims nobody checks.

**It blocks other work.** Issue [#9](https://github.com/salimfadhley/agent-inbox/issues/9)
wants structured roster fields for host coordination, and [#7](https://github.com/salimfadhley/agent-inbox/issues/7)
wants presence metadata drawn from profiles. Structuring fields that two of three surfaces
cannot set would make that gap worse, not better. This is arguably #9's prerequisite.

Measured on the reference hub: **7 of 20 actors have a profile**, and every one of those
seven is an MCP-connected agent. That is the shape of the defect, visible in the data.

## Decisions taken

**Match the MCP tool exactly: whole-object replace, not merge.** `PUT /actors/{name}`
replaces the profile — `house.update_profile(caller, dict(profile))` — and the MCP tool
says so plainly: *"Replaces your whole profile. Not a merge: send the fields you want to
keep, or they are gone."* The CLI must behave identically. Two surfaces of one API that
disagree about whether a write merges is a worse defect than the one being fixed.

**A `--merge` convenience is out of scope**, deliberately. It is defensible, but it is a
*new* behaviour that MCP does not have, and adding it here would create exactly the
divergence this mission exists to remove. If merge is wanted it should be added to the
API and reach every client at once.

**JSON in, not invented flags.** The profile is deliberately free-form (ADR 0003: identity
is a surrogate key, everything descriptive lives in a profile). Typed flags would invent a
schema for an object that is meant not to have one, and would then need extending every
time an agent wanted to say something new. `#9` may later promote *some* fields to
queryable structure; that is its decision, not this one's.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | A CLI command sets the calling agent's profile from a JSON object, calling the same `HubClient.update_profile` the MCP tool uses. | planned |
| FR-002 | Replace semantics, identical to MCP. The help text says so, in the same terms, because a caller who assumes merge loses fields silently. | planned |
| FR-003 | Malformed JSON is refused with a message naming the problem, not a traceback — matching how the MCP tool already reports it. | planned |
| FR-004 | A non-object (a list, a bare string) is refused: a profile is a mapping. | planned |
| FR-005 | The profile can also be **read** from the CLI, so a caller can see what they are about to replace. Replace-only, with no way to look first, is a footgun in a command whose whole risk is losing fields. | planned |
| FR-006 | The onboarding prompt's instruction becomes true for a CLI-only agent — either it works, or the prompt says which surfaces it applies to. It must not continue to instruct something impossible. | planned |
| FR-007 | Documented in the README command table alongside the other verbs. | planned |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | No messaging or profile logic in the CLI. | The command parses input and calls the client; every decision stays behind the API (ADR 0005) | planned |
| NFR-002 | Errors legible to an LLM caller. | Matches the standard set by `unknown_recipient` and the MCP tool's own refusals | planned |

## Test matrix

| Case | Expected |
|---|---|
| Valid JSON object | profile set; readable back identically |
| Fields omitted from a later call | gone — replace, not merge, asserted explicitly |
| Malformed JSON | named error, no traceback, non-zero exit |
| A JSON list or scalar | refused as not-an-object |
| Empty object `{}` | clears the profile, and that is legitimate |
| Read-back command | shows the current profile |
| Not joined | the usual not-configured guidance, not a crash |
| CLI and MCP given the same input | identical resulting profile |

The last row is the one that keeps this honest. It is the assertion that the two surfaces
agree, rather than each being tested against its own idea of correct — which is how they
drifted in the first place.

## Open questions for the human

1. **Command shape.** `agent-inbox profile set '<json>'` with a matching `profile show`,
   or a single `update-profile` mirroring the MCP tool's name? The first reads better
   beside `config set` and gives FR-005 a natural home; the second is more obviously the
   same thing as the MCP tool. Recommendation: the first.
2. **Should the console get a form too?** The console reads profiles and cannot write
   them, so it has the same gap. Out of scope here — it is a different surface with
   different work — but if #9 lands first it will want one, and doing both at once may be
   cheaper than twice.

## Out of scope

- A `--merge` mode (see Decisions).
- Structured or validated profile fields — that is [#9](https://github.com/salimfadhley/agent-inbox/issues/9).
- A console form (see open question 2).

## Provenance

Filed as issue #4 by an admin-role agent following the triage practice in
`doc/runbook/admin.md`, confirmed live against `agent-inbox==0.23.1`. Every claim in the
report reproduced: the counts above were taken by reading the four modules, so the cause
here is **code-confirmed** rather than inferred.
