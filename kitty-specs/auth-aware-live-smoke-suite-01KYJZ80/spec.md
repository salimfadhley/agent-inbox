# Spec — live smoke tests that know what kind of hub they are pointed at

- Mission: `auth-aware-live-smoke-suite-01KYJZ80`
- Raised by: `ludmila_coe` (host), **#2** on her revised list, 2026-07-27
- Evidence from: `nicole_ruzickova`, validating the v0.21.1 deploy on examplehub
- Related: [`auth-mode-truthful-error-text-01KYJZ81`](../auth-mode-truthful-error-text-01KYJZ81/spec.md) — same `auth-mode truthfulness` theme, deliberately separate mission
- Status: **in implementation, 2026-08-03.** The operator selected both-modes-in-CI on
  2026-07-28. **Both open questions are now closed:** question 1 was resolved in v0.23.0
  (recorded below), and question 2 — own compose file or an override — is answered by its
  own reasoning: an override, because the compose file is itself part of what the smoke
  job validates, and a second one would mean the thing under test is not the thing that
  ships.

## What this is

`tests/live/` assumes a hub with authentication **off**. Pointed at a hub that enforces
it, most of the suite fails for reasons that have nothing to do with the deployment being
broken.

Observed against examplehub (`AGENT_MAILBOX_AUTH_MODE=enforce`) on 0.21.1:

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
{"name": "examplehub", "version": "0.21.3", "authenticated": true, "note": "This hub requires authentication…"}
```

So the suite reads that first and asserts what is true for the hub in front of it.

This has a second benefit worth stating: a suite that reads the advertised mode can also
check the advertisement is *honest*, which is a defect class nothing currently covers.

**Both modes run in CI** (operator decision, 2026-07-28).

A correction to an earlier draft of this spec, which claimed CI had no deployment to test
against. It does, and has all along — the `smoke` job builds the image, runs the real
compose topology, and already executes `tests/live`:

```yaml
- name: Run the live smoke tests
  env:
    LIVE_HUB_URL: http://localhost:8080
    LIVE_CONSOLE_URL: http://localhost:8082
  run: uv run pytest tests/live -v
```

So the **open** path has continuous cover. The **enforcing** path — what examplehub and every
production hub actually run — has none. That is the gap, and it is the more valuable half:
an auth regression today reaches production without any test having a chance to see it.

Running both also makes the suite prove its own mode detection, by exercising both
branches on every push. A mode-aware suite that only ever meets one mode is a mode-aware
suite in name.

### Getting a credential in CI, unattended

The enforcing pass needs a device token, and minting one requires an **operator** session
(`provide_operator`), which means password plus TOTP. That is automatable today with no
product change, using only public surface:

1. Start the hub with `AGENT_MAILBOX_AUTH_MODE=enforce`.
2. Take the initial admin password from the container log — the hub emits
   `initial admin password: …` on first run.
3. `GET /auth/enrol` for a TOTP secret and recovery codes.
4. Compute a code with `agent_mailbox.auth.totp`.
5. `POST /auth/enrol` to finish first-run and obtain a session.
6. `POST /auth/agents/{name}/tokens` to mint the device token.

Worth noticing what that buys beyond a credential: it exercises the **entire operator
bootstrap chain** — first-run password, enrolment, 2FA, session, token mint — live, on the
shipped image. Nothing tests that today, and it is the path every new deployment takes
exactly once, at the moment when getting it wrong is most expensive.

Step 2 is the weak link: scraping a log line is fragile, and the line is not a contract.
See open question 1.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | The suite fetches `GET /` first and records the advertised auth mode. If that fetch fails it stops immediately with a clear message, rather than proceeding to produce misleading per-test failures. | planned |
| FR-002 | Every live assertion is expressed against the recorded mode: expected status codes and expected console copy both follow from it. | planned |
| FR-003 | **Negative check:** a hub advertising `authenticated: true` while a protected route answers unauthenticated is a failure. Only possible once the suite reads the advertisement, and it catches a hub whose claims and behaviour disagree. | planned |
| FR-004 | Auth-relevant tests are named or marked so `-k auth` selects them, rather than deselecting all 11 as it does today. | planned |
| FR-005 | Credentials come from the environment, never from repo files. Against an enforcing hub with no credential the suite skips with a stated reason — distinguishing "cannot test this" from "this failed". | planned |
| FR-006 | The suite reports what it did not run. A run where everything skipped must not look like a clean pass. | planned |
| FR-007 | CI runs the suite twice: against the existing open hub, and against one started with `AGENT_MAILBOX_AUTH_MODE=enforce`. Both must pass for the job to pass. | planned |
| FR-008 | The enforcing pass obtains its own credential unattended by the bootstrap chain above. No secret in the repository, and none configured as a CI secret — the hub is created fresh for the run and destroyed with it. | planned |
| FR-009 | The bootstrap is asserted, not merely used. If first-run enrolment or token minting breaks, the job fails *saying so*, rather than surfacing as a confusing auth failure in an unrelated live test. | planned |
| FR-010 | The enforcing pass fails if it ends up running unauthenticated. A credential that turns out not to be needed would make the entire second pass vacuous — the failure shape this mission exists to remove from live validation. | planned |
| FR-011 | The suite reads `adminPasswordSet` from `GET /` and treats a hub running the low-security admin override as **not** fully secured, however `authenticated` reads. Added after v0.23.0; without it a hub with a deliberate hole in its front door passes the same assertions as one without. | planned |
| FR-012 | If CI's enforcing pass uses `AGENT_MAILBOX_ADMIN_PASSWORD` to obtain its session, it must assert the hub advertises the override — so the pass can never quietly be testing a *weaker* hub than the one it claims to validate. | planned |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | No deployment hostnames in the repo. | Hub and console come from `LIVE_HUB_URL` / `LIVE_CONSOLE_URL`, per the generic-only rule in `AGENTS.md` | planned |
| NFR-002 | A failure is diagnosable from its own output. | The failure names the mode the suite assumed, so a wrong assumption is visible without re-running | planned |
| NFR-003 | The second CI pass does not materially slow the job. | The enforcing pass reuses the built image; no second build | planned |

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
| CI, open pass | passes, as today |
| CI, enforcing pass | passes, having minted its own token |
| CI, enforcing pass with the credential removed | **fails** — proves the pass is not vacuous |
| CI, first-run bootstrap broken | fails naming the bootstrap, not some downstream test |

## Open questions for the human

1. ~~**Is scraping the initial admin password from the log acceptable, or should the hub
   gain a documented bootstrap?**~~ **RESOLVED in v0.23.0 — both, and the second is
   bigger than this mission asked for.**

   The operator's answer was that every essential feature should be tested, so the log
   line is now a contract: `INITIAL_PASSWORD_LOG_PREFIX` is a named constant asserted by
   `tests/test_auth_bootstrap.py`, and rewording it fails a test that says why.

   They also added the environment variable — but as `AGENT_MAILBOX_ADMIN_PASSWORD`, a
   **standing low-security mode** rather than a first-run seed. Set it and `admin` signs
   in with no second factor, at any time, with authority to reset passwords and manage
   tokens. That is deliberate: recovering a hub whose authenticator is lost is exactly
   the case where the account is already enrolled, so a setup-only variable would not
   have helped.

   **What this changes for WP03:** the bootstrap chain no longer has to walk enrolment
   and TOTP at all. CI can set `AGENT_MAILBOX_ADMIN_PASSWORD` on its throwaway enforcing
   hub and log in directly, which removes five of the six steps and the whole class of
   risk that made WP03 the mission's most dangerous package. The log-scraping chain
   remains valid and is now contract-backed, so either route works.

   **A new requirement falls out of it:** the hub advertises `adminPasswordSet` at
   `GET /`, so the live suite should assert that a hub claiming `authenticated: true`
   while running the override is not mistaken for a properly secured one. That is FR-003's
   honesty check with a second dimension — see the amendment below.
2. **Should the enforcing pass use its own compose file or the existing one with an
   override?** An override keeps one topology definition, which matters because the
   compose file is itself part of what the smoke job validates.

## Out of scope

- Changing which routes require authentication. This mission tests the hub as it is.
- The auth-mode-contradicting **error text** — cross-linked sibling mission, kept separate
  on the host's advice because owners, blast radius and acceptance differ.
- Adding live tests for behaviour not already covered.

## Provenance

Raised by `ludmila_coe` as #2 on her revised list, promoted above the smaller UX items
because "current false red tests train operators to ignore live validation". The
one-suite decision and the FR-003 negative check are hers; the failure evidence is from
validating the v0.21.1 deployment on examplehub.

Per the operator's standing instruction: written up for human discussion, **not** to be
implemented on the strength of the report.
