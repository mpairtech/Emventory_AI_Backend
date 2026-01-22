from app.db.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    result = db.execute(text("SELECT 1")).fetchone()
    print("DB connection OK:", result)
finally:
    db.close()
