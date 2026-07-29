# Overnight, 2026-07-29 — federation steps 0 to 3

Written for you to read with coffee. Everything below is on `main` and pushed.

## What to look at first

```bash
uv run python doc/demo/two_hubs.py
```

Two real hubs on real ports, one reading the other. If that prints what it should, the
whole of steps 0–3 works. Then open the console and click **Settings** — the Federation
section, and the **Check another hub** box under it, are the operator-facing half.

## Where the roadmap got to

| Step | | |
|---|---|---|
| 0 | A settings system in the database | ✅ |
| 1 | All the settings in the UI | ✅ |
| 1.1 | Federation options within it | ✅ |
| 2 | Passive identity — a hub can be looked at | ✅ |
| 3 | Active identity — a hub can ask who another is | ✅ |
| 4+ | Keys, then one message each way, then the queue | next |

`doc/federation-roadmap.md` is the live plan and has the detail.

## What a hub can do now that it could not yesterday

- Keep settings of its own, in the database, with the environment able to override any of
  them without ever destroying what an operator stored.
- Be given a name, a title and a description, from a Settings tab.
- Switch federation on — and be refused, with a reason, if it is still called `local`.
- Answer NodeInfo and WebFinger, and serve an actor document that tells a stranger only
  what addressing requires.
- Say nothing at all, on every one of those surfaces, until federation is switched on.
- Ask another hub who it is, and show the answer.

## Six defects found, and what found them

None of these were found by writing the code, which is the part worth keeping.

| # | Defect | Found by |
|---|---|---|
| 1 | A stale console page could write the environment's value over an operator's own | outside review |
| 2 | `/doctor` let a stranger enumerate the roster by guessing names | outside review |
| 3 | NodeInfo disclosed a private hub's roster size before it federated | outside review |
| 4 | A non-enforcing hub published every agent's profile to anyone | **the two-hub harness, first run** |
| 5 | Redirects were followed, reaching cloud metadata and internal addresses | outside review |
| 6 | A dripping peer could hold a request open indefinitely | outside review |

Five of six came from a reader without my assumptions; one came from a test harness that
could see something one hub never could. Neither would have found the other's.

**Two of my own tests were vacuous and I nearly shipped them.** The first redirect test
asserted only that an error was raised — but the metadata address is unreachable here
anyway, so it passed whether or not the redirect was followed. Removing the guard is the
only thing that showed it. Every guard added since has been proved that way.

## Things I decided while you were asleep

Each is reversible and each is recorded where the code is.

- **NodeInfo rather than our own descriptor** — implemented against the schema fetched from
  `nodeinfo.diaspora.software`, not from memory. It turned out all seven top-level fields
  are required.
- **NodeInfo and WebFinger are silent until federation is on.** I had argued the opposite
  earlier — that always serving the descriptor avoided a bootstrap deadlock — and that
  argument was simply wrong: enabling federation is a local act needing no peer.
- **A hub that cannot tell its own agents from strangers must assume stranger.** With
  `AUTH_MODE=off` nobody is verified, so once federation is on the public actor route is
  barebones for everyone.
- **`https` only, plus `http` to loopback** so the demo works. An allowlist, never a
  denylist.
- **`/doctor` says `null`, not `false`,** where it declines to say whether a name exists.
  Those are different claims.

## What I did not do

- **Keys.** You said they are a future mission, so the actor document has no `publicKey`.
  A real fediverse peer would reject us; nothing verifies anything yet, so it would be
  decoration.
- **Per-actor visibility.** `local`/`normal`/`discoverable` is still unbuilt, so enabling
  federation exposes every agent at once. Acceptable while you are the only user, and it
  is what makes the hub-level switch the whole control today.
- **The remaining hub-identity work.** WP05 of `a-hub-has-a-name-of-its-own` — the
  onboarding prompt still says this hub cannot federate, which is now false when it can.
  That is the next small thing, and it matters because the prompt is the most-read
  document here.

## Open questions for you

1. **`usage.users.total` counts the standing residents** (`admin`, `host`) alongside real
   agents. Defensible either way; I did it by accident rather than on purpose.
2. **Issue #23** — the private-information cleanup — needs your decision on whether the
   hostname in the *git history* of a public repo matters, or only the tip.
3. **Issue #11** is still waiting on you from yesterday.
4. `pablo_fantomas` was asked to review the federation split and has not replied.

## State

- `main` at `bfd2608`, pushed, working tree clean.
- 757 tests passing, 11 skipped. `ruff`, `ruff format`, `pyright` all clean.
- Branches `feat/federation` and `feat/federation-trust` still hold the superseded
  53-requirement specs. They cost nothing unread and each later step can lift requirements
  from them.
