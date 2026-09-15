# Cloudflare deployment feasibility

Checked 15 September 2026. No Cloudflare resource, tunnel, DNS record, or paid subscription has been created. The user requires zero paid hosting and authorizes changes needed for Cloudflare.

## Existing application

The application runs FastAPI with synchronous SQLAlchemy/PostgreSQL access, synchronous HTTP clients, filesystem operations, and a persistent Python job loop. Document processing invokes the native ClamAV executable before PDF extraction. Supabase remains the database, authentication provider, and private object storage.

## Free Workers

Cloudflare supports Python/FastAPI, but it is a WebAssembly runtime, not the existing Linux Docker runtime. Its free limit is 10 ms CPU per invocation and 128 MB RAM. Supported HTTP clients must be asynchronous. The existing application is not directly compatible. Porting database access, requests, and scheduling does not solve native ClamAV's execution and memory requirements. Cloudflare Queues is available on Free, but a queue does not provide a separate Linux process for scanning.

Do not publish only the UI while representing the complete application as working. Do not skip scanning or change quarantined documents to READY to make a deployment pass.

## Zero-hosting-fee route preserving the application

Run the existing Docker deployment on an owner-operated machine and use a named Cloudflare Tunnel for public HTTPS routing. This is self-hosting behind Cloudflare, not hosting the backend on Cloudflare. The machine must stay powered on and connected; electricity, Internet, and existing Supabase limits still apply. Owner acceptance of this availability dependency is pending.

Local checks: cloudflared 2026.8.2 is installed. Docker CLI exists but the Docker Linux engine is not running. No Cloudflare account access or named tunnel has been verified. Production legal configuration, scanner startup, and recovery verification remain unresolved from the existing deployment checklist.

## Paid route (not authorized)

Cloudflare Containers runs Linux containers but requires Workers Paid, starting at US$5/month plus container usage beyond included allowances. It is not a zero-cost alternative and has not been enabled.

## Sources

- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/workers/languages/python/packages/
- https://developers.cloudflare.com/queues/platform/pricing/
- https://developers.cloudflare.com/containers/platform/pricing/
- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/
