# Project Conventions

> **Note**: Copy this file to the root of your target repository and
> customize it for your project's tech stack and conventions.

## Tech Stack
- [filled per repository]

## Commands
| Command | Purpose |
|---------|---------|
| `npm test` / `pytest` | Run test suite |
| `npm run lint` / `ruff check .` | Run linter |
| `npm run build` / `python -m build` | Build project |

## House Rules
1. Always run tests before claiming a fix is complete.
2. Do not modify generated files, lock files, or vendored code.
3. Write descriptive commit messages referencing the bug ID.
4. Prefer minimal, surgical fixes over large refactors.
5. Add or update tests for every bug fix.

## Do-Not-Touch
- `node_modules/`, `__pycache__/`, `.git/`
- Any `*.lock` or `*.generated.*` files
