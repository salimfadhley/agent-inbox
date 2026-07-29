# Decision Moment `01KYN7QX8706MRGW27FF2E13N5`

- **Mission:** `federated-identity-and-trust-01KYN49V`
- **Origin flow:** `specify`
- **Slot key:** `specify.descriptor.availability`
- **Input key:** `descriptor_when_disabled`
- **Status:** `resolved`
- **Created:** `2026-07-28T20:47:58.215716+00:00`
- **Resolved:** `2026-07-28T20:47:58.890256+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Is the peer descriptor served while federation is disabled?

## Options

- always served
- only when enabled

## Final answer

Always served, reporting mode honestly. Requiring federation to be on creates a bootstrap deadlock between two fresh hubs. The disclosure objection is empty: GET / already publishes federates:false unauthenticated today.

## Rationale

_(none)_

## Change log

- `2026-07-28T20:47:58.215716+00:00` — opened
- `2026-07-28T20:47:58.890256+00:00` — resolved (final_answer="Always served, reporting mode honestly. Requiring federation to be on creates a bootstrap deadlock between two fresh hubs. The disclosure objection is empty: GET / already publishes federates:false unauthenticated today.")
