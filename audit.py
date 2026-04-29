import csv
from datetime import datetime
from pathlib import Path

AUDIT_HEADERS = ["timestamp", "session_id", "old_score", "new_score", "status", "dimension", "priority", "scorer_model", "note"]


def _get_path(room_id: str) -> Path:
    from room import ROOMS_DIR
    return ROOMS_DIR / room_id / "audit.tsv"


def _ensure_file(path: Path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\t".join(AUDIT_HEADERS) + "\n", encoding="utf-8")


def append_entry(session_id: str, old_score: float, new_score: float, status: str,
                 dimension: str = "-", priority: str = "-", scorer_model: str = "-",
                 note: str = "", room_id: str = ""):
    path = _get_path(room_id)
    _ensure_file(path)
    row = [datetime.now().isoformat(timespec="seconds"), session_id,
           str(old_score), str(new_score), status, dimension, priority, scorer_model, note]
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(row)


def load_log(room_id: str = "") -> list[dict]:
    path = _get_path(room_id)
    _ensure_file(path)
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(dict(row))
    return rows
