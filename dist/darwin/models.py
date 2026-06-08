from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
from pathlib import Path


@dataclass
class MetricDefinition:
    name: str
    key: str
    direction: str = "higher"
    weight: float = 1.0


@dataclass
class Session:
    id: str
    timestamp: str
    script: str
    metrics: dict[str, float]
    room_id: str = ""
    prompt: str = ""
    notes: str = ""
    llm_analysis: str = ""
    locked_elements: list[str] = field(default_factory=list)
    static_scores: dict[str, int] = field(default_factory=dict)
    static_total: float = 0.0
    effect_scores: dict[str, float] = field(default_factory=dict)
    effect_total: float = 0.0
    total_score: float = 0.0
    rubric_reasoning: dict[str, str] = field(default_factory=dict)
    scorer_model: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RatchetState:
    baselines: dict[str, float] = field(default_factory=dict)
    locked_constraints: list[dict] = field(default_factory=list)
    improvement_targets: list[str] = field(default_factory=list)
    iteration_count: int = 0
    history: list[dict] = field(default_factory=list)
    effect_baselines: dict[str, float] = field(default_factory=dict)
    stagnation_count: int = 0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path):
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path):
        if path.exists():
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        return cls()


@dataclass
class Candidate:
    id: str
    session_id: str
    mode: str
    content: str
    generated_script: str = ""
    total_score: float = 0.0
    static_scores: dict = field(default_factory=dict)
    effect_scores: dict = field(default_factory=dict)
    created_at: str = ""
    rounds: int = 0
    is_baseline: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BackgroundTask:
    id: str
    room_id: str
    op: str
    status: str = "running"
    progress: str = ""
    best_score: float = 0.0
    result: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    pid: int = 0
    stop_requested: bool = False
    created_at: str = ""
    desc: str = ""
    log: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
