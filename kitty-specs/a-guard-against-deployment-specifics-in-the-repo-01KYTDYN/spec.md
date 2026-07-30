# Spec — a guard against deployment specifics in the repo

- Mission: `a-guard-against-deployment-specifics-in-the-repo-01KYTDYN`
- From issue **#23**, raised by the operator 2026-07-29; decided 2026-07-30
- Status: **specified.** No open questions.

## What this is

**A check that fails the build when a deployment-specific hostname reaches the repository.**

The repository is public. The charter has forbidden deployment specifics since the project
began.

## Why a guard and not another sweep

Because the sweep already happened, and it was not enough.

- **77 occurrences** of the operator's machine hostname accumulated across 35 tracked files
  — source comments, test docstrings, mission notes, specs — under a rule that forbade
  every one of them.
- They were purged. The purge landed.
- **Two more were added on 2026-07-30, in a handover document, by an agent that had read the
  rule an hour earlier**, and were found only because somebody happened to check.

That last one is the specification. This is not a discipline problem to be solved by
restating the rule more firmly; it is a **rule that nothing checks**. Every other defect of
this shape in this project has been fixed the same way — by making the machine fail rather
than asking the reader to remember.

## Decided before speccing (operator, 2026-07-30)

**The commit history is left alone.** Rewriting a published branch invalidates every clone
and changes every commit hash the project has cited — in issues, in specs, and in
inter-agent mail where hashes have been exchanged as evidence. What it would buy is hiding a
LAN hostname that resolves to nothing outside the network it belongs to, and even then
GitHub keeps unreferenced objects reachable for a while. Weighed and declined; recorded so a
later reader knows it was a decision.

**The guard protects the tip.** That is this mission.

## Functional requirements

| ID | Requirement |
|---|---|
| **FR-001** | A check runs in CI and **fails the build** when a tracked file contains a deployment-specific hostname. Not a warning: a warning in a log nobody reads is the state that produced 77 violations. |
| **FR-002** | The check runs **before** a change lands, not on a schedule. A nightly sweep finds what is already public. |
| **FR-003** | **Agent handles are permitted and must never be stripped.** `ludmila_coe`, `pablo_fantomas` and the rest are assigned, meaningless, and identify nobody; crediting the agent that found a defect is provenance worth keeping. Ruled in scope by the operator 2026-07-28 and recorded in the charter. A guard that removes them is a broken guard. |
| **FR-004** | The failure **says what it found and where**, and how to fix it. A red build that does not name the file teaches nothing. |
| **FR-005** | The check covers **every tracked file**, not only source. Every one of the 77 was in a comment, a docstring, a mission note or a spec — none in executable code. |
| **FR-006** | What counts as deployment-specific is **listed explicitly and is extensible without changing the checker**. Hostnames are the known case; the categories below are the deliberate pass this mission owes. |
| **FR-007** | The check is **runnable locally** by the same command CI uses, so a contributor can find a violation before pushing rather than after. |
| **FR-008** | It must be possible to **record a deliberate exception**, in-file and visible, for a case where the string is genuinely required. An unexceptable rule gets disabled the first time it is inconvenient. |

## What counts as deployment-specific

The sweep covered one hostname because that is what was found. Item 4 of #23 asks for one
deliberate pass rather than discovering categories one at a time:

| Category | Examples | Verdict |
|---|---|---|
| Machine hostnames | the operator's LAN host | **forbidden** — the known case |
| Private IP addresses | `192.168.*`, `10.*`, `172.16-31.*` | **forbidden** |
| Internal URLs and ports | an internal service on a known port | **forbidden** |
| Filesystem paths revealing layout | `/Users/<name>/...`, home directories | **forbidden** |
| Organisation names | the operator's employer | **forbidden** |
| Credential-shaped strings | `glpat-`, `dop_v1_`, `ptr_`, long hex | **forbidden** — none found today, and worth keeping none |
| Agent handles | `ludmila_coe` and the rest | **permitted** — FR-003 |
| Public infrastructure | `pypi.org`, `hub.docker.com`, `github.com` | **permitted** |
| Documented examples | `hub.example`, `beta.example`, `*.localhost` | **permitted** — these exist so specs can be concrete without being specific |

## Test matrix

| Case | Expected |
|---|---|
| A file containing a machine hostname | build fails, naming file and line |
| A private IP in a comment | build fails |
| A home-directory path in a docstring | build fails |
| A credential-shaped string | build fails |
| A file containing `ludmila_coe` | **passes** — handles are not violations |
| A file containing `hub.example` | passes |
| A file containing `alpha.localhost` | passes — the federation tests depend on it |
| A clean tree | passes, and says so |
| A marked exception | passes, and the exception is visible in the file |
| The command run locally | same verdict as CI |

**The guard is proved against a real violation, not a synthetic one.** The commit before
`d47589a` on `main` contains exactly what this must catch — two hostname occurrences in a
handover document — and is the natural fixture. A guard tested only against strings written
to be caught has not been tested against the thing that actually happens.

## Out of scope

| Deferred | Why |
|---|---|
| Rewriting the commit history | Decided against, above |
| Scanning untracked or ignored files | `agent-inbox.toml` is gitignored and full of specifics by design; the rule is about what is *published* |
| Secret scanning as a general capability | GitHub already offers this; the categories here are the project's own rule, which no generic scanner knows |
| Enforcing this on forks | Not ours to enforce |

## Provenance

Issue #23, raised by the operator 2026-07-29. History decision and this scope decided
2026-07-30. The fixture commit exists because the agent writing this specification violated
the rule while writing about it.

## A companion decision: where deployment specifics should *live*

Raised by the operator, 2026-07-30:

> we have some configuration that deploys to my servers; I'm wondering if we should put that
> in another repo that triggers when this one releases

**Yes — and it makes this mission simpler rather than larger.**

### The gap it closes

This spec says what may not be in the repository. It does not say where those things go, and
today the honest answer is *nowhere*: the deploy script and the container-starter written
this session live in a session scratchpad and **will not survive it**. A rule that forbids
something without providing a home is a rule people route around, which is roughly how 77
violations accumulate.

A private deployment repository gives the forbidden things somewhere legitimate to be. The
guard stops being "delete this" and becomes "this belongs next door", which is a rule people
follow.

### The split that already exists

Today's work drew the line by accident, and it held:

| Half | Lives | Knows |
|---|---|---|
| `agent-inbox verify-deployment` | **this repo** | nothing about any deployment — takes URLs and a version |
| `ship.sh`, `start_stragglers.py` | scratchpad, homeless | a Portainer stack id, two Fly app names, a LAN host |

The generic half is a product feature and is already shipped. The specific half is exactly
what a private repo is for.

### What the private repo would hold

The stack file and its image tag; the Fly app configuration; the orchestration; the
credentials that today are passed by hand from the operator's notes — a Portainer API key
and a Fly token — which belong in that repository's secrets rather than in a shell history.

### The trigger, and the property that matters

Released here, deployed there — a release publishing an event the deployment repository
acts on.

**The deploy must still prove itself.** `agent-inbox verify-deployment` is the gate: the
deployment job fails unless every target reports the released version and its prompt agrees
with its descriptor. That is not new work; it exists and is tested. Moving the orchestration
must not lose it, because the thing that has gone wrong three times is a deploy that
reported success over a hub that was down or five releases behind.

### Why this is recorded here rather than specced here

It is a **separate mission** — a new repository, a trigger, and secret handling are not this
guard. Recorded here because the two decisions are related and would otherwise be made
inconsistently: a guard designed without knowing where the forbidden things go will be
written as a prohibition, and one designed knowing will be written as a redirection.

**This mission is unchanged by it.** FR-004 gains one line: where the failure names a
deployment specific, it should say where such things belong.
