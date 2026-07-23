"""The prompt catalog: role prompts served live-rendered from templates.

Templates live in ``prompts/*.md`` next to this module, each with a small frontmatter
(``title``, ``description``). They are rendered with *this hub's* live coordinates via
:class:`string.Template` (``$hub_url``, ``$host_agent``, …) so a human can just point an
agent at ``<hub>/prompts/<name>`` and it arrives pre-filled. Drop a new ``.md`` in and
it appears in the index — no code change.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from agent_inbox.config import Config, hub_version

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return ``(metadata, body)`` for a ``---``-delimited frontmatter block."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, text[end + 4 :].lstrip("\n")


def prompt_context(config: Config) -> dict[str, str]:
    """The substitution variables available to every prompt template."""
    base = config.base_url()
    return {
        "hub_name": config.hub_name,
        "hub_url": base,
        "mcp_endpoint": f"{base}/<project>/<agent>/mcp",
        "prompts_url": f"{base}/prompts",
        "admin_agent": config.admin_agent or "(unset)",
        "host_agent": config.host_agent or "(unset)",
        "version": hub_version(),
    }


def _template_path(name: str) -> Path | None:
    """Resolve a prompt name to its file, rejecting anything path-y (no traversal)."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = _PROMPTS_DIR / f"{name}.md"
    return path if path.is_file() else None


def list_prompts() -> list[dict[str, str]]:
    """List available prompts as ``{name, title, description}``, sorted by name."""
    out: list[dict[str, str]] = []
    for path in sorted(_PROMPTS_DIR.glob("*.md")):
        meta, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
        out.append(
            {
                "name": path.stem,
                "title": meta.get("title", path.stem),
                "description": meta.get("description", ""),
            }
        )
    return out


def render_prompt(name: str, config: Config) -> str | None:
    """Render one prompt with the hub's live coordinates, or ``None`` if unknown."""
    path = _template_path(name)
    if path is None:
        return None
    _, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    return Template(body).safe_substitute(prompt_context(config))


def render_index(config: Config) -> str:
    """Render the catalog index (markdown) of available prompts."""
    base = config.base_url()
    lines = [
        f"# {config.hub_name} — prompt catalog",
        "",
        'Point an agent at one of these URLs ("read and action this page"):',
        "",
    ]
    for entry in list_prompts():
        url = f"{base}/prompts/{entry['name']}"
        lines.append(f"- [`{entry['name']}`]({url}) — {entry['description']}")
    return "\n".join(lines) + "\n"
