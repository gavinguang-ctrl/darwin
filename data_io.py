import json
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import DATA_DIR
from models import Session


def new_session_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


def _session_dir(session: Session) -> Path:
    from room import ROOMS_DIR
    d = ROOMS_DIR / session.room_id / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_session(session: Session):
    path = _session_dir(session) / f"{session.id}.json"
    path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_session(session_id: str, room_id: str = "") -> Session:
    from room import ROOMS_DIR
    path = ROOMS_DIR / room_id / "sessions" / f"{session_id}.json"
    return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_sessions(room_id: str = "") -> list[Session]:
    from room import ROOMS_DIR
    sessions_dir = ROOMS_DIR / room_id / "sessions"
    sessions = []
    if sessions_dir.exists():
        for f in sorted(sessions_dir.glob("*.json")):
            sessions.append(Session.from_dict(json.loads(f.read_text(encoding="utf-8"))))
    return sessions


def parse_metrics_from_excel(file) -> dict[str, float]:
    df = pd.read_excel(file)
    if df.shape[1] >= 2:
        return {str(row.iloc[0]).strip(): float(row.iloc[1]) for _, row in df.iterrows() if pd.notna(row.iloc[1])}
    return {}


def parse_metrics_from_json(file) -> dict[str, float]:
    data = json.loads(file.read())
    if isinstance(data, dict):
        return {k: float(v) for k, v in data.items() if v is not None}
    return {}


def parse_metrics_from_csv(file) -> dict[str, float]:
    df = pd.read_csv(file)
    if df.shape[1] >= 2:
        return {str(row.iloc[0]).strip(): float(row.iloc[1]) for _, row in df.iterrows() if pd.notna(row.iloc[1])}
    return {}
