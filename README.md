# CS Skins Tracker

A small FastAPI + SQLAlchemy + Jinja2 + HTMX app for tracking CS2 skin prices:

- **`/pumped`** — skins with a 24h price change ≥ 15% or a 7d change ≥ 30%.
- **`/inventory`** — your holdings, with cost basis, current value, and profit/loss.
- **`/skins`** — every tracked skin, click one to see its full price history as a chart (raw snapshots or daily-aggregated view).

## How prices work

Steam's public market API (`priceoverview`) only returns the *current* price — it
has no history endpoint. So this app builds its own price history: every time you
hit "Refresh Prices" (or the hourly background job runs), it fetches the current
price for each watched skin and stores a timestamped snapshot. The "pumped" page
compares the latest snapshot to whatever snapshot is closest to 24h/7d ago.

**This means the pumped page needs a few refreshes over time before it becomes
useful** — with only one data point there's nothing to compare against. Run the
refresh a few times over the first day or two (or leave the app running so the
hourly job does it for you) to build up history.

## Setup

```bash
pip install -r requirements.txt
python seed_data.py       # optional: adds a few starter skins to the watchlist
uvicorn app.main:app --reload
```

Visit `http://localhost:8000`.

## Adding skins

- **Inventory page**: adding an item there also adds the skin to the watchlist automatically.
- **Watchlist only** (skin you don't own but want to monitor for pumps): use
  `seed_data.py`, or add a row directly via the `Skin` model / a quick script.

The `market_hash_name` must match Steam's exact format, e.g.:
`AK-47 | Redline (Field-Tested)`, `Karambit | Doppler (Factory New)`.
You can copy this exactly from a Steam Community Market URL or listing page.

## Notes & next steps

- Steam's price endpoint is rate-limited (roughly one request per few seconds per
  IP) — if you watch a lot of skins, the refresh loop in `price_service.py` may
  need throttling/backoff added.
- Currently uses SQLite (`csskins.db`, created automatically). Swap the
  `DATABASE_URL` in `app/database.py` for Postgres/MySQL if you need
  multi-user or heavier concurrent access.
- Pump thresholds (`PUMP_THRESHOLD_24H`, `PUMP_THRESHOLD_7D`) live at the top
  of `app/price_service.py` — tune to taste.
- No auth/multi-user support yet — this is built for single-user personal use.
- If you'd rather use a third-party pricing API (CSFloat, SkinPort, Buff163,
  etc.) instead of/alongside Steam, swap out `fetch_current_price()` in
  `price_service.py` — everything downstream (snapshots, pump detection,
  inventory valuation) stays the same.
