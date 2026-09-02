# 2026-09-03 — v1.2.0 (omp) shipped; live test with espen_luo waits on a restart

Mission `omp-known-and-woken-01M1J4KG`, issue #65. Everything is on `main` and pushed;
tag `v1.2.0` is cut. The one open item is the **live verification**, which needs the
owner to restart the omp session — they said they would do it tomorrow.

## State

- **Code:** `82309aa` (omp is a known harness) and `e9bf4da` (omp waking). Gates green,
  removal proofs run. Spec C-004 amended (`5362c70`): both parts shipped as one release.
- **Release:** tag `v1.2.0` pushed at 23:15 UTC 2026-09-02. A background job was waiting
  for the Release and Docker workflows and would then run
  `~/workspace/agent_inbox_private/deploy/ship-fly.sh 1.2.0` and `verify-deployment`.
  **Check that it landed** — do not assume: `agent-inbox verify-deployment` must report
  1.2.0 for hub and console at the public addresses. Log was in the session scratchpad
  (`ship-1.2.0.log`), which does not survive the session; if unsure, run the script
  again — it is idempotent and refuses to say shipped unless proved.
- **Local tool:** `~/.local/bin/agent-inbox` is 1.2.0, installed from this checkout.
- **MCP config:** `~/.claude.json` repointed from the removed `agent-mailbox` script to
  `agent-inbox`. omp imported the stale entry, so its mailbox has been dead all session;
  the restart fixes that.
- **Announcement to all agents:** not yet sent. Do it once the deploy is proved (memory:
  release every fix and tell the agents).

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
