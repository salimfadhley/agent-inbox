# 2026-09-12 — v1.3.0 shipped (doctor `hub says`, #68); omp live wake test still pending (#65)

Everything is on `main`, tagged `v1.3.0`, deployed to the stodge node and proved (`verify-deployment`: 5 checks, hub and console both 1.3.0). Local tool at `~/.local/bin/agent-inbox` is 1.3.0. #68 is closed. The open item is unchanged: the **live idle-wake test on omp** with `espen_luo`, who has the steps by mail (restart omp → `ping` says espen_luo → `install-hook` → restart → reply → idle; then I send mail).

## What shipped

- `doctor` prints `hub says` after `hub check`: who the hub serves this caller as (`you.verified` from `remote_doctor`) beside the name the config sends (`you.claimed`). Four cases; a token bound to a different actor is a failure that names both names and exits 1. Older hubs: no line. `whoami` carries `hub_says`. Helper `_hub_says` in `cli.py`; tests in `tests/test_doctor_says_who_the_hub_thinks_you_are.py`.
- `join` now installs waking for the joined harness via `install_for(engine, …)` — omp extension / opencode plugin — instead of the Claude-only `install(...)`. **This is `espen_luo`'s fix**; it was uncommitted in the shared worktree and got swept into my commit `8c5a46f`. Credited on #65 and to them by mail. Lesson saved to memory: `git diff` every shared file before staging.

## Deploying, for next time

Dispatch the private repo's workflow after the tag's Release and Docker runs are green (they are titled simply "Release" / "Docker image"; match by creation time after the tag, not by commit title): `gh workflow run deploy.yml -R salimfadhley/agent-inbox-private -f version=<v>`, `gh run watch`, then `verify-deployment --hub https://api.hub.stodge.org --prompt https://hub.stodge.org/prompts/agent --expect <v>`. Local `flyctl` login has lapsed.

## Also open

- #65 live acceptance (above). Two follow-ups from the 2026-09-07 Windows report are still unaddressed: raise the onboarding prompt's version floor (currently admits pre-1.2.0 clients that misidentify omp), and honour legacy `[agents.ohmypi]` entries as `omp`. Owner has not yet said whether to do them.
- #64 opencode waking, awaiting `aurelia_saahaa`'s live verification.
