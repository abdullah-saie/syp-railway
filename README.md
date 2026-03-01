# SYP Markets — Live Syrian Pound Exchange Rates

Real-time USD/SYP and other currency charts scraped from sp-today.com.

## 🚀 Deploy on Railway (Free, 24/7)

### Step 1 — Upload to GitHub
1. Create a new repo on github.com
2. Upload all files keeping this structure:
```
syp-railway/
├── Dockerfile
├── railway.toml
├── .gitignore
├── backend/
│   ├── api.py
│   ├── scraper.py
│   ├── database.py
│   └── requirements.txt
└── frontend/
    └── index.html
```

### Step 2 — Deploy on Railway
1. Go to **railway.app** and sign up (free)
2. Click **New Project → Deploy from GitHub repo**
3. Select your repo
4. Railway auto-detects the Dockerfile and builds it

### Step 3 — Add a Volume (for database persistence)
1. In your Railway project, click **+ New → Volume**
2. Mount it at `/data`
3. This keeps your data between deploys

### Step 4 — Get your URL
Railway gives you a free URL like:
`https://syp-markets-production.up.railway.app`

That's it! Open the URL in your browser. 🎉

---

## 🖥️ Run Locally

```bash
# Install dependencies
pip install -r backend/requirements.txt

# Run
cd backend
uvicorn api:app --reload --port 8000

# Open browser
open http://localhost:8000
```

---

## 📡 API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Frontend app |
| `GET /api/pairs` | All tracked pairs with latest prices |
| `GET /api/history?currency=USD&tf=1H` | OHLC candles |
| `GET /api/latest?currency=USD` | Latest tick |
| `POST /api/scrape` | Trigger manual scrape |
| `GET /health` | Health check |

**Timeframes:** `1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W, 1M`

---

## 📊 Data Sources
- **FX rates** — sp-today.com (scraped every 5 min)
- **Crypto** — CoinGecko free API
- **Gold** — sp-today.com
- **Fuel** — sp-today.com
