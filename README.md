# Orqelis — EU Bid Decision Engine

Orqelis is an evidence-first, low-cost SaaS decision engine that helps European SMEs decide which public procurement opportunities on **Tenders Electronic Daily (TED)** they should pursue, which they should reject, why, what evidence supports the decision, and what capability gaps prevent eligibility.

Unlike discovery-only tender platforms that only answer *"Which tenders match my keywords?"*, Orqelis answers:
> **"Which tenders should our company actually spend time and money bidding for?"**

---

## Key Principles & Capabilities

1. **Evidence-First Decision Logic**:
   - Every recommendation is grounded in verified company evidence documents (ISO certificates, turnover declarations, insurance, references).
   - Strict three-valued decision logic: `PASS`, `FAIL`, or `UNKNOWN`.
   - **Crucial rule**: Missing evidence is marked `UNKNOWN`, and `UNKNOWN` never passes an eligibility gate.
2. **Hard Eligibility Gates Before Scoring**:
   - Turnovers, accreditations, or exclusion criteria are evaluated as binary gates. High attractiveness cannot mask an eligibility failure.
3. **Cross-Border Friction Engine**:
   - Identifies non-blocking commercial risks (language requirements, foreign legal jurisdictions, localized performance demands) without treating them as legal disqualifiers.
4. **Transparent, Evidence-Linked Explanations**:
   - All criteria link directly to extracted clauses and specific document excerpts with exact character locators.
5. **Human Override & Dossier Reviews**:
   - SMEs can correct extracted tender criteria by supplying citations from official tender documents.
6. **Multi-Tenant Security & Privacy by Design**:
   - Strict tenant isolation, RBAC (`OWNER`, `ADMIN`, `MEMBER`, `VIEWER`), CSRF tokens, SSRF protection, active-content PDF quarantine, and GDPR-compliant account export and right-to-erasure workflows.
7. **Production-Ready & Minimalist Architecture**:
   - Fast, resilient modular monolith built on FastAPI and SQLAlchemy.
   - Clean adapter boundaries for Identity (`AuthProvider`), Object Storage (`ObjectStorage`), and Billing (`BillingProvider`), preparing for plug-and-play Firebase integration (Phase 10).

---

## Architecture Overview

```
Orqelis
├── app/
│   ├── main.py          # Application entrypoint & security middleware
│   ├── api.py           # REST API routes (auth, orgs, opportunities, analysis, documents)
│   ├── models.py        # SQLAlchemy relational schemas & tenant models
│   ├── db.py            # SQLite & PostgreSQL database session management
│   ├── auth.py          # Session management, CSRF validation, AuthProvider protocol
│   ├── storage.py       # ObjectStorage protocol, LocalStorage, secure file validator
│   ├── decision.py      # Core Bid Decision Engine, 3-valued logic, friction analysis
│   ├── requirements.py  # Deterministic & hybrid requirement extraction taxonomy
│   ├── ted.py           # Official TED Search API client, circuit breaker, rate limiter
│   ├── xml_parser.py    # eForms and legacy notice XML parser using defusedxml
│   ├── ingest.py        # Notice ingestion, version diffing, change impact engine
│   ├── jobs.py          # Persistent DB-backed job queue with worker crash recovery
│   ├── reviews.py       # User dossier review and manual override engine
│   ├── billing.py       # BillingProvider protocol and fail-closed subscription guard
│   ├── observability.py # Structured JSON logging, metrics, and health checks
│   ├── templates/       # Jinja2 templates (app.html, legal.html)
│   └── static/          # Vanilla CSS and JavaScript client (app.js, review.js)
├── migrations/          # Alembic database migrations
├── scripts/
│   ├── backup.py        # 256-bit AES-GCM encrypted database & storage backup/restore
│   ├── browser_check.py # End-to-end Playwright browser verification journey
│   ├── import_notices.py# Bulk XML/ZIP/JSON tender notice ingestion utility
│   ├── seed_demo.py     # Fixture loader for sample tender opportunities
│   └── ted_probe.py     # Contract verification against live TED Search API
└── tests/               # 76+ automated unit, property, security, and integration tests
```

---

## Quickstart & Local Setup

### 1. Prerequisites
- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) (recommended fast package installer)

### 2. Install Dependencies
```bash
uv sync --all-groups
```

### 3. Configure Environment Variables
Copy the example environment configuration:
```bash
cp .env.example .env
```
Default local configuration uses SQLite (`sqlite:///./var/orqelis.db`) and local object storage (`var/objects/`).

### 4. Run Database Migrations
```bash
uv run alembic upgrade head
```

### 5. Seed Demonstration Opportunities
Load sample procurement notices for immediate local testing:
```bash
uv run python scripts/seed_demo.py
```

### 6. Start the Application Server
```bash
uv run uvicorn app.main:app --reload --port 8000
```
Open your browser at `http://127.0.0.1:8000/login` to sign in. During local development, single-use authentication codes are displayed directly on the screen for instant workspace entry.

---

## Background Worker & Ingestion

Orqelis includes an internal, database-backed background job queue that handles document quarantine processing, notice diffing, and deadline alerts.

Run a single worker sweep:
```bash
uv run python -c "from app.jobs import run_once; run_once()"
```

Run a continuous worker daemon:
```bash
uv run python -c "from app.jobs import worker_loop; worker_loop()"
```

---

## Testing & Quality Assurance

The repository adheres to strict automated testing and security standards:

```bash
# Run complete test suite (76 tests)
uv run pytest

# Run linter and formatting checks
uv run ruff check .

# Check for package security vulnerabilities
uv run pip-audit

# Run end-to-end headless browser test with Playwright
python scripts/browser_check.py
```

---

## Encrypted Backups & Disaster Recovery

Orqelis includes an AES-256-GCM encrypted snapshot and restore tool that archives both the database dump and object storage:

```bash
# Generate a random 256-bit hex encryption key
python -c "import secrets; print(secrets.token_hex(32))"

# Create encrypted snapshot
python scripts/backup.py snapshot sqlite:///./var/orqelis.db var/objects var/backup.enc <YOUR_KEY>

# Restore from backup into a clean target directory
python scripts/backup.py restore var/backup.enc var/restored <YOUR_KEY>
```

---

## Phase 10: Firebase Adapter Boundary

Orqelis is built to allow seamless transition to Firebase without changing core business logic:
- **Authentication**: `FirebaseAuthProvider` in `app/auth.py` implements `AuthProvider`. Switch by setting `AUTH_PROVIDER=firebase` and injecting project credentials.
- **Object Storage**: `FirebaseStorage` in `app/storage.py` implements `ObjectStorage` using Google Cloud Storage buckets. Switch by setting `STORAGE_PROVIDER=firebase`.

---

## Legal & Compliance

- **Attribution**: Uses official EU procurement data from [Tenders Electronic Daily (TED)](https://ted.europa.eu) under the European Commission re-use policy.
- **GDPR**: Built-in endpoints for Account Data Archive export (`GET /api/v1/account/export`) and Permanent Erasure (`DELETE /api/v1/account`).
- **Privacy & Terms**: Public legal documentation served directly at `/legal/privacy`, `/legal/terms`, and `/legal/sources`.
