# Contributing to ABM CRM

Thanks for helping. Bug reports, feature ideas and pull requests are all welcome.

## Reporting a bug

Open an issue with:
- what you did, what you expected and what happened;
- the Frappe, Frappe CRM and ABM CRM versions (`bench version`);
- the error from the browser console or from `Error Log` in desk, if there is one.

Please do not post passwords, access tokens or customer data.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Set up a bench as described in the README, then install pre-commit:
   ```bash
   cd apps/abm_crm
   pre-commit install
   ```
   Pre-commit runs ruff, eslint, prettier and pyupgrade.
3. Keep changes inside abm_crm. Extend Frappe CRM through `hooks.py`, and override frontend files in
   `frontend/src_override/` only when there is no other way. Keep overridden files as close to the
   original as possible, and mark each change with an `abm_crm:` comment.
4. Add or update tests in `abm_crm/tests/` and run them:
   ```bash
   bench --site your-test-site run-tests --app abm_crm
   ```
5. Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` ...).

By contributing, you agree that your contribution is licensed under the GNU AGPL v3.
