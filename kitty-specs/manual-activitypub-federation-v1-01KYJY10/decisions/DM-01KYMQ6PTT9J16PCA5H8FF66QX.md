# Decision Moment `01KYMQ6PTT9J16PCA5H8FF66QX`

- **Mission:** `manual-activitypub-federation-v1-01KYJY10`
- **Origin flow:** `specify`
- **Slot key:** `specify.config.list-precedence`
- **Input key:** `list_config_precedence`
- **Status:** `resolved`
- **Created:** `2026-07-28T15:58:57.371014+00:00`
- **Resolved:** `2026-07-28T15:58:58.067402+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Does env-over-stored precedence apply to peer lists and blocklists?

## Options

- lists stored-only
- env pins whole list
- env entries merge

## Final answer

Lists are stored-only. Scalars keep env-over-stored precedence; peer lists and blocklists live only in the store and are edited through the UI. No environment equivalent, so no merge semantics and no second configuration shape.

## Rationale

_(none)_

## Change log

- `2026-07-28T15:58:57.371014+00:00` — opened
- `2026-07-28T15:58:58.067402+00:00` — resolved (final_answer="Lists are stored-only. Scalars keep env-over-stored precedence; peer lists and blocklists live only in the store and are edited through the UI. No environment equivalent, so no merge semantics and no second configuration shape.")
