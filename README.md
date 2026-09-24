# PHC Supply Chain Replenishment Engine

Autonomous medicine replenishment & supply chain resilience engine for Primary Health Centres (PHCs) — Chikkaballapur District, Karnataka.

Built for: **Build with AI: Code for Communities** (Google Cloud Hackathon 2026)

---

## Project Structure

```
phc-replenishment-engine/
├── backend/                    ← FastAPI Python backend
│   ├── app/
│   │   ├── core/
│   │   │   ├── database.py     ← SQLAlchemy engine + session
│   │   │   └── demand_engine.py← Reorder logic, Haversine, transfer suggestions
│   │   ├── models/             ← SQLAlchemy ORM models (PHC, Inventory, Vendor, Order)
│   │   ├── routes/             ← FastAPI routers (phcs, inventory, vendors, orders, analytics, ai)
│   │   ├── schemas/            ← Pydantic v2 schemas
│   │   └── main.py             ← App entry point, CORS, static file serving
│   ├── ai_integration/
│   │   ├── gemini_vision_ocr.py       ← Invoice photo → structured data
│   │   ├── gemini_audio_stock_update.py← Voice note → stock movements
│   │   └── gemini_sms_engine.py       ← Multilingual reorder SMS via Twilio
│   ├── api/
│   │   └── index.py            ← Vercel serverless entry point
│   ├── seed.py                 ← Database seeder (9 Chikkaballapur PHCs)
│   ├── requirements.txt
│   └── .env.example            ← Copy to .env and fill in your keys
│
├── frontend/
│   ├── dashboard/
│   │   └── index.html          ← Admin dashboard (served at /)
│   └── worker/
│       └── index.html          ← Field worker app (served at /worker)
│
└── vercel.json                 ← Vercel deployment config
```

---

## API Keys Required

Copy `backend/.env.example` to `backend/.env` and fill in:

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | For production | PostgreSQL URL (Neon/Supabase/Railway). SQLite used locally. |
| `GEMINI_API_KEY` | For AI features | Google AI Studio key — [get it here](https://aistudio.google.com/app/apikey) |
| `TWILIO_ACCOUNT_SID` | Optional | Only needed to actually send SMS |
| `TWILIO_AUTH_TOKEN` | Optional | Only needed to actually send SMS |
| `TWILIO_FROM_NUMBER` | Optional | Only needed to actually send SMS |

**Without `GEMINI_API_KEY`**: The `/api/v1/ai/*` endpoints return errors, but all inventory, orders, analytics, and map features work normally.

**Without Twilio keys**: `/api/v1/ai/reorder-message` works in dry-run mode (returns the composed message, does not send).

---

## Local Development

```bash
# 1. Install dependencies
cd backend
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 3. Seed the database
python seed.py

# 4. Start the server
uvicorn app.main:app --reload --port 8000
```

Open:
- **Admin Dashboard**: http://localhost:8000/
- **Field Worker App**: http://localhost:8000/worker
- **API Docs (Swagger)**: http://localhost:8000/docs

---

## Deploy to Vercel

### Structure Vercel expects

```
/                        ← repo root
├── api/
│   └── index.py         ← Vercel Python function (MUST be here)
├── requirements.txt     ← Vercel installs these (MUST be at root)
├── vercel.json          ← routes /api/* → Python, / and /worker → static HTML
├── frontend/
│   ├── dashboard/index.html
│   └── worker/index.html
└── backend/             ← all Python source code
    └── app/ ...
```

### 1. Push to GitHub

```bash
git add .
git commit -m "Fix Vercel deployment structure"
git push
```

### 2. Import in Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New Project**
2. Import your GitHub repo
3. **Root Directory**: leave as `/` (repo root)
4. **Framework Preset**: Other
5. Click **Deploy** — Vercel auto-detects `vercel.json`

### 3. Add Environment Variables in Vercel

In your Vercel project → **Settings → Environment Variables**, add:

```
DATABASE_URL    = postgresql://...   ← get from Neon/Supabase/Railway (see below)
GEMINI_API_KEY  = your_key_here      ← from aistudio.google.com/app/apikey
```

### 4. Seed the Production Database

After first deploy, run the seeder locally pointing at your production DB:

```bash
cd backend
DATABASE_URL="postgresql://user:pass@host/db" python seed.py
```

### Recommended Free PostgreSQL Providers

- **[Neon](https://neon.tech)** — best Vercel integration, generous free tier
- **[Supabase](https://supabase.com)** — free tier with dashboard
- **[Railway](https://railway.app)** — simplest setup

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/phcs` | List all PHCs |
| GET | `/api/v1/analytics/network-map` | PHC coordinates + stock health (powers the map) |
| GET | `/api/v1/analytics/district-summary` | Per-district stock breakdown |
| GET | `/api/v1/orders` | List all orders |
| GET | `/api/v1/orders/pipeline/summary` | Kanban board counts |
| GET | `/api/v1/vendors` | List all vendors |
| GET | `/api/v1/phcs/{id}/alerts` | Demand scan for a PHC |
| GET | `/api/v1/phcs/{id}/transfers` | Inter-PHC transfer suggestions |
| POST | `/api/v1/ai/invoice` | Extract data from invoice photo (Gemini) |
| POST | `/api/v1/ai/audio` | Transcribe voice stock note (Gemini) |
| POST | `/api/v1/ai/reorder-message` | Compose multilingual reorder SMS (Gemini + Twilio) |

Full interactive docs: `/docs`
