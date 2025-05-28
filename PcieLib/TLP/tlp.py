from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict

@dataclass
class TLP:
    format: str
    type: str
    requester_id: Optional[Tuple[int, int, int]] = None
    tag: int = 0
    traffic_class: int = 0
    attributes: Dict[str, bool] = field(default_factory=dict)
    length: int = 0
    tlp_id: int = 0
