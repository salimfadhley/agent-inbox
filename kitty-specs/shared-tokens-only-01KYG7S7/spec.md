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

Each row links to the section that states it in full, below.

| ID | Requirement | Status |
|---|---|---|
| **FR-001** | One `/tokens` screen lists every token on the hub — label, issued, last used, agents admitted, revoke. The per-agent pages go away. | Specified |
| **FR-002** | One mint form: a label and a button. A label is **required** — a list of unlabelled tokens is a list nobody can act on. Nothing about minting names an agent. | Specified |
| **FR-003** | Revoking takes effect on the token's next call, and the confirmation says which agents it had admitted, so the operator learns what they just cut off. Revoked tokens stay listed, marked. | Specified |
| **FR-004** | `POST`/`GET /auth/tokens` and `DELETE /auth/tokens/{id}`, operator-only. The three `/auth/agents/{name}/tokens…` routes are removed. | Specified |
| **FR-005** | Every successful authentication records the (token, agent) pair with first and last seen. **This is what makes revoking an informed act rather than a gamble.** | Specified |
| **FR-006** | A token already bound to one actor keeps working, listed as **bound to `<name>`**. Nobody is locked out by an upgrade. | Specified |
| **FR-007** | The words follow the code: prompt, `doctor`, console and API stop hedging between two token shapes. | Specified |
| **FR-008** | Each row carries **when it was last used**, with "never" distinct from "long ago". | Specified |
| **FR-009** | Recording last use is **coarse** — at most one write per token per bucket, not one per request. | Specified |
| **FR-010** | "Issued to" (a label the operator typed) and "admitted" (what we observed) are separate columns. A claim must never be shown where a finding appears to be. | Specified |
| **FR-011** | The admitted history is **last use per agent per token**, overwritten in place — bounded by the number of agents, not by traffic. | Specified |
| **FR-012** | The interrupt gate's guarantee is restated: a shared token proves the *machine*, not the agent. The check stays; the words and `doc/interrupting-an-agent.md` stop claiming more than it gives. | Specified |
| **FR-013** | The mint screen hands over the **token and a setup prompt containing it, together**, at the one moment the secret exists. The standing prompt stays generic and token-free — it is served to anyone. No paste box, no lookup, no second chance. | Specified |

### FR-001 — one Tokens screen, listing every token

`/tokens` shows every token on the hub, not a list of agents. Each row carries:

- **label** (what the operator typed at mint time — "workshop laptop")
- **issued** (date)
- **last used** (date, or "never")
- **agents admitted** (the names this token has authenticated, most recent first)
- **Revoke**

The per-agent pages (`/tokens/{name}`) go away. The Agents directory keeps no Tokens
column.

### FR-002 — minting

One form, on `/tokens`: a label, and a Mint button. The secret is shown exactly once,
with the existing copy button and the `agent-inbox config set --global token <token>`
instruction. Nothing about minting names an agent.

A label is **required** — a list of unlabelled tokens is a list nobody can act on. If
the operator gives none, refuse rather than invent one.

### FR-003 — revoking is immediate and honest

Revoking refuses the token on its next call (already true: `resolve_token` raises
`TokenRevoked`). The confirmation says which agents that token had admitted, so the
operator learns what they have just cut off.

Revoked tokens stay in the list, marked, with their history — a revoked token that
vanishes takes the record of what it did with it.

### FR-004 — the API

- `POST /auth/tokens` — mint. Body: `{"label": "…"}`. Operator-only. Returns the
  secret once.
- `GET /auth/tokens` — every token with the fields in FR-001. Operator-only.
- `DELETE /auth/tokens/{token_id}` — revoke. Operator-only.

The three `/auth/agents/{name}/tokens…` routes are removed. Nothing else moves: the
bearer header, `provide_caller`, and the `X-Agent-Name` identity rule are unchanged.

### FR-005 — record which token admitted which agent

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

### FR-006 — existing tokens

Any token already bound to a real actor keeps working: nobody is locked out by an
upgrade. It appears in the list marked **bound to `<name>`** and can be revoked like
any other. No new bound tokens can be created. Do not migrate them silently — an
operator should see what they have and retire it deliberately.

### FR-007 — the words follow the code

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
  keeps that value or the schema stops using `actor` for new rows is your call; FR-006
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


---

## Absorbed 2026-08-01: the listing, and what it shows

Mission `tokens-you-can-see-01KYYGM6` described the same screen as FR-001 and has been **folded
into this one and retired**. Its requirements land here rather than being built twice against
the same page. Tracked as **#38**.

### FR-008 — every row carries when it was last used

**This is the field that makes the screen worth having.** Issued-date tells an operator a
token is old; only last-used tells them it is *dead*. Without it, revoking is a guess, the
safe-feeling choice is to leave every credential alive, and secrets outlive the machines they
were minted for.

A token never used says so, distinctly from one used long ago. "Never" and "a year ago" are
different facts leading to different actions.

### FR-009 — recording last use is **coarse**

Decided 2026-08-01. At most **one write per token per bucket**, not one per request.

**Corrected 2026-08-02.** This was written believing authentication only *reads* today. It
does not: `AuthService.resolve_token` calls `touch_token` on every successful call, which is
an `UPDATE` plus a `commit` per authenticated request. So coarse recording is not a new cost
to be justified — it is a **fix for a write that is already on the hot path**, and the
existing `last_used` write should be folded into the same bucket rather than left beside it.

Nobody needs second-precision to decide whether a credential is abandoned. Bucket size is a
planning choice; anything from a minute to an hour satisfies this.

### FR-010 — "issued to" is a claim; "admitted" is a finding. Never the same column.

Decided 2026-08-01, and the distinction is deliberate.

| Column | Is | Comes from |
|---|---|---|
| **Issued to** | what the operator typed at mint time — "Sal's laptop", "CI runner" | a claim, and it can be wrong or stale |
| **Admitted** | which agents have actually authenticated with it | observed fact |

A shared token is issued to a *machine*, not an agent, so "issued to" cannot be derived — it
has to be asked for. And it must not be presented as though it were observed: this project
keeps claims and findings visibly apart elsewhere, and a stale label sitting where a fact
appears to be is exactly how an operator revokes the wrong credential.

### FR-011 — the admitted history is bounded by construction

Decided 2026-08-01: store **last use per agent, per token**, overwritten in place.

One row per agent-token pair. Bounded by the number of agents no matter how much traffic
flows, which is what stops this becoming a log that grows forever and presents as working —
the same failure shape as an unbounded queue.

The cost, accepted: no history. You can see that an agent last used a token on Tuesday, not
that it used it heavily in June. Nobody has asked for the latter.

### FR-012 — what this does to who may interrupt an agent

Added 2026-08-02, from analysis before planning. **This mission changes the meaning of a
guarantee another feature depends on**, and that has to be settled here rather than
discovered there.

`v0.41.0` lets a recipient name senders allowed to interrupt it mid-turn, gated on identity
and never on anything the sender wrote. It refuses entirely when the hub does not
authenticate, because a hub with authentication off takes the sender's name from a request
header at face value. That check reads `authenticated` from the hub descriptor.

Once every token is shared, `provide_caller` takes the name from `X-Agent-Name` on **every**
call — that is already what it does for `SHARED_ACTOR`, and after this mission there is no
other kind. So `authenticated` stays `true` while the name behind it is header-supplied.
Left alone, the interrupt gate would report identity as verified and honour a trust list over
a name anyone holding the machine's token can set: the same hole, reinstated behind a check
that now says it is fine, which is worse than having no check.

**Decided: the boundary is the machine, and the words must say so.** A shared token proves
the sender is on a machine an operator admitted. That is a real and useful guarantee — it
still stops a stranger on the network, another machine, and (with signatures) another hub.
What it does not do is tell two agents on the *same* machine apart, and it never could: they
share a config file and a credential by design.

So the check stays, because it still separates "anyone who can reach this hub" from "a
machine the operator admitted". What changes is the claim made for it. `wake_from` means
*interrupt me for mail from these names, as asserted by an admitted machine* — not *as proved
to be that agent*. The reason code `identity-unverified` keeps its meaning; the documentation
in `doc/interrupting-an-agent.md`, whose table still has a row for per-agent device tokens,
must lose that row and say plainly what remains.

### FR-013 — the token and its prompt are born together

Added 2026-08-02, at the owner's suggestion, and it replaces an earlier sketch of a
paste-box on the prompt page.

**The hub cannot retrieve a token, and that is not a policy.** `DeviceToken` holds
`token_hash` and nothing else; the raw secret exists in memory for the length of one
response and is written nowhere. There is no retrieval path to build and none can be added
without changing how tokens are stored.

That constraint picks the design. The mint response is the *only* moment in a token's life
when the secret and the hub's identity are both in hand, so it is the only place a
ready-to-use prompt can be produced without a lookup. So the mint screen shows the secret
and, beside it, an onboarding prompt with that token already in it — one copy, and the
agent's setup has no second step.

**Two prompts, and they must stay two.** Settled 2026-08-02.

| | Where | Carries a token |
|---|---|---|
| The **standing** prompt | the Prompt tab and `/prompts/{role}` | **Never** |
| The **setup** prompt | the mint response, once | Yes — that one token |

The standing prompt is generic and stays exactly as it is: install, connect, join, the
habit. It is fetched by agents with `curl` and is on the console's `OPEN_PATHS`, which
means **it is served to anyone who can reach the hub, signed in or not** — a page that
earns its openness by holding nothing secret. Putting a credential in it would hand that
credential to every anonymous visitor, and the openness is not incidental: an agent needs
that page *before* it has any way to authenticate.

The setup prompt is a different document with a different life. It says: install the CLI,
set this token, join with it, and here is what it admits. It exists in one HTTP response
and is never served again.

Keeping them apart is what makes the openness of the first one safe to keep.

Consequences, both accepted:

- **One chance.** An operator who closes that page without copying has lost the prompt as
  surely as they have lost the token, and must mint a fresh one. That is already true of
  the secret; this only extends the same rule to the text around it. The page must say so.
- **It is a POST response, deliberately.** Not a URL, not a bookmark, not a `?token=`
  parameter. A page carrying a live credential must not be re-fetchable, cacheable, or
  linkable, and a response to a form submission is none of those things.

This lands in the Tokens screen rather than in a later mission: it is the same page, and
building it separately would mean rewriting the screen twice.

### Out of scope, on purpose

**Failed authentication attempts** — someone probing with a wrong or revoked credential — are
**not** part of this. Decided 2026-08-01: they are a different feature with a different
retention story and a write path driven by unauthenticated callers, and they deserve a
hub-wide treatment rather than a corner of a token screen. Filed separately.
