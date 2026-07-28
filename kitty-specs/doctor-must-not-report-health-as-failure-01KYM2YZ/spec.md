# Spec — `doctor` must not report health as failure

- Mission: `doctor-must-not-report-health-as-failure-01KYM2YZ`
- Issue: [#2](https://github.com/salimfadhley/agent-inbox/issues/2)
- Reported by: an admin-role agent, 2026-07-28, with a live reproduction
- Confirmed by: `nicole_ruzickova` — cause **code-confirmed**, not inferred
- Status: **specified, not started.**

## What this is

`doctor` returns exit code `2` for three different situations, and one of them is the
healthy first-run state of every new agent.

```
$ agent-inbox doctor --hub http://localhost:8080
--   configuration   no entry for this engine yet
--   identity        none yet — ask the hub for one below
ok   unique names    one name per engine
ok   connectivity    http://localhost:8080 — agent-inbox 0.23.1
ok   credentials     none needed — this hub does not authenticate
ok   hub check       this hub has no actor named 'unnamed' — join to claim it
--   api             not joined yet
$ echo $?
2
```

Every check that ran returned `ok`. Nothing is broken. The tool says "you are fine, run
`join` next" — and exits as though something failed.

## The code already disagrees with itself

Not an oversight that has to be inferred. Both relevant comments state the intended
behaviour, and the code next to them does the opposite.

`cli.py:657`, opening the configuration check:

> Having none is the **normal** state before `join`, not an error

`cli.py:842`, immediately above the third `return 2`:

> Reachable, and nothing is in the way — but we are nobody here yet. This is the end of
> the road for an unjoined engine, and **it is a good outcome**: it says the next step
> will work.

Then `return 2`.

This is the third defect of that exact shape found in this repository in two days — a
comment describing behaviour the code does not have. In every case the comment was right.
Worth noting as a review heuristic: a comment arguing *against* the line beneath it is
evidence, not decoration.

## Why it matters more than an unusual exit code

**It is the first command a new agent runs.** `doctor` is named in the onboarding prompt
as the self-check, and in `doc/runbook/admin.md` as a session-start step. So the case that
exits non-zero is not an edge case — it is the *entry* case, hit by every new install
before anything else.

**It defeats the obvious way to use the tool.** Treating non-zero as "something is wrong"
is what a wake hook, a provisioning script or a CI step will do. Under that reading, a
brand-new healthy agent is indistinguishable from an unreachable hub. The tool built to
diagnose confusion becomes a source of it.

**It is the project's own recurring defect shape, inverted.** `AGENTS.md` records the
family: a check that passes because it had nothing to look at. This is the mirror image —
a check that *fails* because it had nothing wrong to report. Same root: the outcome does
not follow from the evidence.

## Decisions taken

**`0` for "healthy, action suggested".** The not-joined-yet case exits 0. It is the state
the comment already calls a good outcome, and the state every new agent passes through.

**`2` stays for genuine blockers.** No hub url, and an ambiguous engine, both keep their
current code. They are real: something must change before the tool can proceed.

**No new exit codes in this mission.** The issue suggests distinct codes per case, and
that is deliberately *not* adopted here. Exit codes are a contract: anything currently
treating non-zero as "look at this" keeps working under a `0`/`2` split, but a
`0`/`2`/`3`/`4` split invites callers to branch on numbers nobody has written down. If
finer granularity is wanted it should be its own decision, with the codes documented as
an interface. Fixing the false failure does not require it.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | A `doctor` run where every executed check passed and the only outstanding step is `join` exits **0**. | planned |
| FR-002 | No hub url configured continues to exit **2**. | planned |
| FR-003 | An ambiguous engine (several configured, none selected) continues to exit **2**. | planned |
| FR-004 | The human-readable output is unchanged. This mission changes an exit code, not a report — the text already says the right thing. | planned |
| FR-005 | The exit-code contract is documented where `doctor` is described, so the meaning of 0 and 2 is stated rather than discovered. | planned |
| FR-006 | The comments at `cli.py:657` and `cli.py:842` are reconciled with the code — kept and made true, not deleted to end the disagreement. | planned |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | No new dependency between checks. | The exit code is derived from what the checks already found; no check is re-run to decide it | planned |
| NFR-002 | A genuine failure can never exit 0. | Any `FAIL` line forces a non-zero exit, whatever else passed | planned |

## Test matrix

| Case | Expected |
|---|---|
| Hub reachable, nothing configured, not joined | **0** |
| Hub reachable, joined and healthy | 0 (unchanged) |
| No hub url anywhere | 2 |
| Two engines configured, none selected | 2 |
| Hub unreachable | non-zero (unchanged) |
| Hub reachable but rejects credentials | non-zero (unchanged) |
| Any run containing a `FAIL` line | non-zero — NFR-002 |

The last row is the one that stops this fix from becoming the opposite defect. Widening
"exit 0" is exactly the change that could make a real failure silent, and that would be
worse than what is being fixed: a false alarm wastes attention, a missed alarm wastes
trust.

The first row must be watched failing before the fix, since it is the whole mission.

## Open questions for the human

1. **Should `doctor` gain a `--quiet` or machine-readable mode?** Out of scope, but the
   reason this exit code matters is that scripts consume it, and a script parsing the
   human text is the next problem along. Worth knowing whether that is wanted before
   someone builds it by accident.

## Out of scope

- Distinct codes for each blocker (see Decisions).
- Any change to what `doctor` checks or prints.
- The em-dash encoding defect in the same output — [#3](https://github.com/salimfadhley/agent-inbox/issues/3),
  separate mission, same command.

## Provenance

Filed as issue #2 by an admin-role agent following the triage practice in
`doc/runbook/admin.md`, with a live reproduction against `agent-inbox==0.23.1`. The three
`return 2` sites and both contradicting comments were confirmed by reading `cli.py`, so
the cause here is **code-confirmed** rather than inferred — using the reporting split
agreed with `ludmila_coe`.
