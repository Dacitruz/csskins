from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.templates_config import templates

router = APIRouter()


@router.get("/skins", response_class=HTMLResponse)
def skins_page(request: Request, db: Session = Depends(get_db)):
    skins = db.query(models.Skin).order_by(models.Skin.display_name).all()

    rows = []
    for skin in skins:
        latest = (
            db.query(models.PriceSnapshot)
            .filter(models.PriceSnapshot.skin_id == skin.id)
            .order_by(models.PriceSnapshot.timestamp.desc())
            .first()
        )
        snapshot_count = (
            db.query(models.PriceSnapshot)
            .filter(models.PriceSnapshot.skin_id == skin.id)
            .count()
        )
        rows.append(
            {
                "skin": skin,
                "latest_price": latest.price if latest else None,
                "snapshot_count": snapshot_count,
            }
        )

    return templates.TemplateResponse(
        "skins.html", {"request": request, "rows": rows}
    )


@router.get("/skins/{skin_id}", response_class=HTMLResponse)
def skin_detail(skin_id: int, request: Request, db: Session = Depends(get_db)):
    skin = db.query(models.Skin).filter(models.Skin.id == skin_id).first()
    if not skin:
        return HTMLResponse("Skin not found", status_code=404)

    snapshot_count = (
        db.query(models.PriceSnapshot)
        .filter(models.PriceSnapshot.skin_id == skin.id)
        .count()
    )

    return templates.TemplateResponse(
        "skin_detail.html",
        {"request": request, "skin": skin, "snapshot_count": snapshot_count},
    )


@router.get("/skins/{skin_id}/history.json")
def skin_history_json(skin_id: int, db: Session = Depends(get_db)):
    """Raw snapshot series for Chart.js: [{t: ISO timestamp, p: price}, ...]"""
    snapshots = (
        db.query(models.PriceSnapshot)
        .filter(models.PriceSnapshot.skin_id == skin_id)
        .order_by(models.PriceSnapshot.timestamp.asc())
        .all()
    )
    return JSONResponse(
        [{"t": s.timestamp.isoformat(), "p": s.price} for s in snapshots]
    )


@router.get("/skins/{skin_id}/history/daily.json")
def skin_history_daily_json(skin_id: int, db: Session = Depends(get_db)):
    """One point per day (last snapshot of each day) - cleaner for longer ranges."""
    snapshots = (
        db.query(models.PriceSnapshot)
        .filter(models.PriceSnapshot.skin_id == skin_id)
        .order_by(models.PriceSnapshot.timestamp.asc())
        .all()
    )

    by_day = {}
    for s in snapshots:
        day_key = s.timestamp.date().isoformat()
        by_day[day_key] = s.price  # last one wins since we're iterating ascending

    series = [{"t": day, "p": price} for day, price in sorted(by_day.items())]
    return JSONResponse(series)
