from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List

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

@dataclass
class TLPWithData(TLP):
    data: List[int] = field(default_factory=list)

    def bytes_to_dwords(self):
            """Convierte una lista de bytes en una lista de DWORDs (little endian)."""
            dwords = []
            for i in range(0, len(self.data), 4):
                dword = (
                    self.data[i]
                    | (self.data[i+1] << 8)
                    | (self.data[i+2] << 16)
                    | (self.data[i+3] << 24)
                )
                dwords.append(dword)
            return dwords
    