"""Fetching current prices and computing which skins have recently pumped."""

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


async def fetch_current_price(market_hash_name: str, currency: int = 1) -> dict | None:
    """Hits Steam's public (unauthenticated, rate-limited) priceoverview endpoint.

    currency=1 is USD. See Steam's currency codes for others.
    Returns None if the item wasn't found or Steam rate-limited us.
    """
    params = {
        "appid": STEAM_APP_ID,
        "currency": currency,
        "market_hash_name": market_hash_name,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(STEAM_PRICE_URL, params=params)
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


async def refresh_all_prices(db: Session) -> dict:
    """Fetches current price for every watched skin and stores a snapshot.

    Steam's endpoint is rate-limited (roughly 1 request per few seconds per IP),
    so for a lot of skins you'll want to space these out. For personal use with
    a modest watchlist this straightforward loop is fine.
    """
    skins = db.query(models.Skin).filter(models.Skin.watched.is_(True)).all()
    updated, failed = 0, 0

    for skin in skins:
        result = await fetch_current_price(skin.market_hash_name)
        if result is None:
            failed += 1
            continue
        snapshot = models.PriceSnapshot(
            skin_id=skin.id,
            price=result["price"],
            volume=result["volume"],
        )
        db.add(snapshot)
        updated += 1

    db.commit()
    return {"updated": updated, "failed": failed, "total": len(skins)}


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
