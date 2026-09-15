# orqelis.pro deployment handoff

Status: **not yet deployed**. The Render dashboard is accessible through Edge in `Sri Vishnu's workspace`. It still shows the Git-provider connection screen. This checkout has no Git remote and the connected GitHub app reports no accessible repositories. No Render services, paid resources, live database migrations, or DNS changes have been created in this deployment pass.

## Current Render proposal — awaiting spending approval

- Existing Supabase project `orqelis` remains the database; no Render Postgres or Redis is needed. Jobs use the existing PostgreSQL queue.
- Always-on web service: `0.5c-512mb`, US$7/month. Worker with ClamAV: `2c-4g`, US$85/month. Proposed base compute: **US$92/month**, excluding taxes and usage overages, on the US$0 Hobby workspace. This is a proposal, not a purchase authorization or a verified load-test result.
- A free web service reduces base compute to US$85/month but sleeps on idle. There is no free dedicated worker. ClamAV recommends 3–4 GiB RAM; a smaller worker has not been shown viable. The old Compose 2 GB worker limit is not verified sizing for this deployment.
- Build using `deploy/Dockerfile` (`uv sync --frozen --no-dev`). Web: `/app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log`. Configure Render PORT=8000; health path `/readiness`.
- Worker: `/app/.venv/bin/python -m app.jobs`. Before deployment, adapt the Compose signature updater to run alongside the worker on Render; it cannot use a shared Compose volume across Render services.
- Required existing migration command: `/app/.venv/bin/alembic upgrade head`, after checking the live revision. Local head is `72c149c94201`. No live migration was applied during these browser checks.
- Production secrets are prepared locally in ignored `var/deploy.env`; never commit or print them. The missing legal operator details and unverified recovery flags still block production startup. Do not invent values or mark reviews complete.
- GitHub OAuth email-read authorization was submitted in Edge; the subsequent repository-installation step was not verified complete. Finish access limited to the application repository after creating/pushing that repository.

Pricing checked 15 September 2026: https://render.com/pricing . Scanner sizing: https://docs.clamav.net/ . No final Render hostname exists yet, so final Spaceship DNS targets cannot be supplied until a service is created.

Prepared: `compose.deploy.yaml`, `deploy/Dockerfile`, Caddy HTTPS configuration, ClamAV signature updater, private `var/deploy.env` generator, and a redacted read-only Supabase preflight. The Linux image has not yet been built or smoke-tested on a server.

## Remaining external requirements

1. Hosting provider/account or existing Linux server; budget approval before any purchase. Allow memory for ClamAV, the web app and worker.
2. DNS access to Spaceship. Ordinary signed-in Edge tabs are not connected to this session's automation. Do not export browser cookies; use a supported browser connection or scoped DNS API credentials.
3. Operator/company name, address, contact email and jurisdiction. The guide's legal review and hosted restore-verification gates must be completed, not bypassed by setting false approval claims.
4. Supabase email delivery: enable email auth, set Site URL `https://orqelis.pro`, configure production SMTP, and include `{{ .Token }}` in the Magic Link email template. The app now exchanges email OTPs server-side. An authorized real-mailbox smoke test is still required.
5. Restore-test PostgreSQL **and Supabase Storage object bytes**. Database backups alone do not cover uploaded objects. The current filesystem backup helper does not cover hosted Supabase objects; do not set `BACKUPS_VERIFIED=true` until the hosted recovery path is verified.

## Server steps after the above are ready

Generate private configuration locally with `python -m scripts.prepare_deployment`. Transfer source and `var/deploy.env` through an authenticated encrypted channel. Never publish that file or print expanded Compose configuration containing its secrets.

```sh
docker compose -f compose.deploy.yaml build migrate
docker compose -f compose.deploy.yaml run --rm migrate
docker compose -f compose.deploy.yaml up -d
```

Run migrations on staging first. Migration `72c149c94201` adds immutable provider identity mapping. Retain a backup and previous image for rollback; avoid destructive database downgrades on live customer data.

Point apex A records at the host, and `www` at the same host or the apex. Preserve unrelated MX/TXT records. Check existing AAAA records before changing IPv6. Caddy needs ports 80/443 to obtain and renew certificates. Only the reverse proxy is exposed; the Python server stays internal.

Before public registration, verify HTTPS, email sign-in, tenant isolation, scan-to-confirmed-evidence, assessment, notification processing, exports, deletion and hosted recovery. Paid billing remains disabled. The broader product audit can follow deployment; broken authentication and unsafe data access cannot.

## Verification this session

- 88 isolated automated tests passed on 15 September 2026.
- Live Supabase database connectivity passed.
- The document bucket exists and is private, with no storage object policies.
- Checked application tables had RLS enabled.
- Tests are now isolated from the real database configured in `.env`.

References: [Supabase email OTP](https://supabase.com/docs/guides/auth/auth-email-passwordless), [Storage access control](https://supabase.com/docs/guides/storage/security/access-control), [ClamAV configuration](https://docs.clamav.net/manual/Usage/Configuration.html), [Caddy HTTPS](https://caddyserver.com/docs/automatic-https).
