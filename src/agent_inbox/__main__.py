"""``python -m agent_inbox`` — the same program, reached without the console script.

**Why this exists, and what it does not promise.**

On Windows a running `.exe` is locked by the operating system, and `uv tool install
--force` has to replace `agent-inbox.exe` to upgrade. An agent whose MCP server is
running holds that file open, so the upgrade fails with `Failed to install entrypoint`
— which the onboarding prompt currently explains as "this error means the upgrade
worked", because the package itself did get replaced.

The owner's suggestion (2026-08-05): launch the module rather than the shim, since
Windows does not lock `.py` files the way it locks executables. That is the reason this
file is here — it makes

    python -m agent_inbox mcp

a supported way in, so a harness can be pointed at the module instead of the script.

**It is a mitigation, not a cure, and the difference matters.** The shim is only one of
the files an upgrade replaces: a uv tool venv also contains its own `python.exe`, and a
process launched through *that* interpreter holds it open just as firmly. So this is
expected to remove the entrypoint failure specifically, and may simply move the problem
to a different file. That has not been verified on Windows — this is written on macOS,
where nothing is locked and the question cannot be asked.

Anyone testing it there should say which of the two happens. `igor_laszlo` and
`mariana_taphrale` both run Windows with scoop-installed interpreters, which is the
configuration where it matters most.
"""

import sys

from agent_inbox.cli import main

if __name__ == "__main__":
    # `main` returns the exit code rather than raising, exactly as the console scripts
    # expect — so the two entry points cannot drift in how they report failure.
    sys.exit(main())
