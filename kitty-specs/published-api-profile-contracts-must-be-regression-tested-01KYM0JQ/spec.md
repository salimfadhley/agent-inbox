# Spec — published behaviour claims need regression tests

- Mission: `published-api-profile-contracts-must-be-regression-tested-01KYM0JQ`
- Found by: `nicole_ruzickova`, 2026-07-28, answering a question from `ludmila_coe`
- Shaped by: `ludmila_coe` — title, acceptance criteria and the standalone/cross-link call
- Related: [`prompt-must-tell-the-truth-about-auth-01KYKZM4`](../prompt-must-tell-the-truth-about-auth-01KYKZM4/spec.md)
  — same failure shape, different artifact
- Status: **specified, not started.**

## What this is

`API_DESCRIPTION` in `api.py` is the source of the published API profile — the text
Litestar renders into `/schema/openapi.json`, and which its own comment describes as
"the handful of behaviours that are decisions rather than types, and that a client author
would otherwise have to discover by experiment".

**No test asserts anything about its content.**

Found by being asked. Ludmila asked whether the cursor contract added in v0.23.1 was
"versioned/tested alongside OpenAPI so the cursor contract cannot drift again". It is not.
I confirmed the paragraph reaches `/schema/openapi.json` by fetching it, which proves it
is *wired*, not that it will *stay*.

## Why it matters

Documentation that exists to prevent experimentation is load-bearing, and this project has
just been shown what happens when load-bearing generated text is unprotected.

The onboarding prompt drifted into telling every agent that an authenticating hub does not
authenticate, and did so behind a published claim that it "never goes stale". Nothing
caught it, because nothing asserted the claim it was making. `API_DESCRIPTION` is the same
kind of artifact with the same absence of cover — and its failure would be quieter still,
because its audience is external client authors who have no way to know the document is
wrong and every reason to trust it.

The cursor contract is the concrete case in front of us. Every sentence of it was written
because getting it wrong has a real cost, all of them measured this week:

- there is always a cursor, including on an empty inbox → otherwise a caller stores `""`
  and later re-reads mail;
- it is a filter the caller owns, not hub state → otherwise two sessions sharing a name
  hide mail from each other;
- it is opaque → otherwise a client parses `<published>|<id>` and we can never change it;
- percent-encode it → otherwise the filter silently matches everything.

Each is a behaviour someone could "tidy" out of the profile without touching a line of
code, and no test would notice.

## Decisions taken

**Its own mission, cross-linked — not folded into the prompt one.** Ludmila's
recommendation and reasoning, adopted:

- same failure shape, different artifact (prompt text vs API profile text);
- different audience (every agent at session start vs external client authors);
- different regression surface (console/prompt tests vs `/schema/openapi.json` content);
- a prompt fix could be entirely correct and still leave this untested, so bundling would
  hide an independent acceptance condition behind someone else's green tick.

**Assert contracts, not prose.** Test that the required *claims* are present, not that
the text matches a snapshot. A large string comparison would break on every improvement to
the wording and teach people to update the fixture without reading it — which is how a
test stops being a test.

**Assert against the generated document, not the constant.** Reading `API_DESCRIPTION`
directly would pass even if it were no longer wired into the schema. The test must fetch
`/schema/openapi.json` the way a client author does.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | A test asserts the cursor contract is present in `/schema/openapi.json`: always present including on an empty inbox; caller-owned filter rather than hub state; opaque; percent-encode in URLs. | planned |
| FR-002 | Assertions run against the **generated** document, not the module constant, so a profile that is no longer wired in fails. | planned |
| FR-003 | Assertions are per-claim, not a snapshot of the whole string, so wording can improve without losing a required claim. | planned |
| FR-004 | Any auth-mode-sensitive prose in the profile is either derived from the hub's actual mode or absent. The profile currently states `authenticated: false` means the header is taken at face value — that is a description of a *field*, not a claim about this hub, and the distinction must survive. | planned |
| FR-005 | A contributor note records the rule: published documentation making behavioural claims needs a regression test when it exists to replace client-author experimentation. | planned |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | The tests do not make the profile hard to edit. | Improving wording without changing meaning keeps them green | planned |
| NFR-002 | Failure output says which claim went missing. | The message names the contract, not just "string not found" | planned |

## Test matrix

| Case | Expected |
|---|---|
| Each cursor claim | present in the generated document |
| Profile no longer passed to `OpenAPIConfig` | fails — this is FR-002's whole point |
| Wording improved, meaning kept | still green |
| A required claim deleted | fails, naming the claim |
| Auth-mode prose | describes the field's meaning, never asserts this hub's posture |

The second row is the one that would have caught the shape of the prompt bug, and it is
the row a snapshot test would get wrong.

## Open questions for the human

1. **How far does this extend?** The same argument applies to the MCP tool docstrings and
   the onboarding prompt, which are also generated text carrying behavioural claims. This
   spec covers the API profile only. A general rule may be right, but writing one before
   there are two worked examples would be guessing at the shape.
2. **Is the console's rendered prompt page in scope**, or only machine-facing documents?

## Out of scope

- The prompt's auth claim — cross-linked sibling mission.
- Rewriting the profile. This is about protecting what it says, not changing it.

## Provenance

Ludmila asked whether the contract was protected; the honest answer was no, and finding
that out took one grep. She then supplied the title, the acceptance shape, and the
argument for keeping it standalone. The broader lesson she asked to have recorded, and
which both missions share: **generated or published documentation must have tests for its
critical behavioural claims, especially where those docs are the replacement for copied
setup instructions or black-box experimentation.**
