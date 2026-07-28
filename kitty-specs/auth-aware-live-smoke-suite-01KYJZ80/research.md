# Research — auth-aware live smoke suite

Phase 0 for `auth-aware-live-smoke-suite-01KYJZ80`. Every finding below was observed
against running systems on 2026-07-27/28 — the deployed hub (examplehub) and this repository's
CI — rather than reasoned from the source. Where I reasoned instead of checking, and was
wrong, that is recorded too, because the corrections changed the mission.

## D-01 — The suite assumes an unauthenticated hub

**Decision:** treat this as the root defect, not the individual failing assertions.

**Evidence:** running the documented invocation against examplehub (`AUTH_MODE=enforce`,
v0.21.1) gave `5 failed, 3 passed, 3 skipped`. Every failure is the hub behaving
correctly:

| Failure | Actual cause |
|---|---|
| `/observe/mailbox/admin` | 401 — protected route, test expects open |
| `/observe/purge/status` | 401 — same |
| `join` | 401 — same |
| thread read | `not_authenticated` body where a dict was expected |
| `test_the_console_serves_and_warns` | asserts `does not authenticate` appears in console HTML — correctly absent |

**Rationale:** fixing the five assertions individually would leave the next
auth-dependent test to be written wrong in the same way. The suite needs a premise.

## D-02 — CI already runs the live suite. This corrects an earlier claim.

**Decision:** the gap is the *enforcing* configuration, not live testing as such.

**Evidence:** `.github/workflows/ci.yml`, `smoke` job — builds the image, runs
`docker compose up -d`, waits for hub and console, then:

```yaml
- name: Run the live smoke tests
  env:
    LIVE_HUB_URL: http://localhost:8080
    LIVE_CONSOLE_URL: http://localhost:8082
  run: uv run pytest tests/live -v
```

**Correction:** the first draft of `spec.md` stated CI had no deployment to test against,
and offered "should CI run this against a real hub?" as an open question. That was wrong,
and I had not looked. The open path has had continuous cover since the smoke job existed;
the enforcing path — what every production hub runs — has had none. This materially
raised the mission's value and changed the operator's decision, who chose to run both
modes rather than only fix local false-reds.

**Lesson, and it is the project's own:** the claim "CI cannot do this" was never checked.
It is the same shape as the defects in `AGENTS.md` — an assertion made without
establishing its premise.

## D-03 — One auth-aware suite, not two operator-selected modes

**Decision:** the suite reads the hub's advertised mode and asserts accordingly.

**Evidence:** the hub already advertises it. `GET /` on examplehub:

```json
{"name": "examplehub", "version": "0.22.0", "authenticated": true,
 "note": "This hub requires authentication: agents present a device token…"}
```

**Rationale:** the alternative — `live-open` and `live-auth-enforced` suites chosen by the
runner — relocates the decision to the operator, who is the person least likely to know
which mode a given hub is in, and who gets it wrong silently. Reading the hub also makes
D-04 possible.

## D-04 — The advertised mode can itself be checked

**Decision:** a hub advertising `authenticated: true` while a protected route answers
unauthenticated is a test failure (FR-003).

**Rationale:** this assertion only becomes available once the suite reads the
advertisement, and it covers a defect class nothing else does. It is not hypothetical
that the hub misdescribes its own auth posture: `auth-mode-truthful-error-text-01KYJZ81`
records the same hub returning *"This hub does not authenticate"* in a 400 while
returning `not_authenticated` to an uncredentialed request minutes apart. That is prose
rather than behaviour, so this check would not have caught it — but it is the same family,
and the two missions should be cross-read.

## D-05 — CI can obtain a credential unattended, with no product change

**Decision:** bootstrap an operator inside the job rather than storing a secret.

**Evidence:** the chain exists entirely on public surface.

| Step | Mechanism | Source |
|---|---|---|
| Initial password | hub logs `initial admin password: %s` on first run | `auth/service.py:146` |
| TOTP secret | `GET /auth/enrol` returns a fresh secret + recovery codes | `api.py:1145`, `auth/service.py:288` |
| Code generation | `agent_mailbox.auth.totp` | in-tree |
| Complete first-run | `POST /auth/enrol` | `api.py:1156` |
| Mint device token | `POST /auth/agents/{name}/tokens`, `provide_operator` | `api.py:1197` |

**Checked and rejected:** an environment variable for the initial admin password. No such
variable exists — `serve.py` reads only `AGENT_MAILBOX_AUTH_MODE`, `_PUBLIC_URL` and
`_SECRET_KEY`. Adding one is real product surface with security consequences on an exposed
hub, and should not arrive as a side effect of wanting a test.

**Secondary benefit:** this is the only live exercise of the operator bootstrap that would
exist anywhere. That path runs exactly once per deployment, at the moment when a fault is
most expensive, and today nothing tests it.

**Risk:** step 1 reads a log line that is not a contract. Reword it and CI breaks somewhere
that looks unrelated. Open question 1 in `spec.md`; recommendation is to make it a
contract and assert it directly.

## D-06 — Authenticating as an operator does not violate ADR 0008

**Decision:** proceed; no charter tension.

**Rationale:** [ADR 0008](../../doc/decisions/0008-no-actor-has-authority.md) says
administration happens **out of band** — "through the shell, git, the deployment, the
operator console" — and that no *actor on the mailbox* has authority. The suite
authenticates as an operator, from outside, exactly as the ADR describes administration
working. It gains nothing through an agent credential and grants no agent anything.

## Open questions and risks feeding into tasks

1. **The log-line dependency (D-05).** Highest risk in the mission. Either assert the line
   as a contract, or add a bootstrap variable — a product decision, deliberately not taken
   here.
2. **A second pass that passes for the wrong reason.** The plausible bad outcome is not a
   failing enforcing pass but a *passing* one that never authenticated: a green tick and
   no coverage. FR-010 addresses it; verify by removing the credential and watching it
   fail, as the v0.22.0 regression tests were verified.
3. **Compose override versus a second file.** An override keeps one topology definition,
   which matters because the compose file is itself part of what the smoke job validates.
4. **`everyone` is not a usable empty-audience case on a deployed hub.** Reserved actors
   (`admin`, `host`) exist before anyone joins, so a broadcast always reaches somebody.
   Relevant here because it is the kind of environment-dependent assumption this suite
   exists to stop encoding — observed while testing the v0.22.0 fix.
