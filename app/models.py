from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Boolean,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Skin(Base):
    """A distinct tradeable skin, identified by its Steam market_hash_name.

    e.g. "AK-47 | Redline (Field-Tested)"
    """

    __tablename__ = "skins"

    id = Column(Integer, primary_key=True, index=True)
    market_hash_name = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=False)
    icon_url = Column(String, nullable=True)
    watched = Column(Boolean, default=True)  # included in price-refresh sweeps
    created_at = Column(DateTime, default=datetime.utcnow)

    price_snapshots = relationship(
        "PriceSnapshot", back_populates="skin", cascade="all, delete-orphan"
    )
    inventory_items = relationship(
        "InventoryItem", back_populates="skin", cascade="all, delete-orphan"
    )


class PriceSnapshot(Base):
    """A single price observation for a skin at a point in time.

    We build our own price history by recording one of these every time
    we refresh prices (manually or on a schedule), since Steam's public
    endpoint only exposes the *current* price, not history.
    """

    __tablename__ = "price_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    skin_id = Column(Integer, ForeignKey("skins.id"), nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    volume = Column(Integer, nullable=True)  # units sold in last 24h, if available
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    skin = relationship("Skin", back_populates="price_snapshots")


class InventoryItem(Base):
    """A skin you own, with what you paid for it."""

    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    skin_id = Column(Integer, ForeignKey("skins.id"), nullable=False)
    quantity = Column(Integer, default=1)
    buy_price = Column(Float, nullable=False)  # price paid per unit
    buy_date = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    skin = relationship("Skin", back_populates="inventory_items")
