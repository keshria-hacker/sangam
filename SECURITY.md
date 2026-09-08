# Security Policy

## Supported version

Only the latest `1.x` release receives fixes.

## Reporting a vulnerability

Do not open a public issue for a security concern. Contact the repository maintainer privately with reproduction steps and impact details.

## Deployment note

Sangam v1.1 is a local, single-user application. It uses a locally stored account session with **scrypt** password hashing (N=16384, r=8, p=1). Provider API keys added from Settings → Providers are **encrypted at rest** using **Fernet (AES-128-CBC with HMAC-SHA256)** with a `MASTER_KEY` from the environment. Sessions use **Bearer tokens** + **HTTP-only cookies** with **CSRF double-submit cookie protection**.

### Do not expose this instance to the public internet without:
- Setting `ENV=production`
- Setting strong `ALLOWED_ORIGINS` (no `null` origin)
- Using a reverse proxy with TLS
- Rotating `MASTER_KEY` periodically
- Reviewing rate limits for your threat model

See `ARCHITECTURE.md` for the security architecture overview.
