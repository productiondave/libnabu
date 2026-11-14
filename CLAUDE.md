# CLAUDE.md

See AGENT.md for the regeneration procedure and ground rules.

## Token economy (Pro plan)

- Open-ended searches ("where is X used", surveys across dirs) go to the Explore agent. If the file or symbol is known, use Grep/Read directly.
- Grep first, then Read with offset/limit. Don't read `gen/`, `build/`, `symbols.txt` or `report.txt` whole.
- Keep command output small: pipe make/build through `tail` or `grep`.
- Don't re-read after a successful Edit or re-run a clean `make`.
- Upstream changes: delegate to `libnabu-regen`.
