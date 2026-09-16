# Orqelis acquisition and SEO

## Account configuration

- Existing Google account, existing Analytics account 400605934.
- New Orqelis GA4 property 554554004; production web stream 15785633024.
- Public measurement ID: `G-GHGKC163XE` (not a credential).
- Domain Search Console property: `sc-domain:orqelis.pro`, DNS ownership verified through Cloudflare Domain Connect. Keep its verification TXT record. Existing website/email records are unchanged.
- One Google tag integration; no Tag Manager container or duplicate tag.

## Privacy and measurement contract

Basic opt-in: no Google request before consent. Equal accept/reject actions; persistent preferences and withdrawal. DNT/GPC suppress collection. Cookies/consent last at most 180 days; no cookie renewal. GA4 user/event retention is two months, with reset on new activity disabled. Enhanced measurement, Google signals and advertising personalization are disabled. Use no Google Ads links, User-ID, user-provided data or remarketing audiences.

Only fixed event names and fixed page categories can reach the tag. Public URLs are a closed allowlist; all private paths become `/app`. Queries, fragments, tender IDs/titles, names, email, company identifiers, evidence, documents, Supabase identifiers and form values are not event inputs. Referrers are restricted to known public search engines; campaign query parameters are intentionally discarded, including arbitrary UTM values. Acquisition is therefore measured through safe referrers and Search Console rather than unrestricted campaign metadata.

| Event | Trigger |
| --- | --- |
| `page_view` | Public allowlisted page after consent; never an authenticated page view |
| `auth_start` | Successful email-code request |
| `sign_up` | Successful verified identity creating its first Orqelis application account |
| `login` | Successful verified identity for an existing application account |
| `onboarding_complete` | Final onboarding step completed |
| `opportunity_view` | Opportunity detail successfully loaded; no tender identifier |
| `assessment_start` | User explicitly starts assessment |
| `assessment_complete` | That assessment succeeds |
| `decision_complete` | Assessment returns BID, STRONG_BID or NO_BID; no result value sent |

`decision_complete` measures a completed advisory result, not a human approval, submitted offer or award. Conditional/unknown results do not fire it. Google's standard consented session/engagement events may also appear. No synthetic customer conversions should be generated just to populate a report.

## Indexing and language architecture

The homepage now renders public HTML independent of login state. `/` is English; `/de/`, `/fr/`, `/es/`, `/it/`, `/nl/`, `/pl/`, `/pt/` are complete server-rendered translations with reciprocal hreflang and x-default. Public language links synchronize the existing application preference. They do not translate procurement evidence. The three guides are explicitly English and have no invented translation alternates.

The sitemap contains 12 URLs: eight homepages, three guides and the existing source policy. App/auth/API/health/static routes and unfinished legal drafts receive X-Robots-Tag noindex; app pages also have a noindex meta tag. Crawling is permitted so crawlers can observe noindex. This is indexing control, not an access-control mechanism; API authorization remains enforced. Query variants and internal Render origins are noindex. `www` redirects to the HTTPS apex. Unknown browser routes return a useful HTML page with HTTP 404; API errors retain JSON.

Public metadata includes unique titles/descriptions, self-canonicals, Open Graph/Twitter image, favicon and Organization/WebSite/WebPage JSON-LD. No invented ratings, prices, affiliation or business address. JSON-LD uses per-response CSP nonces; no unsafe-inline/eval permission was added.

## Research and initial keyword map — 16 September 2026

Live web search sampled English, German, French, Spanish, Italian, Dutch, Polish and Portuguese queries. These are qualitative intent observations, not keyword-volume estimates or personalized Google rank measurements. No paid SEO data or fabricated search volumes were used.

| Language | Search cluster | Intent | Target |
| --- | --- | --- | --- |
| English | EU tenders, European public procurement, tender discovery, TED opportunities | Discovery / product evaluation | `/`, `/guides/find-eu-tenders` |
| English | tender qualification, evidence-backed bid/no-bid analysis, whether to bid | Evaluation / practical process | `/guides/bid-no-bid-decisions` |
| English | cross-border procurement, European tender eligibility checklist | Preparation / research | `/guides/cross-border-tender-qualification` |
| German | öffentliche Ausschreibungen Europa, TED Ausschreibungen, Eignung prüfen | Discovery and qualification | `/de/` |
| French | appels d’offres européens, qualification, décision go/no-go | Discovery and evaluation | `/fr/` |
| Spanish | licitaciones europeas, requisitos, decidir presentar oferta | Discovery and participation | `/es/` |
| Italian | gare europee, ricerca bandi TED, requisiti di partecipazione | Discovery and qualification | `/it/` |
| Dutch | Europese aanbestedingen vinden, geschiktheid, bid/no-bid | Discovery and evaluation | `/nl/` |
| Polish | przetargi unijne TED, warunki udziału, ocena przetargu | Discovery and qualification | `/pl/` |
| Portuguese | concursos públicos europeus, TED, requisitos de participação | Discovery and preparation | `/pt/` |

Observed official/navigational intent: [TED](https://ted.europa.eu/en/), [Spanish tender search guidance](https://commission.europa.eu/funding-and-tenders/find-calls-tender_es), [Polish TED](https://ted.europa.eu/pl/), [Italian TED](https://ted.europa.eu/it/), [Dutch government guidance](https://ondernemersplein.overheid.nl/product-dienst-en-innovatie/opdrachten-en-aanbestedingen/werken-voor-de-overheid-via-een-aanbesteding/), [Portuguese Commission guidance](https://portugal.representation.ec.europa.eu/negocios-e-financiamento/concursos-e-contratos_pt). Broad TED searches frequently lead to official search portals or individual notices, so Orqelis should explain its qualification workflow instead of impersonating the official directory.

Observed commercial competitors and positioning, based on their own pages (claims not independently audited):

- [TenderFilter](https://tenderfilter.eu/de/): SME-focused TED discovery and alerts; discovery intent.
- [Tenderbold](https://tenderbold.com/): broad European tender discovery and bidding workflow.
- [Deepbloo](https://fr.deepbloo.com/free-resources/solution-de-gestion-dappels-doffres): tender monitoring and opportunity management including go/no-go.
- [TenderCrunch](https://tendercrunch.com/): document analysis and response writing; broader response-automation intent than Orqelis's current functionality.
- [TED Monitor](https://tedmonitor.eu/it/software-appalti-pubblici-europei): Italian-language TED discovery software.
- [HelloTender](https://www.hellotender.eu/nl): Dutch tender discovery and alerts.
- [BidIndex](https://bidindex.eu/pt): Portuguese-language European tender aggregation.
- [EuProcure](https://euprocure.com/): sector-specific IT/software procurement discovery.

Inference: Orqelis's defensible initial content is source-traceable qualification, uncertainty and bid effort, alongside TED discovery. Do not claim exhaustive national coverage, automated bid submission, AI proposal writing, guaranteed qualification or wins. Revisit the map using actual Search Console impressions and consented acquisition data after indexing.

## Validation and operation

Run `pytest`, `ruff check .`, Node syntax checks and `node --test tests/i18n.test.cjs`; run `python -m scripts.check_i18n_browser` and `python -m scripts.check_seo_browser`. The latter proxies an isolated test server through a fake production origin and stubs Google requests to test opt-in, rejection, withdrawal, event allowlisting and sensitive URL stripping without sending test secrets externally.

Public HTML renders without JS, uses system fonts and no third-party rendering dependencies. Analytics is async and absent before consent. No field Core Web Vitals claim can be made until enough real data accumulates. Google crawling, indexing, report processing and ranking take time and are not guaranteed.

Implementation references: [GA4 manual pageviews](https://developers.google.com/analytics/devguides/collection/ga4/views), [Google hreflang guidance](https://developers.google.com/search/docs/specialty/international/localized-versions), [noindex crawling requirements](https://developers.google.com/search/docs/crawling-indexing/block-indexing), [Google tag CSP](https://developers.google.com/tag-platform/security/guides/csp).
