from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.gzip import GZipMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import Base, engine, SessionLocal
from app import price_service
from app.routers import pumped, inventory, skins

Base.metadata.create_all(bind=engine)

scheduler = AsyncIOScheduler()


async def scheduled_refresh():
    await price_service.run_refresh_in_background(SessionLocal)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto price-refresh every hour. Steam's endpoint is rate-limited, so don't
    # go much more aggressive than this if you're tracking more than a handful
    # of skins - tune to taste.
    scheduler.add_job(scheduled_refresh, "interval", hours=1, id="price_refresh")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="CS Skins Tracker", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(pumped.router)
app.include_router(inventory.router)
app.include_router(skins.router)


@app.get("/")
def root():
    return RedirectResponse(url="/pumped")