import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from config import DATA_DIR

ROOMS_DIR = DATA_DIR / "rooms"


@dataclass
class Room:
    id: str
    name: str
    product_info: str
    created_at: str
    base_prompt: str = ""
    original_prompt: str = ""
    baseline_session_id: str = ""
    locked_prompt_description: str = ""
    use_global_locked_prompt: bool = True
    tag: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def dir(self) -> Path:
        return ROOMS_DIR / self.id

    def sessions_dir(self) -> Path:
        return self.dir() / "sessions"

    def ratchet_state_path(self) -> Path:
        return self.dir() / "ratchet_state.json"

    def audit_path(self) -> Path:
        return self.dir() / "audit.tsv"

    def save(self):
        d = self.dir()
        d.mkdir(parents=True, exist_ok=True)
        self.sessions_dir().mkdir(exist_ok=True)
        self.candidates_dir().mkdir(exist_ok=True)
        (d / "room.json").write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def candidates_dir(self) -> Path:
        return self.dir() / "candidates"


def create_room(name: str, product_info: str) -> Room:
    room = Room(
        id=uuid.uuid4().hex[:8],
        name=name,
        product_info=product_info,
        created_at=datetime.now().isoformat(),
    )
    room.save()
    return room


def list_rooms() -> list[Room]:
    rooms = []
    if not ROOMS_DIR.exists():
        return rooms
    for d in sorted(ROOMS_DIR.iterdir()):
        meta = d / "room.json"
        if meta.exists():
            rooms.append(Room.from_dict(json.loads(meta.read_text(encoding="utf-8"))))
    return rooms


def load_room(room_id: str) -> Room:
    meta = ROOMS_DIR / room_id / "room.json"
    return Room.from_dict(json.loads(meta.read_text(encoding="utf-8")))


def save_candidate(room: Room, candidate) -> None:
    d = room.candidates_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{candidate.id}.json"
    path.write_text(json.dumps(candidate.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def list_candidates(room: Room) -> list:
    from models import Candidate
    d = room.candidates_dir()
    candidates = []
    if d.exists():
        for f in sorted(d.glob("*.json")):
            candidates.append(Candidate.from_dict(json.loads(f.read_text(encoding="utf-8"))))
    return sorted(candidates, key=lambda c: c.total_score, reverse=True)


def load_candidate(room: Room, candidate_id: str):
    from models import Candidate
    f = room.candidates_dir() / f"{candidate_id}.json"
    if f.exists():
        return Candidate.from_dict(json.loads(f.read_text(encoding="utf-8")))
    return None


# --- Tag management ---
DEFAULT_TAGS = ["大客户", "捡钱", "自营"]
_TAGS_FILE = DATA_DIR / "tags.json"


def load_tags() -> list[str]:
    if _TAGS_FILE.exists():
        return json.loads(_TAGS_FILE.read_text(encoding="utf-8"))
    return list(DEFAULT_TAGS)


def save_tags(tags: list[str]):
    _TAGS_FILE.write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding="utf-8")


def add_tag(tag: str):
    tags = load_tags()
    if tag and tag not in tags:
        tags.append(tag)
        save_tags(tags)
    return tags


def set_baseline(room: Room, candidate) -> None:
    room.baseline_session_id = candidate.session_id
    if candidate.mode == "prompt":
        room.base_prompt = candidate.content
    room.save()
    # 清除旧基线标记，设置新基线
    for f in room.candidates_dir().glob("*.json"):
        from models import Candidate
        c = Candidate.from_dict(json.loads(f.read_text(encoding="utf-8")))
        if c.is_baseline and c.id != candidate.id:
            c.is_baseline = False
            f.write_text(json.dumps(c.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    c_path = room.candidates_dir() / f"{candidate.id}.json"
    if c_path.exists():
        candidate.is_baseline = True
        c_path.write_text(json.dumps(candidate.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
