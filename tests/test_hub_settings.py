"""Hub settings: precedence, and the assertion that overriding does not erase.

The mission's highest risk is invisible to inspection. If startup — or a write, or a
console submit — puts the environment's value into the store, an operator who later
unsets the variable has silently lost their setting, and it looks like it worked.
That is this project's recurring defect shape, so it is asserted directly here rather
than trusted to the design.
"""

import pytest

from agent_inbox.hub_settings import ResolvedSetting, resolve_hub_settings
from agent_inbox.store import InMemoryStore


def test_nothing_configured_is_the_ordinary_state() -> None:
    """Every hub predating this table looks like this, so it is the base case."""
    resolved = resolve_hub_settings({}, {})

    assert resolved["name"] == ResolvedSetting("local", "default")
    assert resolved["title"] == ResolvedSetting(None, "default")
    assert resolved["description"] == ResolvedSetting(None, "default")


def test_stored_wins_when_the_environment_is_silent() -> None:
    resolved = resolve_hub_settings({"name": "saltclub", "title": "The Salt Club"}, {})

    assert resolved["name"] == ResolvedSetting("saltclub", "stored")
    assert resolved["title"] == ResolvedSetting("The Salt Club", "stored")
    # Not set anywhere: still absent, not an empty string pretending to be a value.
    assert resolved["description"] == ResolvedSetting(None, "default")


def test_environment_wins_and_names_its_variable() -> None:
    resolved = resolve_hub_settings(
        {"name": "saltclub"}, {"AGENT_INBOX_HUB_NAME": "pepperclub"}
    )

    assert resolved["name"] == ResolvedSetting(
        "pepperclub", "environment", "AGENT_INBOX_HUB_NAME"
    )


def test_the_legacy_prefix_is_reported_as_the_variable_in_effect() -> None:
    """A console naming the wrong variable sends the operator to edit the wrong thing.

    Deployments written before the rename carry `AGENT_MAILBOX_*`, and telling their
    operator that `AGENT_INBOX_HUB_NAME` governs the field would be false.
    """
    resolved = resolve_hub_settings({}, {"AGENT_MAILBOX_HUB_NAME": "oldclub"})

    assert resolved["name"].value == "oldclub"
    assert resolved["name"].variable == "AGENT_MAILBOX_HUB_NAME"


def test_the_new_prefix_wins_over_the_old_one() -> None:
    resolved = resolve_hub_settings(
        {},
        {"AGENT_INBOX_HUB_NAME": "new", "AGENT_MAILBOX_HUB_NAME": "old"},
    )

    assert resolved["name"].value == "new"
    assert resolved["name"].variable == "AGENT_INBOX_HUB_NAME"


@pytest.mark.asyncio
async def test_overriding_does_not_erase() -> None:
    """Set, override, unset, and get your own value back.

    The assertion that matters is the middle one: the store is read **directly** while
    the environment shadows it. A resolver that reads correctly from a store that has
    already been overwritten passes a weaker test and fails the operator.
    """
    store = InMemoryStore()
    await store.set_hub_setting("name", "saltclub")

    # The operator's value is in force.
    assert resolve_hub_settings(await store.hub_settings(), {})["name"] == (
        ResolvedSetting("saltclub", "stored")
    )

    # A deployment sets the variable. The environment wins for *reads*...
    env = {"AGENT_INBOX_HUB_NAME": "deployment-name"}
    stored = await store.hub_settings()
    assert resolve_hub_settings(stored, env)["name"].value == "deployment-name"

    # ...and the operator's own value is untouched underneath it. Assert the store,
    # not the resolver: this is the line that stands between the design and data loss.
    assert (await store.hub_settings())["name"] == "saltclub"

    # The variable is removed. What comes back is what the operator configured.
    assert resolve_hub_settings(await store.hub_settings(), {})["name"] == (
        ResolvedSetting("saltclub", "stored")
    )


@pytest.mark.asyncio
async def test_cleared_is_distinguishable_from_never_set() -> None:
    """`""` is a value someone chose; absence is never having chosen.

    The console renders them the same and the API must not, or clearing a title becomes
    indistinguishable from a hub that never had one.
    """
    store = InMemoryStore()
    await store.set_hub_setting("title", "")
    assert resolve_hub_settings(await store.hub_settings(), {})["title"] == (
        ResolvedSetting("", "stored")
    )

    await store.set_hub_setting("title", None)
    assert resolve_hub_settings(await store.hub_settings(), {})["title"] == (
        ResolvedSetting(None, "default")
    )
