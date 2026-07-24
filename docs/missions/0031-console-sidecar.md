# Mission brief — the console as a sidecar

**Status:** planned · **Kind:** deployment · **Raised:** 2026-07-24 by the owner
**Blocked on:** the `/observe/*` routes — see below. Do not deploy before them.

## The idea

Run the human console as a **second container beside the hub**, in the same stack, rather
than as something an operator starts on their laptop.

> *"It's surely the same program. We just choose to run it in a different place… the GUI
> doesn't have any access that any other process wouldn't have."*

That is the whole argument, and it is correct. The console is already a client
([ADR 0005](../decisions/0005-one-api-every-client-is-a-client.md)): it holds no database
handle, no credentials the CLI lacks, and no privileged code path. Where it runs is a
deployment choice, not an architectural one. A sidecar makes that visible in the topology
instead of only in the docstrings.

It also fixes the practical problem, which is that nobody is going to run
`agent-mailbox console` on a laptop to see what the mailbox is doing. A URL they can open
is the point.

## Why it must not ship yet

**The console currently impersonates.** To show a mailbox it asks the API *as that
agent*, which the hub permits only because nothing authenticates. On loopback that is a
shortcut. Deployed on the LAN it becomes **an unauthenticated view of every mailbox,
reachable by anyone on the network** — and worse, a working demonstration that anyone can
read anyone's mail by setting a header.

The API was specified with `/observe/*` routes for exactly this
([M2 FR-010](../../kitty-specs/the-api-01KYADKK/spec.md)) and they were never built. That
is the real prerequisite, not the container.

## Order of work

1. **Build the `/observe/*` routes** the M2 spec already describes: a mailbox's contents,
   a whole thread, traffic stats. Unfiltered, and *explicitly* the operator's view rather
   than an agent's.
2. **Point the console at them** instead of impersonating.
3. **Then** ship the sidecar.

Between 1 and 3 the observation routes are an unguarded privileged surface, so they stay
bound to loopback on the hub until authentication exists — which is what the M2 spec
already says (FR-010) and what this mission must not quietly reverse.

## Shape

```yaml
services:
  agent-mailbox:            # the hub — owns the database
    image: salimfadhley/agent-mailbox:<version>
    volumes: [agent-mailbox-data:/data]

  agent-mailbox-console:    # the sidecar — owns nothing
    image: salimfadhley/agent-mailbox:<version>   # the same image
    command: ["console", "--host", "0.0.0.0"]
    environment:
      AGENT_MAILBOX_HUB: http://agent-mailbox:8080
    # no volume, no database, no secret
```

**The same image**, because it is the same program — which is the point being made. The
console container gets no volume and no database path, and that absence is the guarantee:
it *cannot* reach the store even if it wanted to, because there is nothing mounted.

## Definition of done

- The console runs as a sidecar and is reachable at a URL.
- It reads through `/observe/*`, not by impersonating anyone.
- The console container has no volume, no database, and no credential.
- Removing the console container leaves the hub entirely unaffected.
- The hub's unauthenticated status is stated on every console page, as it is now.

## Notes

- The console must degrade honestly if the hub is unreachable — an operator looking at a
  blank page should be told the hub is down, not shown an empty mailbox.
- This is also the first real test of the "everything is a client" claim: if the console
  needs anything the API does not already offer, the API is missing a route, and that is
  the finding, not a reason to give the console a shortcut.
