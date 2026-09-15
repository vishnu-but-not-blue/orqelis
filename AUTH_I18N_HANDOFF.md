# Production authentication and language work

## Baseline inspected on 15 September 2026

The working tree was clean at `e631e3ead570ffc8c17c019859d52b85f5683b42`.
Render's existing `orqelis` service (`srv-dakc4gtg1s2s73bqb8i0`) was live on that
same commit, with GitHub `vishnu-but-not-blue/orqelis`, branch `main`, automatic
deployment on commits, a free instance, and the existing Supabase database.
The historical DEPLOYMENT.md describes an earlier deployment attempt and is not
the current runtime status. No hosting provider or database was changed here.

## Exact authentication findings

The real mailbox's Orqelis Supabase signup email had no visible code. Its
confirmation URL contained `type=signup` and `redirect_to=http://localhost:3000`.
The FastAPI UI already requested `/auth/v1/otp` and verified `type=email`; however,
the request supplied no explicit redirect destination. Supabase's default signup
email used a confirmation link instead of the application's promised code, and
the email generated earlier captured the development redirect destination.

At the start of this work the Supabase Site URL was already `https://orqelis.pro`.
Allowed redirects were `https://orqelis.pro/**` and `https://www.orqelis.pro/**`.
No localhost, loopback, Render or other development redirect was configured.
Changing that configuration does not rewrite previously delivered email links.
Email was enabled; OTP length was eight digits and expiry 3,600 seconds.
Two Auth users existed, both confirmed. No Auth users were changed or deleted.
“Confirm email” was disabled; it was restored to enabled and verified after reload.

The application now explicitly sends `redirect_to=https://orqelis.pro/login`.
The code-entry field supports 6–10 numeric digits, autofill and focus. Identity
still requires Supabase's authoritative verified-email response, and the existing
server-side session, CSRF, origin checks and logout invalidation are retained.

## SMTP remains an explicit blocker

The current dashboard says: “Set up custom SMTP to edit templates”. It uses default
templates and does not allow the required subject/body changes without SMTP.
No email provider was selected, configured, purchased or subscribed to. The user
explicitly requested options before any provider decision.

The ready-to-apply template is `deploy/supabase-email-otp.html`. Once an approved
SMTP sender is configured, use this template for BOTH **Confirm sign up** and
**Magic link or OTP**, with subject **Your Orqelis sign-in code**. It displays
`{{ .Token }}` and a plain return link to the production code-entry page. It has
no automatic authentication link, development URL or `{{ .ConfirmationURL }}`.

Supported options checked on 15 September 2026:

| Provider | Price | Limits / requirements |
| --- | --- | --- |
| Resend Free | US$0 | 3,000/month; at most 100/day; verify sender domain |
| Brevo Free | US$0 | 300/day; verify sender domain; transactional sending activation |
| Resend Pro | US$20/month | 50,000/month; excess US$0.90/1,000 |

References: https://resend.com/pricing,
https://resend.com/docs/send-with-supabase-smtp,
https://help.brevo.com/hc/en-us/articles/8292912279954-Add-or-remove-emails-from-your-plan,
https://help.brevo.com/hc/en-us/articles/115000188150-Troubleshooting-Issues-with-Brevo-SMTP.
Supabase's built-in mailer is restricted to project-team recipients and is not a
general production delivery solution: https://supabase.com/docs/guides/auth/auth-smtp.

Do not claim the production OTP journey is complete. A real-mailbox request,
received numeric code, successful verification, secure session, application access,
logout and replay rejection must still be verified after the approved SMTP setup.
Current mailbox inspection is evidence of the original failure, not a successful
OTP delivery test.

## Internationalization

Eight catalogs cover application navigation, authentication, onboarding, company
profile, opportunities, assessments, evidence, settings, forms, notifications,
errors and empty states. The compact header selector defaults to English and
persists locally. Tender/source text, user-entered data, identifiers, API enums,
source excerpts and stored decisions are not translated. Legal documents remain
identified as original English, with localized navigation.

See `app/static/locales/README.md` for authoring, escaping and additional languages.
The browser regression uses isolated local data and checks eight languages,
navigation, mobile layouts, unmodified source text, stable form values and logout
replay rejection. It does not send email or modify production data.
