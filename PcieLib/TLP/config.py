from .tlp import TLP
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List

CFG0RD = "Cfg0Rd"
CFG1RD = "Cfg1Rd"
CFG0WR = "Cfg0Wr"
CFG1WR = "Cfg1Wr"

@dataclass
class Config(TLP):
    address: Optional[int] = None
    destination_id: Optional[Tuple[int, int, int]] = None
    byte_enable: Tuple[int, int] = (0xF, 0xF)

    def __str__(self):
        return (
            f"TLP Type : Configuration Read Type 0 ({self.format})\n"
            f"Requester ID : {self.requester_id}\n"
            f"Device      : {self.destination_id}\n"
            f"Address    : {self.address}\n"
        )

@dataclass
class ConfigRead(Config):
    pass

@dataclass
class ConfigWrite(Config):
    data: List[int] = field(default_factory=list)

@dataclass
class ConfigType0Read(ConfigRead):
    format: str = field(init=False, default=CFG0RD)
    pass

@dataclass
class ConfigType1Read(ConfigRead):
    format: str = field(init=False, default=CFG1RD)
    pass

@dataclass
class ConfigType0Write(ConfigWrite):
    format: str = field(init=False, default=CFG0WR)
    pass

@dataclass
class ConfigType1Write(ConfigWrite):
    format: str = field(init=False, default=CFG1WR)
    pass
