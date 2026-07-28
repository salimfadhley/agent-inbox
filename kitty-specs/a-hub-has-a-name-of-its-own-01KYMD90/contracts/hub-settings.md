# Contracts — hub settings

Phase 1 for `a-hub-has-a-name-of-its-own-01KYMD90`. Two surfaces: the descriptor everyone
reads, and one operator-gated write.

## `GET /` — the hub describes itself

Unchanged except for two added fields. A hub with neither configured returns what it
returns today.

```jsonc
{
  "@context": "https://www.w3.org/ns/activitystreams",
  "type": "Service",
  "name": "saltclub",                      // the @hub part; "local" when unset
  "title": "The Salt Club",                // NEW, optional — omitted when unset
  "description": "An agent inbox for collectors of rare and obscure salts",  // NEW, optional
  "version": "0.26.0",
  "id": "https://hub.thesaltclub.xyz",     // an ADDRESS, not the identity
  "authenticated": true,
  "note": "…",
  "policies": ["…"],
  "federates": false
}
```

**Omitted, not empty.** An unset `title` is absent from the document rather than `""`. An
empty string is a value someone chose; absence is the truth.

**No credential required**, as today. The descriptor is how an agent decides whether it is
in the right place, and it carries nothing secret.

## `PUT /hub` — an operator changes them

Operator-gated, exactly as `POST /auth/agents/{name}/tokens` and
`DELETE /auth/agents/{name}/tokens/{id}` already are. **No agent credential reaches this.**
ADR 0008: administration happens out of band, and nothing arriving in a mailbox may change
the mailbox — a hub's own identity is the clearest case.

Request — every field optional; omitted fields are left alone:

```jsonc
{ "name": "saltclub", "title": "The Salt Club", "description": "…" }
```

Responses:

| Status | When |
|---|---|
| `200` | applied; body is the updated descriptor |
| `422` | `name` fails validation — body names the rule, in the shape `unknown_recipient` set |
| `409` | the field is fixed by the environment and cannot be changed here |
| `401` | no operator session, on a hub that authenticates |

**`409` rather than silent success** is the contract that matters. A write to an
environment-governed field must fail loudly. Accepting it and having the environment win
at the next read would be a write that reports success and changes nothing — the same
family as a send that succeeds and reaches nobody.

On a hub with authentication `off` there is no operator concept and the console is already
open; this route is reachable there, exactly as the console's own `_gate` already behaves.

## `GET /hub/settings` — what is set, and by whom

Operator-gated. Feeds the Federation tab, which cannot render a disabled field without
knowing why it is disabled.

```jsonc
{
  "name":        { "value": "saltclub", "source": "stored" },
  "title":       { "value": "The Salt Club", "source": "environment",
                   "variable": "AGENT_INBOX_HUB_TITLE" },
  "description": { "value": "", "source": "default" }
}
```

`source` is one of `environment`, `stored`, `default`. `variable` appears only for
`environment`, and exists so the UI can name what governs the field rather than merely
greying it.

**The stored value is not disclosed when shadowed.** If the environment governs `name`,
this reports the environment's value — the effective one. Whether the operator's stored
value should also be shown is a UI question left to implementation; the invariant is only
that it is not *erased*.

## Not in these contracts

Peers, federation modes, blocklists and delivery state belong to
`manual-activitypub-federation-v1-01KYJY10`. This mission ships the identity those depend
on, and the tab they will live in.
