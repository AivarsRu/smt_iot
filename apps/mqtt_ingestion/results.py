from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IngestionResult:
    success: bool
    duplicate: bool = False
    raw_message: Optional[object] = None
    measurements_created: int = 0
    measurements_updated: int = 0
    events_created: int = 0
    errors: list = field(default_factory=list)
