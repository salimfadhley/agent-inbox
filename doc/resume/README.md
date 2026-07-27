# Resume File Naming

Resume prompts live in this directory and should be named:

```text
<timestamp>_<model-name>_<short-title>.md
```

Rules:

- Use UTC for `<timestamp>` in `YYYYMMDD-HHMM-UTC` form.
- Use a lowercase, filesystem-safe `<model-name>` such as `codex-gpt-5` or
  `claude-opus-5`.
- Use a short kebab-case `<short-title>` that describes the handoff.
- Do not use spaces, slashes, colons, or deployment-specific hostnames in the filename.

Example:

```text
20260727-2235-UTC_codex-gpt-5_restart-wake-release-gate-handoff.md
```

