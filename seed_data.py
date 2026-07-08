"""Quick script to seed a starter watchlist of popular skins.

Run with: python seed_data.py
Edit the SKINS list below to whatever you want tracked.
"""

from app.database import SessionLocal, Base, engine
from app import models

SKINS = [
    "AK-47 | Redline (Field-Tested)",
    "AWP | Asiimov (Field-Tested)",
    "M4A4 | Howl (Field-Tested)",
    "Karambit | Doppler (Factory New)",
    "Glock-18 | Fade (Factory New)",
]

Base.metadata.create_all(bind=engine)
db = SessionLocal()

for name in SKINS:
    exists = db.query(models.Skin).filter(models.Skin.market_hash_name == name).first()
    if not exists:
        db.add(models.Skin(market_hash_name=name, display_name=name, watched=True))
        print(f"Added: {name}")
    else:
        print(f"Already exists: {name}")

db.commit()
db.close()
print("Done. Now hit 'Refresh Prices' on the /pumped page to fetch current prices.")
