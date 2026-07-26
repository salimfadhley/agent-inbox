# Shared tokens only

**One kind of credential: a token that admits a machine. It is listed, it is
revocable, and it records which agents it has let in.**

## Why

Device tokens arrived bound to one agent each. Minting one apiece is the right shape
for a shared server and pure friction on a laptop running four coding agents — and
friction is what gets abandoned, so the shared token (`actor = "*"`) was added: it
admits whoever holds it, and each agent still says which name it is using.

Having both kinds is worse than having either. Three concrete faults today:

1. **A shared token cannot be found again.** The Tokens screen lists tokens *per
   agent*, and a shared token belongs to no agent, so once the "shown once" page is
   closed there is no screen on which it appears. It cannot be reviewed and cannot be
   revoked from the console at all — the operator's only recourse is the database.
2. **Nothing records what a token admits.** An operator looking at a token cannot tell
   which agents have used it, so revoking is a guess about what will break. On a hub
   where one token admits a whole machine, that is the only question worth asking.
3. **Two models to explain.** The prompt, `doctor`'s guidance, the console and the API
   all carry both shapes, and every one of them has to hedge about which applies.

## What changes

**All tokens are shared.** A token admits a machine; the agent's *name* still comes
from the caller and is settled by the hub as it always was. No path — console, API or
CLI — mints a token bound to a single agent.

**Every token is listed and revocable**, with its label, when it was issued, when it
was last used, and which agents it has admitted.

**Authentication is recorded per agent.** The first time a token admits `jed_smith`,
that is written down; every later use updates the last-seen time. That is what makes
revoking an informed act rather than a gamble.

## Requirements

### FR-1 — one Tokens screen, listing every token

`/tokens` shows every token on the hub, not a list of agents. Each row carries:

- **label** (what the operator typed at mint time — "workshop laptop")
- **issued** (date)
- **last used** (date, or "never")
- **agents admitted** (the names this token has authenticated, most recent first)
- **Revoke**

The per-agent pages (`/tokens/{name}`) go away. The Agents directory keeps no Tokens
column.

### FR-2 — minting

One form, on `/tokens`: a label, and a Mint button. The secret is shown exactly once,
with the existing copy button and the `agent-inbox config set --global token <token>`
instruction. Nothing about minting names an agent.

A label is **required** — a list of unlabelled tokens is a list nobody can act on. If
the operator gives none, refuse rather than invent one.

### FR-3 — revoking is immediate and honest

Revoking refuses the token on its next call (already true: `resolve_token` raises
`TokenRevoked`). The confirmation says which agents that token had admitted, so the
operator learns what they have just cut off.

Revoked tokens stay in the list, marked, with their history — a revoked token that
vanishes takes the record of what it did with it.

### FR-4 — the API

- `POST /auth/tokens` — mint. Body: `{"label": "…"}`. Operator-only. Returns the
  secret once.
- `GET /auth/tokens` — every token with the fields in FR-1. Operator-only.
- `DELETE /auth/tokens/{token_id}` — revoke. Operator-only.

The three `/auth/agents/{name}/tokens…` routes are removed. Nothing else moves: the
bearer header, `provide_caller`, and the `X-Agent-Name` identity rule are unchanged.

### FR-5 — record which token admitted which agent

On every successful token authentication, record the pair. A new table:

```
auth_token_use (token_id, actor, first_seen, last_seen, uses)   PK (token_id, actor)
```

Written where the actor is known. This is one extra upsert on an authenticated
request — acceptable on a single-owner hub, and worth a sentence in the code saying so,
since it sits on the hot path.

Note the shape problem it creates: `resolve_token` today is given only the secret and
answers *with* the actor, because a bound token named one. Under this model it does
not, and the claimed name arrives separately in the `X-Agent-Name` header. Changing
that signature — so the caller passes the claimed name in — is part of this mission.
Do not infer the actor from the token.

### FR-6 — existing tokens

Any token already bound to a real actor keeps working: nobody is locked out by an
upgrade. It appears in the list marked **bound to `<name>`** and can be revoked like
any other. No new bound tokens can be created. Do not migrate them silently — an
operator should see what they have and retire it deliberately.

### FR-7 — the words follow the code

Once per-agent tokens are gone, they must stop being described:

- the served prompt (`prompts.py`) — the device-token paragraph
- `doctor`'s `_token_help` in `cli.py` — the "Tokens -> Mint" steps
- the MCP `join` tool's `token` parameter documentation
- `README.md` where it describes tokens
- the Tokens page's own explanatory text

## Non-goals

- The human login model (password + TOTP, sessions, recovery codes) is untouched.
- How an agent *sends* a token is untouched: `Authorization: Bearer …`, taken from
  `~/.config/agent-inbox/config.toml` or the project file.
- No token expiry, rotation schedule or scopes. If those are wanted they are their own
  mission; this one makes the credential that already exists visible and revocable.

## Acceptance

1. Mint a token from the console. It appears in the list with its label and issue date.
2. An agent authenticates with it. The list shows that agent against that token, and a
   sensible last-used time.
3. A second agent on the same machine authenticates with the same token. Both names
   appear. Neither can read the other's mail — the identity rule is unchanged.
4. Revoke it. Both agents are refused on their next call, and `agent-inbox doctor`
   reports `token revoked`, with the hub's verdict saying so.
5. The revoked token is still listed, marked revoked, with its history intact.
6. No route, form or CLI flag can produce a token bound to one agent.
7. A pre-existing bound token still authenticates its agent, is listed as bound, and
   can be revoked.

## Notes for the implementer

- The shared sentinel is `SHARED_ACTOR = "*"` in `auth/records.py`. Whether the column
  keeps that value or the schema stops using `actor` for new rows is your call; FR-6
  needs the old rows to keep working either way.
- `auth_device_tokens` already has `label`, `created`, `last_used`, `revoked`. The
  missing piece is the usage table, not the token table.
- The console is a client and holds no security judgement: it relays the operator's
  session and reports what the hub says (ADR 0005). Keep that — the guard belongs on
  the API routes, where it is today.
- The Tokens page is reachable from the nav and is gated along with every other page.
  That behaviour exists and should not change.
- Tests: `tests/test_auth_service.py`, `tests/test_auth_store.py`,
  `tests/test_auth_api.py` and `tests/test_console.py` all cover the current per-agent
  shape and need rewriting rather than deleting — the properties they pin
  (operator-only, shown once, revocation refuses) all still apply.
