# Decision Moment `01KYMQ4GNS4B1PRD6WJ6W75DRG`

- **Mission:** `manual-activitypub-federation-v1-01KYJY10`
- **Origin flow:** `specify`
- **Slot key:** `specify.identity.name-scope`
- **Input key:** `hub_name_scope`
- **Status:** `resolved`
- **Created:** `2026-07-28T15:57:45.529793+00:00`
- **Resolved:** `2026-07-28T15:57:46.212287+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Is the hub name visible to other hubs, or purely local?

## Options

- purely local
- advertised not addressable
- federated addressing uses it

## Final answer

Purely local. The hub name never crosses the wire; the domain is the sole federated identity, per D-05 and C-008 (Lemmy's answer). Renaming therefore orphans nothing.

## Rationale

_(none)_

## Change log

- `2026-07-28T15:57:45.529793+00:00` — opened
- `2026-07-28T15:57:46.212287+00:00` — resolved (final_answer="Purely local. The hub name never crosses the wire; the domain is the sole federated identity, per D-05 and C-008 (Lemmy's answer). Renaming therefore orphans nothing.")
