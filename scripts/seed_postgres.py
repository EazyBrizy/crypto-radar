import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal  # noqa: E402
from app.services.bootstrap_service import bootstrap_postgres_seed  # noqa: E402


def main() -> None:
    with SessionLocal() as session:
        summary = bootstrap_postgres_seed(session)
        session.commit()
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
