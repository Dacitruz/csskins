from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app import price_service
from app.templates_config import templates

router = APIRouter()


@router.get("/pumped", response_class=HTMLResponse)
def pumped_page(request: Request, db: Session = Depends(get_db)):
    pumped = price_service.get_pumped_skins(db)
    return templates.TemplateResponse(
        "pumped.html", {"request": request, "pumped": pumped, "active": "pumped"}
    )


@router.get("/pumped/table", response_class=HTMLResponse)
def pumped_table(request: Request, db: Session = Depends(get_db)):
    """HTMX partial - just the table body, for polling/refresh without a full reload."""
    pumped = price_service.get_pumped_skins(db)
    return templates.TemplateResponse(
        "partials/pumped_table.html", {"request": request, "pumped": pumped}
    )


@router.post("/pumped/refresh", response_class=HTMLResponse)
async def refresh_prices(request: Request, db: Session = Depends(get_db)):
    """Manually trigger a Steam price sweep, then return the updated table."""
    await price_service.refresh_all_prices(db)
    pumped = price_service.get_pumped_skins(db)
    return templates.TemplateResponse(
        "partials/pumped_table.html", {"request": request, "pumped": pumped}
    )
