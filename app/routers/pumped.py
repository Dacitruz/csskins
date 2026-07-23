from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app import price_service
from app.templates_config import templates

router = APIRouter()


@router.get("/pumped", response_class=HTMLResponse)
def pumped_page(request: Request, db: Session = Depends(get_db)):
    pumped = price_service.get_pumped_skins(db)
    return templates.TemplateResponse(
        "pumped.html",
        {
            "request": request,
            "pumped": pumped,
            "active": "pumped",
            "refresh_state": price_service.refresh_state,
        },
    )


@router.get("/pumped/table", response_class=HTMLResponse)
def pumped_table(request: Request, db: Session = Depends(get_db)):
    """HTMX partial - just the table body, for polling/refresh without a full reload."""
    pumped = price_service.get_pumped_skins(db)
    return templates.TemplateResponse(
        "partials/pumped_table.html",
        {"request": request, "pumped": pumped, "refresh_state": price_service.refresh_state},
    )


@router.post("/pumped/refresh", response_class=HTMLResponse)
def refresh_prices(
    request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Kicks off a Steam price sweep in the background and returns immediately -
    the sweep is paced to avoid Steam's rate limit, so it can take a while for
    a big watchlist. The table polls itself for updates as prices come in."""
    background_tasks.add_task(price_service.run_refresh_in_background, SessionLocal)
    pumped = price_service.get_pumped_skins(db)
    return templates.TemplateResponse(
        "partials/pumped_table.html",
        {"request": request, "pumped": pumped, "refresh_state": price_service.refresh_state},
    )