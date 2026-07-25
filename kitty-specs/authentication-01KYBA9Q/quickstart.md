# Quickstart — bootstrap and the grace-mode migration

## First run (a fresh hub)

1. Start the hub. Because the users table is empty, it bootstraps and logs, once:
   ```
   WARNING agent_mailbox.auth: no users found — created bootstrap admin.
   WARNING agent_mailbox.auth: initial admin password: <random> (shown once; change it now)
   ```
2. Open the console → **Login**. Sign in as `admin` with that password.
3. You are required to **set a real password** and **enrol 2FA**: scan the QR with your
   authenticator app, enter a code to confirm, and save the recovery codes shown.
4. The logged password is now dead; the account is `active`.

## Migrating the live hub without a lockout

The hub starts in whatever `AGENT_MAILBOX_AUTH_MODE` says (`off` by default — today's
behaviour). To turn auth on for a hub that already has agents:

1. **Deploy with `AUTH_MODE=warn`.** Everything keeps working; the hub now *checks*
   credentials and **logs** every request that would fail under enforce, but serves it. Watch
   the logs to see exactly which agents still lack a token.
2. **Complete the bootstrap** (above) so you have an operator login.
3. **Mint a device token per agent.** In the console → **Agents → Tokens**, or:
   ```
   POST /auth/agents/<agent>/tokens   { "label": "<where it runs>" }   → { "token": "<secret>" }
   ```
   Put the secret in that agent's `agent-mailbox.toml`; the client sends it as a bearer
   header from then on. Re-run the agent and confirm its warning stops.
4. **When the warnings have drained to zero, set `AUTH_MODE=enforce`** and redeploy. Now a
   missing or invalid credential is refused; `GET /` reports `authenticated: true`; the write
   paths and `/observe/*` are gated behind a session or a token.

Reverting is symmetric: set `AUTH_MODE=warn` (or `off`) and redeploy — no schema change, no
data migration.

## Environment

- `AGENT_MAILBOX_AUTH_MODE` = `off` | `warn` | `enforce` (default `off`).
- `AGENT_MAILBOX_SECRET_KEY` = a stable base64 Fernet key used to encrypt TOTP secrets at
  rest. **Keep it constant across restarts** — losing it means re-enrolling 2FA, not losing
  accounts. Generate one with the app's `--print-secret-key` helper (or any Fernet key).
- Bearer credentials assume TLS is terminated in front of the hub (C-009).
