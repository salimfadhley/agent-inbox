"""What a hub keeps about itself, and which source decided it.

Its own module rather than part of `serve`, because both the server and the API need
it and `serve` imports the API — so putting it there would be a cycle. It is also the
honest home: this is hub state, not server startup.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

#: The project is `agent-inbox`, so its variables are `AGENT_INBOX_*`.
ENV_PREFIX = "AGENT_INBOX_"

#: What they used to be called, and still are on every deployment written before the
#: rename. Dropping it would leave a hub unable to read its own configuration.
LEGACY_ENV_PREFIX = "AGENT_MAILBOX_"


def env_with_source(name: str, environ: Mapping[str, str]) -> tuple[str, str] | None:
    """The value **and the variable it came from**, or None when neither is set.

    The variable name matters as much as the value. A console that greys out a field and
    says `AGENT_INBOX_HUB_NAME` governs it, on a deployment configured through
    `AGENT_MAILBOX_HUB_NAME`, sends the operator to edit a variable that is not the one
    in effect — and they conclude the console is broken.
    """
    for prefix in (ENV_PREFIX, LEGACY_ENV_PREFIX):
        variable = f"{prefix}{name}"
        value = environ.get(variable)
        if value is not None:
            return value.strip(), variable
    return None


#: The three things a hub keeps about itself, and what each falls back to. `name` is an
#: address component and always resolves to something; the other two are presentation
#: and legitimately absent — the state of every hub that existed before them.
HUB_SETTING_KEYS: tuple[str, ...] = ("name", "title", "description", "federation")

#: Kept in the same table, and deliberately **not** in HUB_SETTING_KEYS: the signing
#: key is hub state, but it is not a *setting* — nothing reports it, nothing resolves it
#: against the environment, and no route may write it. Keeping it out of that tuple is
#: what stops it appearing in `GET /hub/settings` by anyone simply adding a key.
SECRET_SETTING_KEYS: frozenset[str] = frozenset({"signing_key"})
_HUB_SETTING_ENV = {
    "name": "HUB_NAME",
    "title": "HUB_TITLE",
    "description": "HUB_DESCRIPTION",
    "federation": "FEDERATION",
}
_HUB_SETTING_DEFAULTS: dict[str, str | None] = {
    "name": "local",
    "title": None,
    "description": None,
    # Off unless something says otherwise. NFR-001, and the only safe default.
    "federation": "disabled",
}


@dataclass(frozen=True, slots=True)
class ResolvedSetting:
    """A value, and who decided it.

    Copied in shape from `client.effective_settings()`, which already answers "which one
    won" for client configuration. Two nearly-identical answers to one question is worse
    than one, and this project has paid for near-duplicates before.
    """

    value: str | None
    source: str
    variable: str | None = None


def resolve_hub_settings(
    stored: Mapping[str, str],
    environ: Mapping[str, str] | None = None,
    *,
    default_name: str = "local",
) -> dict[str, ResolvedSetting]:
    """Environment, then stored, then default — and say which.

    ``default_name`` is what the hub was constructed with — on a real deployment that
    is already the environment's value, and on a hub with nothing configured it is
    ``local``. Passing it keeps a hub built directly, as the tests do, reporting its
    own name rather than falling through to ``local``.

    **The environment shadows; it never replaces.** Nothing here writes to `stored`,
    and nothing at startup may either: an operator who sets a variable, restarts, then
    unsets it must get their configured value back. Overwriting it would be silent
    data loss that looks exactly like it worked.
    """
    env = os.environ if environ is None else environ
    resolved: dict[str, ResolvedSetting] = {}
    for key in HUB_SETTING_KEYS:
        found = env_with_source(_HUB_SETTING_ENV[key], env)
        if found is not None:
            resolved[key] = ResolvedSetting(found[0], "environment", found[1])
            continue
        if key in stored:
            resolved[key] = ResolvedSetting(stored[key], "stored")
            continue
        fallback = default_name if key == "name" else _HUB_SETTING_DEFAULTS[key]
        resolved[key] = ResolvedSetting(fallback, "default")
    return resolved
