from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, price_service
from app.templates_config import templates

router = APIRouter()


def _get_or_create_skin(db: Session, market_hash_name: str) -> models.Skin:
    skin = (
        db.query(models.Skin)
        .filter(models.Skin.market_hash_name == market_hash_name)
        .first()
    )
    if skin:
        return skin
    skin = models.Skin(
        market_hash_name=market_hash_name,
        display_name=market_hash_name,
        watched=True,
    )
    db.add(skin)
    db.commit()
    db.refresh(skin)
    return skin


def _build_row(db: Session, item: models.InventoryItem) -> dict:
    latest = (
        db.query(models.PriceSnapshot)
        .filter(models.PriceSnapshot.skin_id == item.skin_id)
        .order_by(models.PriceSnapshot.timestamp.desc())
        .first()
    )
    current_price = latest.price if latest else None
    cost = item.buy_price * item.quantity
    value = (current_price * item.quantity) if current_price is not None else None
    profit = (value - cost) if value is not None else None
    profit_pct = (profit / cost * 100) if profit is not None and cost else None

    return {
        "item": item,
        "current_price": current_price,
        "cost": cost,
        "value": value,
        "profit": profit,
        "profit_pct": profit_pct,
    }


def _build_inventory_rows(db: Session):
    items = db.query(models.InventoryItem).all()
    rows = [_build_row(db, item) for item in items]
    total_cost = sum(r["cost"] for r in rows)
    total_value = sum(r["value"] for r in rows if r["value"] is not None)
    return rows, total_cost, total_value


def _render_inventory_table(request: Request, db: Session):
    rows, total_cost, total_value = _build_inventory_rows(db)
    return templates.TemplateResponse(
        "partials/inventory_table.html",
        {
            "request": request,
            "rows": rows,
            "total_cost": total_cost,
            "total_value": total_value,
            "total_profit": total_value - total_cost,
        },
    )


@router.get("/inventory", response_class=HTMLResponse)
def inventory_page(request: Request, db: Session = Depends(get_db)):
    rows, total_cost, total_value = _build_inventory_rows(db)
    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            "rows": rows,
            "total_cost": total_cost,
            "total_value": total_value,
            "total_profit": total_value - total_cost,
            "active": "inventory",
        },
    )


@router.get("/inventory/table", response_class=HTMLResponse)
def inventory_table(request: Request, db: Session = Depends(get_db)):
    return _render_inventory_table(request, db)


@router.post("/inventory/refresh", response_class=HTMLResponse)
async def refresh_inventory_prices(request: Request, db: Session = Depends(get_db)):
    """Manually trigger a Steam price sweep, then return the updated inventory table."""
    await price_service.refresh_all_prices(db)
    return _render_inventory_table(request, db)


@router.post("/inventory/add", response_class=HTMLResponse)
def add_inventory_item(
    request: Request,
    db: Session = Depends(get_db),
    weapon_name: str = Form(...),
    condition: str = Form(""),
    quantity: int = Form(1),
    buy_price: float = Form(...),
    notes: str = Form(""),
):
    base_name = weapon_name.strip()
    market_hash_name = f"{base_name} ({condition})" if condition else base_name

    skin = _get_or_create_skin(db, market_hash_name)
    item = models.InventoryItem(
        skin_id=skin.id,
        quantity=quantity,
        buy_price=buy_price,
        notes=notes or None,
    )
    db.add(item)
    db.commit()

    return _render_inventory_table(request, db)


@router.post("/inventory/{item_id}/delete", response_class=HTMLResponse)
def delete_inventory_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.query(models.InventoryItem).filter(models.InventoryItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()

    return _render_inventory_table(request, db)


@router.get("/inventory/{item_id}/edit", response_class=HTMLResponse)
def edit_inventory_item_form(item_id: int, request: Request, db: Session = Depends(get_db)):
    """Swaps a single row into an inline edit form for its buy price."""
    item = db.query(models.InventoryItem).filter(models.InventoryItem.id == item_id).first()
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    row = _build_row(db, item)
    return templates.TemplateResponse(
        "partials/inventory_row_edit.html", {"request": request, "row": row}
    )


@router.post("/inventory/{item_id}/update", response_class=HTMLResponse)
def update_inventory_item(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    buy_price: float = Form(...),
):
    item = db.query(models.InventoryItem).filter(models.InventoryItem.id == item_id).first()
    if item:
        item.buy_price = buy_price
        db.commit()

    return _render_inventory_table(request, db)
