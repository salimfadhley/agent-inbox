# Data model — a hub has a name of its own

Phase 1 for `a-hub-has-a-name-of-its-own-01KYMD90`.

This is the **first persistent state the hub keeps about itself**. Today the store holds
three tables, all about mail: `actors`, `objects`, `reads`. Nothing records what the hub
*is*.

## Entities

### HubSettings

What an operator has configured. Persisted; may be entirely absent, which is the state of
every hub in existence today.

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | str | no | the `@hub` part. Validated as an address component. Absent means `local` |
| `title` | str | no | display only — "The Salt Club". Free text, may be empty |
| `description` | str | no | prose — what the hub is for, who runs it. Free text, may be empty |

**A row is not required.** An upgraded hub has none, and that is the ordinary case rather
than a missing-configuration error. Reads must tolerate absence without inventing one.

**Only `name` is load-bearing.** It appears in addresses and gates federation. The other
two are presentation and carry no behaviour.

### ResolvedSetting

The answer to "what is this value, and who decided it" — computed per request, never
stored.

| Field | Type | Notes |
|---|---|---|
| `value` | str | what the hub will use |
| `source` | enum | `environment` \| `stored` \| `default` |
| `variable` | str \| None | the environment variable's name, when `source` is `environment` |

`variable` exists so the console can say *which* variable governs a disabled field. A
greyed box with no explanation reads as broken; one naming `AGENT_INBOX_HUB_NAME` reads as
governed.

This mirrors `client.effective_settings()`, which already returns `(value, source)` for
client configuration. Copying that shape rather than inventing a second one is deliberate.

### HubDescriptor

The public face, at `GET /`. Not stored — assembled from resolved settings plus facts the
hub already knows.

| Field | Source | Changed by this mission |
|---|---|---|
| `name` | resolved | now validated, and stored when not set by environment |
| `title` | resolved | **new** |
| `description` | resolved | **new** |
| `id`, `version`, `authenticated`, `note`, `policies` | as today | unchanged |

## Relationships

```
environment  ─┐
              ├─► ResolvedSetting ──► HubDescriptor  (GET /)
HubSettings  ─┘         │
  (stored)              └────────► console field state (value + enabled/disabled + why)
        ▲
        │ operator write, gated where the hub authenticates (ADR 0008)
        └─ Federation tab
```

Environment and stored are **both inputs** to resolution. They are never merged into one
another, which is the invariant below.

## Invariants

These are what make the model trustworthy rather than decorative. Each is a test.

1. **Environment shadows; it never replaces.** Resolution prefers the environment, and
   startup must not write the environment's value into `HubSettings`. An operator who sets
   a variable, restarts, then unsets it gets their stored value back. Violating this is
   silent data loss that looks exactly like it worked — the project's recurring shape, and
   the highest risk in this mission.

2. **Absence is legitimate at every level.** No settings row, no `title`, no
   `description`: all ordinary. A hub with nothing configured must produce the descriptor
   it produces today, byte for byte where the new fields are concerned.

3. **`name` is an address component, not free text.** It satisfies the same rule as an
   agent name. Today `trevor@The Salt Club` parses into `trevor@the salt club`, and
   `hub.thesaltclub.xyz` is accepted as a *name* — the exact conflation this removes.

4. **Validation applies to writes, never to startup.** A hub already configured with a
   name the new rule would reject must still start. The rule arrived after its
   configuration did.

5. **`local` is a name, not a sentinel.** It is permitted and is the default. What it
   blocks is *enabling federation*, so that a hub with federation on and no name is
   unreachable as a state.

6. **Identity survives the address.** Changing the public URL does not change `name`. This
   is the mission in one line, and the test that would have caught the mistake that
   prompted it.

## What is deliberately not modelled

- **A hub identifier separate from the name.** Proposed and rejected: the operator's
  direction is that the fediverse `name@hub` form settles addressing, and domain-based
  federated identity settles collisions. A third identifier would be a parallel concept
  earning nothing.
- **Aliases or forwarding for a renamed hub.** Unnecessary — nothing outside the hub holds
  the friendly name. See D-06 in `research.md`.
- **Peers, federation modes, blocklists.** They belong to
  `manual-activitypub-federation-v1-01KYJY10`, whose FR-001 already anticipates the tab
  this mission builds.
