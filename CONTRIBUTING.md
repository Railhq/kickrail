# Contributing to Kickrail

Thanks for helping. Bug reports, fixes and docs improvements are all welcome.

## Before you start

- **Bugs:** open an issue with steps to reproduce, what you expected and what happened.
- **Security issues:** don't open a public issue. Use the repository's [private vulnerability reporting](https://github.com/Railhq/kickrail/security/advisories/new).
- **Bigger changes:** open an issue or a discussion first, so we can agree on the approach before you spend time on it.

## Run it locally

You need Python 3.13, Node 20+ and a local MongoDB.

```sh
make setup        # venv, npm install, example env files
make backend      # :8000
make web          # :3000
make check        # backend tests, then web typecheck and lint
```

See the [README](README.md) for the settings `backend/.env` and `web/.env.local` need.

## Pull requests

- Branch from `main` and open the pull request against `main`. It is squash merged, so the PR title becomes the commit message: keep it short and in the imperative ("Add PayPal payout retries").
- Add or update tests for behaviour changes. `make check` must pass.
- Match the surrounding code: its naming, comment density and idioms.
- Never commit secrets or real customer data. Use `@example.com` addresses in tests.

## Contributor License Agreement

The first time you open a pull request, a bot will ask you to sign the [CLA](CLA.md) by posting a comment. It takes one comment and covers all your future contributions. You keep the copyright in your work; the CLA lets us include it and keep Kickrail's licensing flexible, including offering it under a commercial license alongside the [AGPL-3.0](LICENSE).
