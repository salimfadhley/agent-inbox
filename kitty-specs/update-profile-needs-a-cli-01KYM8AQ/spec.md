# Spec — the CLI must be able to set a profile

> **Audited and closed 2026-08-03.** Verified implemented in the code, not merely
> specified. This folder is history; nothing in it is outstanding work.

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

## Reframed, 2026-07-28 — the request is narrower than the need

The issue asks for a write command. Taken literally that is what would be built, and it
would be half a feature.

**Reading and writing are one package, not a command and a nice-to-have.** The write
*replaces* the whole profile, so a caller who cannot see the current value is being asked
to overwrite something they cannot read. That is not a convenience gap; it is the write
command being unsafe on its own. FR-005 is therefore core, not an addition, and this
mission ships both or neither.

Two things visible from inside the codebase, which the reporter could not have known,
support widening it slightly:

- **The console has the same gap.** It reads `profile` in four places and cannot write it.
  So "the CLI is missing a command" is really "the write path exists on one surface of
  three", which is a different and more accurate problem statement.
- **Profiles are about to become load-bearing.**
  [#7](https://github.com/salimfadhley/agent-inbox/issues/7) wants presence metadata drawn
  from them and [#9](https://github.com/salimfadhley/agent-inbox/issues/9) wants
  structured roster fields. Both assume profiles are populated. Today they are populated
  only by agents that happen to speak MCP — 7 of 20 actors, all MCP-connected.

The symptom in the report stands unchanged: an onboarding instruction that cannot be
followed. Nothing here replaces it; the scope around it is corrected.

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
| FR-005 | **Core, not an addition.** The profile can be **read** from the CLI. A write that replaces the whole object is unsafe without a way to see the current one, so read and write ship together or not at all. | planned |
| FR-008 | Read must be usable as input to write without hand-editing — the output is the JSON the write accepts, so `show` into an editor and back through `set` is a working loop rather than a retyping exercise. | planned |
| FR-006 | The onboarding prompt's instruction becomes true for a CLI-only agent — either it works, or the prompt says which surfaces it applies to. It must not continue to instruct something impossible. | planned |
| FR-007 | Documented in the README command table alongside the other verbs. | planned |
| FR-009 | `update-profile` exists as a thin alias for `profile set`, or failing that as an error naming it. It catches the agent translating the MCP tool name literally at a shell — which is precisely the agent this issue is about. A command that does not exist teaches them they misunderstood; a signpost does not. | planned |

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

## Open questions

1. ~~**Command shape.**~~ **Settled: `profile show` and `profile set '<json>'`**, with
   `update-profile` as a thin alias. Agreed with `ludmila_coe`, whose reasoning is worth
   keeping rather than just the conclusion:

   - replace semantics make `show` practically necessary, or the CLI adds a field-loss
     footgun;
   - `set` groups the write beside the read and matches the existing `config set` idiom;
   - it leaves room for later `profile` subcommands without inventing a second naming
     family;
   - the onboarding prompt can name the CLI form explicitly while MCP keeps
     `update_profile` as its tool name.

   **The alias is hers and it is the better idea.** It exists for exactly the agent this
   issue is about: one reading `update_profile` in MCP-oriented text and translating it
   literally at a shell. A command that does not exist teaches that agent it has
   misunderstood; an alias — or at minimum an error naming `profile set` — turns a dead
   end into a signpost. Not canonical, just a catch.

2. **Should the console get a form too?** It reads profiles in four places and cannot
   write them, so it has the same gap. Out of scope here — different surface, different
   work — but #9 will want one, and doing both together may be cheaper than twice.

## Out of scope

- A `--merge` mode (see Decisions).
- Structured or validated profile fields — that is [#9](https://github.com/salimfadhley/agent-inbox/issues/9).
- A console form (see open question 2).

## Provenance

Filed as issue #4 by an admin-role agent following the triage practice in
`doc/runbook/admin.md`, confirmed live against `agent-inbox==0.23.1`. Every claim in the
report reproduced: the counts above were taken by reading the four modules, so the cause
here is **code-confirmed** rather than inferred.

**The reporter cannot currently be reached.** Issue #5's own reproduction names them
`zakhar_shchukina`; no such actor exists on this hub. I inferred from their use of
`http://localhost:8080` that they had joined a different hub — `ludmila_coe` checked and
narrowed that: on this machine `localhost:8080` currently resolves to the same hub, so the
address is not by itself evidence of a second one. What is evidence is that their
reproduction shows `role zakhar_shchukina` returning `known: true` while it now returns
`known: false`. So: a different hub *context* at the time, not necessarily a different hub
now, and no route to them from here. Their feedback was requested on the ticket, which is
the only channel known to reach them.

Worth carrying beyond this mission: **useful, accurate reports are arriving from an agent
neither the admin nor the host can contact.** Whatever is decided here, that is a gap in
the feedback loop rather than a detail of this issue.
