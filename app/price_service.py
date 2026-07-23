"""Fetching current prices and computing which skins have recently pumped."""

import asyncio
import time
from datetime import datetime, timedelta
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app import models

STEAM_APP_ID = 730  # CS2 / CS:GO
STEAM_PRICE_URL = "https://steamcommunity.com/market/priceoverview/"

# % change thresholds that count as a "pump"
PUMP_THRESHOLD_24H = 15.0
PUMP_THRESHOLD_7D = 30.0

# Steam rate-limits this endpoint hard if you hit it back-to-back. Rather than
# retrying a rate-limited item repeatedly within one sweep (which is what
# made refreshes take 20+ minutes when Steam was throttling hard), we:
#  - back off the delay for *all subsequent* requests this sweep when we hit one 429
#  - give up on an item after one failed attempt and let the next sweep retry it
#  - abort the whole sweep early if we hit too many 429s in a row, since
#    Steam clearly isn't going to let us through right now
REQUEST_DELAY_SECONDS = 2.0
MAX_DELAY_SECONDS = 12.0
MAX_CONSECUTIVE_RATE_LIMITS = 5
MAX_SWEEP_SECONDS = 5 * 60  # hard ceiling regardless of watchlist size


def _parse_price(price_str: str | None) -> float | None:
    """Steam returns prices like '$12.34' or '12,34€' depending on currency/locale."""
    if not price_str:
        return None
    cleaned = price_str.replace(",", ".")
    cleaned = "".join(c for c in cleaned if c.isdigit() or c == ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


async def fetch_current_price(
    market_hash_name: str, currency: int = 1
) -> dict | str | None:
    """Hits Steam's public (unauthenticated, rate-limited) priceoverview endpoint.

    Single attempt - no internal retry loop. Returns:
      - a price dict on success
      - the string "rate_limited" if Steam responded 429 (so the caller can
        back off the pacing for the rest of the sweep)
      - None if the item wasn't found or the response was otherwise unusable
    """
    params = {
        "appid": STEAM_APP_ID,
        "currency": currency,
        "market_hash_name": market_hash_name,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(STEAM_PRICE_URL, params=params)
        except httpx.RequestError:
            return None

        if resp.status_code == 429:
            return "rate_limited"

        if resp.status_code != 200:
            return None

        data = resp.json()
        if not data.get("success"):
            return None

        price = _parse_price(data.get("lowest_price")) or _parse_price(
            data.get("median_price")
        )
        if price is None:
            return None

        volume = None
        if data.get("volume"):
            try:
                volume = int(data["volume"].replace(",", ""))
            except ValueError:
                pass

        return {"price": price, "volume": volume}


refresh_state = {
    "in_progress": False,
    "progress_done": 0,
    "progress_total": 0,
    "last_result": None,  # dict from refresh_all_prices, once it finishes
    "last_started": None,  # datetime
    "last_finished": None,  # datetime
}


async def refresh_all_prices(db: Session) -> dict:
    """Fetches current price for every watched skin and stores a snapshot.

    Requests are paced, and the delay grows if Steam starts rate-limiting us
    (429s). If we hit MAX_CONSECUTIVE_RATE_LIMITS 429s in a row, or the sweep
    runs past MAX_SWEEP_SECONDS, it stops early rather than grinding on -
    whatever's left just gets picked up by the next sweep (hourly job or the
    next manual refresh). Each snapshot commits immediately so the write
    transaction never sits open for the whole refresh.

    This can still take a while for a big watchlist - call it via
    run_refresh_in_background() from a route handler rather than awaiting it
    directly, so the page doesn't sit there waiting on it.
    """
    skins = db.query(models.Skin).filter(models.Skin.watched.is_(True)).all()
    updated, failed = 0, 0
    refresh_state["progress_total"] = len(skins)
    refresh_state["progress_done"] = 0

    delay = REQUEST_DELAY_SECONDS
    consecutive_rate_limits = 0
    stopped_early = False
    started_at = time.monotonic()

    for i, skin in enumerate(skins):
        if time.monotonic() - started_at > MAX_SWEEP_SECONDS:
            stopped_early = True
            break

        result = await fetch_current_price(skin.market_hash_name)

        if result == "rate_limited":
            failed += 1
            consecutive_rate_limits += 1
            delay = min(delay * 1.5, MAX_DELAY_SECONDS)
            if consecutive_rate_limits >= MAX_CONSECUTIVE_RATE_LIMITS:
                refresh_state["progress_done"] = i + 1
                stopped_early = True
                break
        elif result is None:
            failed += 1
            consecutive_rate_limits = 0
        else:
            snapshot = models.PriceSnapshot(
                skin_id=skin.id,
                price=result["price"],
                volume=result["volume"],
            )
            db.add(snapshot)
            db.commit()
            updated += 1
            consecutive_rate_limits = 0

        refresh_state["progress_done"] = i + 1

        if i < len(skins) - 1:
            await asyncio.sleep(delay)

    return {
        "updated": updated,
        "failed": failed,
        "total": len(skins),
        "stopped_early": stopped_early,
    }


# --- Background refresh tracking -------------------------------------------
# The refresh loop above can take a while, so route handlers kick it off as a
# background task instead of awaiting it - the button click returns instantly
# and the page just polls for new data as it trickles in. This state lets
# templates show "refreshing..." and stops two refreshes from overlapping and
# double-hammering Steam.


async def run_refresh_in_background(session_factory) -> None:
    """Runs refresh_all_prices with its own DB session, tracking progress.

    session_factory is typically app.database.SessionLocal - a callable that
    returns a fresh Session, since the request's session may already be
    closed by the time this runs as a background task.
    """
    if refresh_state["in_progress"]:
        return  # a refresh is already running - don't start a second one

    refresh_state["in_progress"] = True
    refresh_state["last_started"] = datetime.utcnow()
    db = session_factory()
    try:
        result = await refresh_all_prices(db)
        refresh_state["last_result"] = result
    finally:
        db.close()
        refresh_state["in_progress"] = False
        refresh_state["last_finished"] = datetime.utcnow()


@dataclass
class PumpResult:
    skin: models.Skin
    current_price: float
    price_24h_ago: float | None
    price_7d_ago: float | None
    change_24h_pct: float | None
    change_7d_ago_pct: float | None
    is_pumped: bool


def _latest_before(db: Session, skin_id: int, cutoff: datetime) -> float | None:
    snap = (
        db.query(models.PriceSnapshot)
        .filter(models.PriceSnapshot.skin_id == skin_id)
        .filter(models.PriceSnapshot.timestamp <= cutoff)
        .order_by(models.PriceSnapshot.timestamp.desc())
        .first()
    )
    return snap.price if snap else None


def get_pumped_skins(db: Session) -> list[PumpResult]:
    """Compares each skin's latest price to its price ~24h and ~7d ago."""
    now = datetime.utcnow()
    results: list[PumpResult] = []

    skins = db.query(models.Skin).all()
    for skin in skins:
        latest = (
            db.query(models.PriceSnapshot)
            .filter(models.PriceSnapshot.skin_id == skin.id)
            .order_by(models.PriceSnapshot.timestamp.desc())
            .first()
        )
        if not latest:
            continue

        price_24h = _latest_before(db, skin.id, now - timedelta(hours=24))
        price_7d = _latest_before(db, skin.id, now - timedelta(days=7))

        change_24h = (
            ((latest.price - price_24h) / price_24h * 100) if price_24h else None
        )
        change_7d = ((latest.price - price_7d) / price_7d * 100) if price_7d else None

        is_pumped = (change_24h is not None and change_24h >= PUMP_THRESHOLD_24H) or (
            change_7d is not None and change_7d >= PUMP_THRESHOLD_7D
        )

        results.append(
            PumpResult(
                skin=skin,
                current_price=latest.price,
                price_24h_ago=price_24h,
                price_7d_ago=price_7d,
                change_24h_pct=change_24h,
                change_7d_ago_pct=change_7d,
                is_pumped=is_pumped,
            )
        )

    # Show the most inflated first
    results.sort(
        key=lambda r: (r.change_24h_pct or r.change_7d_ago_pct or 0), reverse=True
    )
    return [r for r in results if r.is_pumped]