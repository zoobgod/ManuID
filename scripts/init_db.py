from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.bootstrap import seed_default_companies, seed_default_product_types
from app.database import SessionLocal, init_db


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        seed_default_product_types(db)
        seed_default_companies(db)
    finally:
        db.close()
    print("Database initialized.")


if __name__ == "__main__":
    main()
