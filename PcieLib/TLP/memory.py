from dataclasses import dataclass, field
from .tlp import TLP
from typing import List

@dataclass
class MemoryTLP(TLP):
    address: int = 0

@dataclass
class MemoryTLPRead(MemoryTLP):
    pass

@dataclass
class MemoryTLPWrite(MemoryTLP):
    data: List[int] = field(default_factory=list)
