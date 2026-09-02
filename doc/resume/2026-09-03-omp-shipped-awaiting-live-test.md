# 2026-09-03 — v1.2.0 (omp) shipped; live test with espen_luo waits on a restart

Mission `omp-known-and-woken-01M1J4KG`, issue #65. Everything is on `main` and pushed;
tag `v1.2.0` is cut. The one open item is the **live verification**, which needs the
owner to restart the omp session — they said they would do it tomorrow.

## State

- **Code:** `82309aa` (omp is a known harness) and `e9bf4da` (omp waking). Gates green,
  removal proofs run. Spec C-004 amended (`5362c70`): both parts shipped as one release.
- **Release:** v1.2.0 released (PyPI + Docker Hub) and **deployed to stodge, proved**:
  `verify-deployment` — 5 checks, hub and console both 1.2.0 (2026-09-02 23:50 UTC).
  Deployed by dispatching the private repo's workflow — the Actions allowance is back —
  `gh workflow run deploy.yml -R salimfadhley/agent-inbox-private -f version=1.2.0`;
  `ship-fly.sh` locally needs `flyctl auth login`, which has lapsed on this machine.
- **Local tool:** `~/.local/bin/agent-inbox` is 1.2.0, installed from this checkout.
- **MCP config:** `~/.claude.json` repointed from the removed `agent-mailbox` script to
  `agent-inbox`. omp imported the stale entry, so its mailbox has been dead all session;
  the restart fixes that.
- **Announcement to all agents:** sent after the deploy was proved.

## The test, step by step (already sent to espen_luo as mail)

1. espen: `agent-inbox --version` → 1.2.0; restart omp; `agent-inbox --engine omp join
   --name espen_luo`; `agent-inbox install-hook` (should detect omp from `OMPCODE`);
   restart omp; `whoami` → espen_luo/omp; reply and go idle.
2. me: send espen a message while idle. Expect a self-started turn opening with the
   notice — sender and subject, **no body**, attributed as machine output.
3. me: send one mid-turn. Expect it to wait until the turn ends (`followUp`).
4. Ask espen whether anything crashed the session (the in-process hazard).
5. Post the result on #65; close it if green. #64 (opencode) still awaits its own.

## If it fails

- Extension not loaded: omp scans `<cwd>/.omp/extensions/*.js` cwd-only; check
  `~/.omp/logs/omp.<date>.<pid>.log` for extension load errors.
- Waiter exits 0 at once: the extension passes `--engine omp`; confirm
  `[agents.omp]` exists in `agent-inbox.toml` (espen first joined as `ohmypi`).
- Wrong identity: `OMPCODE`/`CLAUDECODE` ordering is in `client.ENGINE_MARKERS`.
