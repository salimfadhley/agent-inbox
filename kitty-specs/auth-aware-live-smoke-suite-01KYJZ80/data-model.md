# Data model — auth-aware live smoke suite

This mission adds no persistent entities: it changes tests and a CI job, and touches no
storage. What follows is the model the *test suite* needs to hold — the things it must
know before it can assert anything, and how they relate.

That is worth writing down because the defect being fixed is precisely a missing entity.
Today the suite has no representation of "what kind of hub am I talking to", so the answer
is hardcoded as an assumption, and every assertion inherits it.

## Entities

### HubDescriptor

What the hub says about itself. Fetched once per run from `GET /`.

| Attribute | Type | Source | Notes |
|---|---|---|---|
| `name` | str | `GET /` → `name` | the hub's own name, e.g. `halob` |
| `version` | str | `GET /` → `version` | compared against nothing by this suite; recorded in failure output |
| `authenticated` | bool | `GET /` → `authenticated` | **the field this whole mission turns on** |
| `note` | str | `GET /` → `note` | prose description of the posture; see the cross-check below |

Fetch failure is fatal to the run, not to one test (FR-001). A descriptor that cannot be
read means no assertion has a premise.

### AuthMode

Derived from `HubDescriptor.authenticated`. Deliberately a small closed set rather than a
free boolean, so that a third state cannot be introduced silently.

| Value | Meaning | Consequence for assertions |
|---|---|---|
| `open` | hub does not authenticate | protected routes answer 200; console shows the `does not authenticate` warning |
| `enforcing` | hub requires a credential | protected routes answer 401 without one, 200 with; console must **not** show that warning |

The hub's configuration also admits `warn`, which this suite does not model. That is a
deliberate omission and a known limitation: `warn` both authenticates and tolerates
failure, and its caller-facing semantics are an open question in
`auth-mode-truthful-error-text-01KYJZ81`. Modelling it before that is settled would encode
a guess.

### Credential

A device token, held only for the life of the run.

| Attribute | Type | Notes |
|---|---|---|
| `token` | str | bearer credential |
| `actor` | str | the agent name it authenticates |
| `origin` | enum | `environment` (an operator supplied it) or `bootstrapped` (CI minted it) |

Never read from a repository file, never written to one (NFR-001, FR-005). `origin`
exists so a failure can say where the credential came from, which is the first question
when authentication misbehaves.

### BootstrapResult

Only in CI, and only in the enforcing pass. The audit trail of D-05, so that a failure in
any of six steps names itself instead of surfacing as a 401 in an unrelated test (FR-009).

| Attribute | Type | Notes |
|---|---|---|
| `initial_password` | str | scraped from container logs — the fragile step |
| `totp_secret` | str | from `GET /auth/enrol` |
| `enrolled` | bool | first-run completed |
| `session` | opaque | operator session |
| `credential` | Credential | the point of the exercise |

## Relationships

```
HubDescriptor ──derives──> AuthMode
                              │
                              ├── selects expected status codes
                              ├── selects expected console copy
                              └── decides whether a Credential is required
                                          │
                    ┌─────────────────────┴─────────────────────┐
              origin=environment                          origin=bootstrapped
           (operator, running by hand)                 (CI enforcing pass only)
                                                              │
                                                       BootstrapResult
```

## Invariants

These are the assertions that make the model trustworthy rather than decorative:

1. **No assertion runs before `AuthMode` is known.** The mode is a precondition, not a
   parameter with a default. A default would restore exactly the current bug.
2. **`authenticated: true` implies protected routes reject an uncredentialed request**
   (FR-003). This is the cross-check between what the hub *says* and what it *does*, and
   the only new coverage in the mission.
3. **`enforcing` plus no credential is a skip with a stated reason, never a failure and
   never silence** (FR-005, FR-006). "Cannot test this" and "this failed" are different
   facts and must not share a symbol.
4. **In CI's enforcing pass, a run that completes without ever authenticating is a
   failure** (FR-010). Without this the pass can be green and empty — the failure shape
   this mission exists to remove from live validation.
