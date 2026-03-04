# Contributing to taeys-hands

## Branch rules

**`main` is protected.** You cannot push directly to it — all changes must go through a pull request with at least one review.

## Workflow

```bash
# 1. Create a branch for your work
git checkout -b fix/describe-the-fix      # for bug fixes
git checkout -b feat/describe-the-feature # for new features

# 2. Make your changes and commit them
git add <files>
git commit -m "fix: short description of what and why"

# 3. Push your branch
git push origin fix/describe-the-fix

# 4. Open a pull request on GitHub
gh pr create --base main
```

## Commit message format

```
type: short description

Longer explanation if needed.
```

Types: `fix`, `feat`, `refactor`, `docs`, `test`

## Pull request checklist

- Branch is up to date with `main`
- Code tested manually (run `python3 server.py` and verify with Claude Code MCP)
- PR description explains what changed and why
- No private IPs, credentials, or personal config committed

## Platform-specific test environment

You need:
- Linux with X11
- Firefox with accessibility enabled (`about:config` → `accessibility.force_disabled` = `0`)
- Python 3.10+ with `gi.repository` (PyGObject / AT-SPI2)
- `xdotool`, `xsel`, `xdpyinfo`
- Optional: Redis, Neo4j for full pipeline testing

See `CLAUDE.md` for the full operational guide.

## Questions

Open an issue — we're happy to help.
