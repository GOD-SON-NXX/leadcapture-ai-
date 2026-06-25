# LeadCapture AI

**Automated lead capture and conversion system for local service businesses** (HVAC, plumbing, roofing).

Find businesses on Google Maps, audit their websites, deploy AI chatbots, run free pilots, and convert to paying customers — all without human sales calls.

## Architecture

```
├── src/
│   ├── app.py                 # FastAPI main entry point
│   ├── config.py              # Environment configuration
│   ├── database/
│   │   ├── schema.sql         # SQLite schema
│   │   └── connection.py      # DB connection management
│   ├── modules/
│   │   ├── lead_finder.py     # MODULE 1: Google Places scraping
│   │   ├── website_auditor.py # MODULE 2: Website audit & scoring
│   │   ├── chatbot_engine.py  # MODULE 3: OpenAI GPT-4o-mini chatbot
│   │   ├── pilot_manager.py   # MODULE 4: Trial management & dashboard
│   │   ├── payment_handler.py # MODULE 5: Wise verification & billing
│   │   ├── email_sequences.py # MODULE 6: Email templates & sending
│   │   └── admin_dashboard.py # MODULE 7: Admin metrics & actions
│   ├── templates/             # Email HTML templates
│   └── static/
│       └── embed.js           # Chatbot widget for business websites
├── data/                      # SQLite database & logs (auto-created)
├── .env.example               # Environment variables template
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container deployment
└── start.sh                   # Startup script
```

## Quick Start

### 1. Prerequisites

- Python 3.10+
- OpenAI API key (GPT-4o-mini access)
- Google Places API key
- Resend API key (for email)

### 2. Setup

```bash
# Clone and enter the project
cd leadcapture-ai

# Create .env from template
cp .env.example .env
# Edit .env with your API keys

# Install dependencies
pip install -r requirements.txt

# Start the server
python src/app.py
```

### 3. Verify

```bash
# Health check
curl http://localhost:8000/health

# Dashboard
open http://localhost:8000/admin
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key for chatbot | Yes |
| `GOOGLE_PLACES_API_KEY` | Google Places API key | Yes |
| `RESEND_API_KEY` | Resend API key for emails | Yes |
| `EMAIL_FROM` | Sender email address | Yes |
| `APP_URL` | Public URL of your deployment | Yes |
| `ADMIN_PASSWORD` | Admin dashboard password (future) | Optional |
| `MONTHLY_PRICE` | Subscription price (default: 97) | No |
| `DATABASE_PATH` | SQLite database path | No |

## Modules

### Module 1: Lead Finder
Scrapes Google Places API for service businesses in any city. Filters by rating (≥4.0) and reviews (≥10). Deduplicates by phone+website.

**Usage:** `POST /api/leads/search` with `{"city": "Austin", "state": "TX"}`

### Module 2: Website Auditor
Fetches each business website, checks for chatbots, contact forms, clickable phones, and CTAs. Scores 0-100 and sends HTML audit reports via Resend.

**Usage:** `POST /api/audit/run?lead_id=1` or batch: `POST /api/audit/batch?limit=10`

### Module 3: Chatbot Engine
Custom OpenAI GPT-4o-mini chatbot with:
- Configurable system prompts per business
- Server-Sent Events (SSE) for real-time streaming
- Lead info extraction (name, phone, service, zip, time)
- Escalation to business owner when needed
- All conversations stored in SQLite

**Embed in websites:** Paste the generated `<script>` tag from the business dashboard.

### Module 4: Pilot Management
- Trial signup at `/pilot/signup`
- 7-day countdown with daily email sequence
- Business dashboard at `/dashboard/{id}`
- Day 1: Welcome + setup instructions
- Day 3: Value email with conversation count
- Day 5: Invoice with Wise details
- Day 6: Reminder email
- Day 7: Decision/expiry

### Module 5: Payment & Activation
- Manual Wise verification (no Stripe)
- Admin marks payments as PAID/UNPAID
- Business auto-activates on payment
- Monthly billing cycle: 25th reminder → 30th due → 33rd deactivate
- 3-day grace period
- Reactivation link for expired customers

### Module 6: Email Sequences
All emails use templates with `{{variable}}` substitution. Templates:
- `audit_initial`, `audit_followup`, `audit_final`
- `pilot_welcome`, `pilot_day3_value`, `pilot_day5_invoice`
- `pilot_day6_reminder`, `pilot_day7_decision`
- `billing_reminder`, `billing_due`, `billing_overdue`
- `activation_welcome`, `deactivation_notice`

### Module 7: Admin Dashboard
Available at `/admin`. Shows:
- Total leads, audits sent, pilots active, paying customers
- MRR, churn rate, email open/click rates
- Pending payments with Verify/Reject actions
- Business management (view, deactivate)
- Conversation logs with full message history

### Module 8: Deployment
- Single command: `python src/app.py` or `./start.sh`
- SQLite auto-creates on first run
- Docker: `docker build -t leadcapture-ai . && docker run -p 8000:8000 leadcapture-ai`
- Health check at `/health`
- Background scheduler handles daily pilot checks and batch audits automatically

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/` | Landing page |
| POST | `/api/leads/search` | Search for leads |
| GET | `/api/leads` | List all leads |
| POST | `/api/audit/run` | Audit a single website |
| POST | `/api/audit/batch` | Batch audit fresh leads |
| POST | `/api/chat/start` | Start a conversation |
| GET | `/api/chat/stream` | SSE chatbot stream |
| GET | `/pilot/signup` | Pilot signup form |
| POST | `/api/pilot/signup` | Submit pilot signup |
| GET | `/dashboard/{id}` | Business dashboard |
| GET | `/reactivate` | Reactivation page |
| POST | `/api/payments/record` | Record a payment |
| POST | `/api/pilot/run-daily-checks` | Manual pilot check trigger |
| GET | `/admin` | Admin dashboard |
| GET | `/admin/payments` | Payment management |
| GET | `/admin/leads` | Lead management |
| GET | `/admin/business/{id}` | Business detail view |
| GET | `/admin/conversation/{id}` | Conversation viewer |
| GET | `/admin/verify-payment/{id}` | Verify payment |
| GET | `/admin/reject-payment/{id}` | Reject payment |
| GET | `/admin/deactivate/{id}` | Deactivate business |

## Design Decisions

- **No third-party automation**: Custom scheduler (APScheduler) replaces N8N/Make/Zapier
- **No hosted chatbot builders**: Custom OpenAI integration replaces Botpress/Voiceflow
- **Manual payments**: Wise verification instead of Stripe API (saves $0/month)
- **SQLite first**: Upgradable to PostgreSQL when needed
- **No auth for MVP**: Add basic auth or OAuth when deploying publicly

## License

MIT
