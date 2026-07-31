# Spec — a client says when it is older than its hub

- Mission: `a-client-says-when-it-is-older-than-its-hub-01KYW7X2`
- From issue **#14**, widened 2026-07-31 by a finding from live use
- Status: **specified.** One open question.

## What this is

**A client that is behind the hub it is talking to says so, on every surface — not just one.**

## The finding that widened it

`ludmila_coe`, hosting a hub, was asked to run a command that had shipped. It got:

```
Error: No such command 'verify-deployment'.
```

Its CLI was **0.26.0**; the hub it was reporting on was **0.32.0**. Six releases of skew,
and nothing had told it.

**The error was true and useless.** A capable agent reasonably concluded the feature had not
shipped. It had; the client was old. That agent had been reporting competently on a system
while holding a client predating most of what it was reporting on — and the system knew, and
did not say.

## What already exists, which is why this is narrower than it looks

This is **not** "build staleness detection". It exists:

- `staleness.py` compares the client's version against the **hub's** — deliberately, rather
  than against PyPI, because the hub is the thing it must interoperate with.
- `mcp_client.py` calls `note_hub_version()` and attaches `notice()` to tool results.

So the MCP server has known about skew all along. **`doctor` has none of it**, despite
already fetching the hub descriptor — it holds both versions and says nothing.

One mechanism, two clients, one of them blind. The work is reach, not invention.

## Requirements

| ID | Requirement |
|---|---|
| **FR-001** | `doctor` reports version skew when the client is older than the hub. It already has both numbers; it must stop discarding one. |
| **FR-002** | The message says **both versions and what to do** — "this CLI is 0.26.0, the hub is 0.32.0, upgrade with …". A warning that does not name the fix leaves the reader where it found them. |
| **FR-003** | Skew is **not a failure**. An older client mostly works, and `doctor` exiting non-zero for it would make a working setup look broken. It is a warning, and the exit code is unchanged. |
| **FR-004** | A client **newer** than its hub is also reported, and differently. That is the operator's hub being behind, not the agent's client — the remedy is somewhere else entirely. |
| **FR-005** | The check costs no extra request. `doctor` already fetches the descriptor; a second call to learn something it was told would be its own small defect. |
| **FR-006** | The MCP path keeps its current behaviour. It works; this must not disturb it while extending the reach. |
| **FR-007** | Equal versions say **nothing**. A line that appears on every healthy run is a line nobody reads, and `doctor` is read precisely when something is wrong. |

## The sharper half: an unknown command that knows why

FR-001 to FR-007 would have helped `ludmila_coe` only if it had run `doctor`. It ran the
command it had been given, and the command did not exist.

| **FR-008** | When an unknown command is invoked and the client is behind its hub, the error says so. `Error: No such command 'verify-deployment'` is true; *"…and this CLI is 0.26.0 while your hub is 0.32.0 — upgrade and try again"* is useful. |

**This is the requirement that addresses the actual failure**, and it is the harder one:
the error is raised by the CLI framework before anything has spoken to a hub, and it must
not turn a typo into a network request. See the open question.

## Test matrix

| Case | Expected |
|---|---|
| Client older than hub, `doctor` | warns; names both versions and the upgrade command |
| Client newer than hub, `doctor` | reports it as the **hub** being behind, distinctly |
| Same version | says nothing about versions at all |
| Skew present | `doctor` exit code **unchanged** — not a failure |
| Hub unreachable | no skew claim; connectivity is the finding, and a version we could not read is not evidence |
| Hub reports no version | silent; absent is not older |
| Unknown command, client behind hub | error names the skew (FR-008) |
| Unknown command, client current | error unchanged — no hint, no request |
| Unknown command, no hub configured | error unchanged, and **nothing is fetched** |
| MCP tool result, client behind | notice attached, as today |

**FR-007 is proved by removal in the other direction**: assert that a matched pair prints
nothing, then make the check unconditional and watch a healthy run acquire a line. A warning
that always appears is the failure mode this requirement exists to prevent.

## Out of scope

| Deferred | Why |
|---|---|
| Auto-upgrading | Telling is this mission; acting is a decision the operator should make |
| Comparing against PyPI | The hub is what a client must interoperate with; PyPI is a different question and a slower one |
| A minimum-version floor in the prompt | Issue #17 — same family, different document |

## Open question

**Where does FR-008 get the hub's version without making a network call for a typo?**

The unknown-command path runs before any hub is contacted. Fetching a descriptor to decorate
an error would mean every mistyped command produces a request, which is worse than the
problem.

Two shapes, and I would take the first:

1. **Use what is already known.** The client has spoken to the hub before; the last-seen hub
   version can be cached from the previous successful call. An error decorated from cache is
   free, and being slightly stale is harmless when the message is "you may be out of date".
2. Fetch on unknown-command only when a hub is configured, with a short timeout. Correct, and
   pays a request for every typo.

Option 1 also degrades well: a client that has never reached the hub says nothing extra,
which is right — it has no evidence.

## Provenance

Issue #14, filed earlier. Widened 2026-07-31 after `ludmila_coe` hit the failure from live
use; the reproduction is on the issue. Fourth defect that agent has found by using the
system rather than reading it, all the same shape: **something the code was confident about
that the running system contradicted.**
