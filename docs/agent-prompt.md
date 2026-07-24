# Getting on the mailbox

**The prompt is not kept here any more.** Open your hub's console and go to **Prompt**, or
fetch it plainly:

```bash
curl http://<your-console>/prompts.txt
```

## Why it moved

This file used to hold a copy of the prompt, and at one point there were three of them,
one per role. They drifted apart from each other and from the code, and guidance that had
been wrong for eight releases was still being pasted to every new agent.

There is one prompt now and it is generated. `src/agent_mailbox/prompts.py` is the only
copy, the console renders it, and `tests/test_console.py` fails if it names a command that
no longer exists. A prompt that lives in a document nobody executes cannot be checked, and
so it rots — this one had been telling agents to run `agent-mailbox-mcp` long after the
binary was unified into `agent-mailbox mcp`.

Generating it also lets each hub fill in **its own address**, so the commands can be
pasted as they stand. A `<host>` placeholder is something to get wrong, and a real
hostname written into a tracked file is a charter violation — this file previously
contained one.

## Roles are configuration, not a different prompt

Whether an agent is an ordinary agent, the `host`, or an `admin` is a line in its
`agent-mailbox.toml`. What a role *means* is fetched from the hub when the agent connects,
so a role can be added or redescribed without re-onboarding anybody, and there is no
second page to forget to update.
