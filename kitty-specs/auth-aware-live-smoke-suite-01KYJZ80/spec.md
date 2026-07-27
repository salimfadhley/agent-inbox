# Spec — live smoke tests that know what kind of hub they are pointed at

- Mission: `auth-aware-live-smoke-suite-01KYJZ80`
- Raised by: `ludmila_coe` (host), **#2** on her revised list, 2026-07-27
- Evidence from: `nicole_ruzickova`, validating the v0.21.1 deploy on halob
- Related: [`auth-mode-truthful-error-text-01KYJZ81`](../auth-mode-truthful-error-text-01KYJZ81/spec.md) — same `auth-mode truthfulness` theme, deliberately separate mission
- Status: **specified, not started.** Awaiting human prioritisation.

## What this is

`tests/live/` assumes a hub with authentication **off**. Pointed at a hub that enforces
it, most of the suite fails for reasons that have nothing to do with the deployment being
broken.

Observed against halob (`AGENT_MAILBOX_AUTH_MODE=enforce`) on 0.21.1:

```
LIVE_HUB_URL=http://<hub>:8081 LIVE_CONSOLE_URL=http://<console>:8080 \
  uv run pytest tests/live -p no:warnings
→ 5 failed, 3 passed, 3 skipped
```

Every failure is the hub doing exactly the right thing:

| Failure | Cause |
|---|---|
| `/observe/mailbox/admin` → 401 | route protected; test expects it open |
| `/observe/purge/status` → 401 | same |
| `join` → 401 | same |
| thread read → `not_authenticated` body where a dict was expected | same |
| `test_the_console_serves_and_warns` | asserts the console shows `does not authenticate` — **correctly absent**, because this hub does authenticate |

## Why it matters

**Five red tests that mean nothing teach an operator to ignore live validation.** That is
the actual damage: not the failures themselves but what they do to the habit. The live
suite is the last check before a deployment is trusted, and it currently cries wolf on
exactly the deployments that matter most — the enforcing, production-shaped ones.

The `LIVE_AUTH=1` variants exist, but the intuitive way to reach them finds nothing:

```
pytest tests/live -k auth   →  11 deselected, 0 selected
```

So an operator who notices the auth tests exist still cannot easily run them.

There is also a silent-skip hazard of the same family recorded in `AGENTS.md`: without
`-rs`, the three skipped tests are invisible, and a suite that skips everything reports a
clean run. **A skip is not a pass.**

## Decisions taken

**One auth-aware suite, not two modes.** The alternative — separate `live-open` and
`live-auth-enforced` suites selected by the operator — moves the decision to the person
least likely to know which mode a given hub is in, and gets it wrong silently.

The hub already advertises the answer. `GET /` returns:

```json
{"name": "halob", "version": "0.21.3", "authenticated": true, "note": "This hub requires authentication…"}
```

So the suite reads that first and asserts what is true for the hub in front of it.

This has a second benefit worth stating: a suite that reads the advertised mode can also
check the advertisement is *honest*, which is a defect class nothing currently covers.

## Functional requirements

- **FR-001** — The suite fetches `GET /` first and records the advertised auth mode. If
  that fetch fails, the suite fails immediately with a clear message rather than
  proceeding to produce misleading per-test failures.
- **FR-002** — Every live assertion is expressed against the recorded mode: expected
  status codes and expected console copy both follow from it.
- **FR-003** — **Negative check:** if the hub advertises `authenticated: true` but a
  protected route answers unauthenticated, that is a failure. This is the check that only
  becomes possible once the suite reads the advertisement, and it catches a hub whose
  claims and behaviour disagree.
- **FR-004** — Auth-relevant tests are named or marked so `-k auth` selects them rather
  than deselecting everything.
- **FR-005** — Credentials come from the environment, never from repo files, and the
  suite skips with a clear reason when an enforcing hub is named without a credential —
  distinguishing "cannot test this" from "this failed".
- **FR-006** — The suite reports what it did not run. A run where everything skipped must
  not look like a clean pass.

## Non-functional requirements

- **NFR-001** — No deployment hostnames in the repo. Hub and console come from
  `LIVE_HUB_URL` / `LIVE_CONSOLE_URL`, per the generic-only rule in `AGENTS.md`.
- **NFR-002** — Failure output must name the mode it assumed, so a wrong assumption is
  diagnosable from the failure alone.

## Test matrix

| Case | Expected |
|---|---|
| Open hub, no credential | full suite runs and passes |
| Enforcing hub, valid credential | full suite runs and passes |
| Enforcing hub, no credential | explicit skip with reason — not failure, not silent |
| Enforcing hub, protected route answers unauthenticated | **failure** (FR-003) |
| Hub advertises open but enforces | **failure**, with both observations reported |
| `pytest tests/live -k auth` | selects the auth cases |
| Console copy, enforcing hub | asserts the authenticated copy; does not require the warning |
| Console copy, open hub | asserts the `does not authenticate` warning is present |

## Open questions for the human

1. **Should CI run this against a real hub?** Today it cannot — CI has no deployment. The
   `smoke` job runs the compose topology, so an enforcing hub could be stood up there.
   That would be a larger change and is not assumed by this spec.
2. **Credential shape for the suite** — device token via environment is the obvious
   answer, but this should match whatever the operator flow actually is rather than
   inventing a test-only path.

## Out of scope

- Changing which routes require authentication. This mission tests the hub as it is.
- The auth-mode-contradicting **error text** — cross-linked sibling mission, kept separate
  on the host's advice because owners, blast radius and acceptance differ.
- Adding live tests for behaviour not already covered.

## Provenance

Raised by `ludmila_coe` as #2 on her revised list, promoted above the smaller UX items
because "current false red tests train operators to ignore live validation". The
one-suite decision and the FR-003 negative check are hers; the failure evidence is from
validating the v0.21.1 deployment on halob.

Per the operator's standing instruction: written up for human discussion, **not** to be
implemented on the strength of the report.
