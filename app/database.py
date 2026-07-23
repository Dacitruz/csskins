from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
 
# SQLite for simplicity - swap the URL for Postgres/MySQL later if you outgrow it.
# e.g. "postgresql+psycopg2://user:pass@localhost/csskins"
DATABASE_URL = "sqlite:///./csskins.db"
 
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
 
if DATABASE_URL.startswith("sqlite"):
    # WAL mode lets other requests keep reading the DB while the price-refresh
    # job is writing - without this, a long refresh can make every other page
    # feel stuck waiting on a database lock.
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
 
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
 
Base = declarative_base()
 
 
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()