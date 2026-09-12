# Contributing

Discuss behavior changes in an issue before a large contribution. Keep changes
focused and include steps to reproduce bugs using synthetic data.

Use Python 3.12 and Node.js 22. Install Python dependencies with
`python -m pip install -c infra/constraints.docker.txt -e ".[dev]"` and run
`npm ci` in `apps/console-web`.

Before submitting a pull request:

```sh
npm --prefix apps/console-web ci
npm --prefix apps/console-web run build
python -m pytest -q
python -m ruff check apps services packages scripts tests
python scripts/check_public_release.py
```

Build the frontend before backend tests, which also check SPA serving. Do not call
paid models, operate real candidate accounts, or send messages in automated tests.
State separately which checks were mocked and which were verified live.

Never attach resumes, browser profiles, API keys, internal company requirements,
customer URLs, local databases, or internal presentations. Use fictional fixtures.
Changes to data retention must update `docs/DATA_PRIVACY.md`.

Contributions are distributed under the repository's MIT license.
