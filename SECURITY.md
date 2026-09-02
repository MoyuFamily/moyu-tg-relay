# Security Policy

## Reporting a vulnerability

Please do not include live credentials, Telegram session material, phone numbers, private deployment endpoints, or other sensitive data in a public GitHub Issue or Pull Request.

If a report requires sensitive evidence, contact the repository maintainers through a private channel first and share only the minimum information required to reproduce the issue.

## Credentials and session material

Treat the following as secrets:

- `OTP_RELAY_BEARER_TOKEN`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION_STRING`
- Telethon `*.session` / `*.session-journal` files
- any credentials used by reverse proxies or deployment systems

`TELEGRAM_SESSION_STRING` and a Telethon `.session` file both grant persistent Telegram account access. Never commit either form to Git, paste them into Issues or PRs, print them in CI logs, or include them in release artifacts.

`TELEGRAM_API_ID` and `TELEGRAM_ACCOUNT_ID` are identifiers rather than authentication secrets, but avoid publishing real account-specific values unnecessarily.

## Repository hygiene

Before making a fork, branch, or repository public, scan the complete Git history for leaked credentials and session files. Removing a secret only from the latest tree is not sufficient because old commits remain accessible.

If a credential has ever been committed, assume it is compromised: revoke or rotate it first, then remove it from history if the history is going to be published.

The repository intentionally ignores `.env`, `.env.*`, `.state/`, `*.session`, and `*.session-journal`; `.env.example` contains placeholders only.

## Deployment boundary

Standalone Docker/systemd deployments normally keep a file-backed Telethon session on the Relay host. Secret-managed deployments may inject `TELEGRAM_SESSION_STRING` at runtime. In both cases, session material belongs to the deployment secret boundary and must not enter source control or release artifacts.
