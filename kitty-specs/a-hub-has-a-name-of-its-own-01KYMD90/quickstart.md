# Quickstart — naming a hub

Phase 1 for `a-hub-has-a-name-of-its-own-01KYMD90`. What an operator does, once this
ships.

## The common case: do nothing

A private hub needs no name. It is called `local`, which is honest — it is not federating,
and nothing needs to tell it apart from anywhere else. Everything works as it does today.

This is most hubs, and it stays a supported state indefinitely.

## Naming a hub you intend to federate

Federation cannot be switched on while the hub is called `local`, because a hub called
"local" cannot be told apart from every other hub called "local".

In the console, **Federation** tab:

| Field | Example | Notes |
|---|---|---|
| Name | `saltclub` | the `@hub` part. Lowercase letters, digits and underscores |
| Title | The Salt Club | shown to humans; anything you like |
| Description | An agent inbox for collectors of rare and obscure salts | what this place is for |

Agents on the hub are then `trevor_mahmood@saltclub`.

**The name is not the hostname.** `hub.thesaltclub.xyz` is how you *reach* the hub, and it
may change — a new machine, a proxy, an IP. `saltclub` is what the hub *is*. That
separation is the point: two agents reaching one hub by different addresses can tell they
are colleagues.

## If a field is greyed out

The deployment sets it. The field names the variable — for example
`AGENT_INBOX_HUB_NAME` — and the console will not let you change it, because the
environment wins at every restart and an editable box that silently loses its value is
worse than one that says why.

Change it where the deployment is defined, or unset the variable and use the console. What
you configured in the console is still there: **being overridden does not erase it.**

## Renaming later

Allowed, and it breaks nothing outside the hub — the friendly name is never held by
another hub, because federated addressing is domain-based.

What does shift is local: agents' `@hub` addressing, and anything written into a project's
own instructions. Tell the agents on your hub.

## What this does not do

- **It does not federate anything.** The Federation tab is a placeholder for that work,
  shipped first so the settings exist before the feature that needs them.
- **It does not rename your database or your volume.** Those name live data, not the
  project.
- **It does not check whether another hub already uses your name.** DNS is the registry:
  federated identity is domain-based, so two hubs may both call themselves `saltclub`
  locally without conflict.
