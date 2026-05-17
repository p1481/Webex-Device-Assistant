# Migration: `ADMIN_COOKIE_SECRET` (Phase 1.4)

**Breaking change** in commit [`d2784e2`](../../../commit/d2784e2) on branch `phase1-4-hardening`.

## TL;DR

Real-mode deployments **must** now set a new environment variable:

```bash
export ADMIN_COOKIE_SECRET="<random-256-bit-secret>"
```

Without it, the app fails to start in real mode (`AppConfig.validate()` raises).

---

## What changed

Previously, the admin UI's session-cookie HMAC reused `WEBEX_WEBHOOK_SECRET` as
its signing key, with a hard-coded fallback (`"device-assistant-dev-admin-cookie-secret"`)
when unset. That fallback was the same in dev and production, meaning any leak
of the codebase trivially forged admin sessions.

After Phase 1.4:

| Setting | Mock mode (`WEBEX_MOCK_MODE=true`) | Real mode (`WEBEX_MOCK_MODE=false`) |
|---|---|---|
| `ADMIN_COOKIE_SECRET` set | Used | Used |
| `ADMIN_COOKIE_SECRET` unset | Falls back to dev secret | **Startup fails** (`_require_env`) |

Admin endpoints now return **HTTP 503** ("ADMIN_COOKIE_SECRET is not configured")
if the secret somehow ends up missing at request time in real mode.

## Why

1. **Key separation.** The webhook HMAC and the admin session HMAC are different
   trust boundaries; rotating one should not require rotating the other.
2. **Fail-closed.** Real-mode deployments should never silently fall back to a
   well-known dev secret.

## How to migrate

### 1. Generate a strong secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Or:

```bash
openssl rand -base64 48
```

### 2. Add to your environment

**systemd unit / `.env` file:**

```dotenv
ADMIN_COOKIE_SECRET=<paste-here>
```

**Inline (one-shot):**

```bash
WEBEX_MOCK_MODE=false \
WEBEX_BOT_TOKEN=... \
WEBEX_BOT_PERSON_ID=... \
WEBEX_WEBHOOK_SECRET=... \
ADMIN_COOKIE_SECRET=... \
.venv/bin/python -m uvicorn assistant_app.main:app
```

**Docker:**

```yaml
services:
  app:
    environment:
      ADMIN_COOKIE_SECRET: ${ADMIN_COOKIE_SECRET}
```

**Kubernetes:**

```yaml
env:
  - name: ADMIN_COOKIE_SECRET
    valueFrom:
      secretKeyRef:
        name: device-assistant
        key: admin-cookie-secret
```

### 3. Rotate (recommended on first deploy)

Setting a brand-new secret invalidates all existing admin login sessions —
which is exactly what you want when adopting this change, since the prior
sessions were signed with the (leaked-by-default) webhook secret. Admins will
need to re-login once after deployment.

### 4. Verify

```bash
# Should NOT contain the old default
curl -s http://localhost:8080/healthz

# Admin login should issue a fresh cookie
curl -i -c cookies.txt -X POST http://localhost:8080/admin/login \
  -d 'username=...&password=...'
```

## Rollback

If you must temporarily revert: set `WEBEX_MOCK_MODE=true`. The dev fallback
secret will then be used. Do not run real mode without `ADMIN_COOKIE_SECRET`.

## Test fixtures

All `tests/test_webex_integration.py` real-mode fixtures already include
`ADMIN_COOKIE_SECRET=test-cookie-secret` (commit `f615570`). If you add new
real-mode tests, set this in your environment dict.
