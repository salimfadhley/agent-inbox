# Decision Moment `01KYN7QVXF2ADJ1W0KHZ1X89MD`

- **Mission:** `federated-identity-and-trust-01KYN49V`
- **Origin flow:** `specify`
- **Slot key:** `specify.peers.warning-semantics`
- **Input key:** `warning_blocks_enable`
- **Status:** `resolved`
- **Created:** `2026-07-28T20:47:56.847139+00:00`
- **Resolved:** `2026-07-28T20:47:57.532243+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Does a Warning result block enabling a peer, or only annotate it?

## Options

- advisory with confirmation
- blocks enabling
- annotate only, no confirmation

## Final answer

Advisory, but enabling over a Warning requires explicit confirmation and the warning text is recorded in the audit entry. Blocking would make Warning indistinguishable from Failed. C-008 gives no steer: Lemmy has no equivalent check.

## Rationale

_(none)_

## Change log

- `2026-07-28T20:47:56.847139+00:00` — opened
- `2026-07-28T20:47:57.532243+00:00` — resolved (final_answer="Advisory, but enabling over a Warning requires explicit confirmation and the warning text is recorded in the audit entry. Blocking would make Warning indistinguishable from Failed. C-008 gives no steer: Lemmy has no equivalent check.")
