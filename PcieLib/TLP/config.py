from .tlp import TLP, TLPWithData
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict

CFG0RD = "Cfg0Rd"
CFG1RD = "Cfg1Rd"
CFG0WR = "Cfg0Wr"
CFG1WR = "Cfg1Wr"

@dataclass
class Config(TLP):
    address: Optional[int] = None
    destination_id: Optional[Tuple[int, int, int]] = None
    byte_enable: Tuple[int, int] = (0xF, 0xF)

   

@dataclass
class ConfigRead(Config):
    type: str = field(init=False, default="config_read")
    
    def __str__(self):
        return (
        f"{self.format}: {self.requester_id} -> {self.destination_id} | 0x{self.address:X}"
    )
@dataclass
class ConfigWrite(Config, TLPWithData):
    type: str = field(init=False, default="config_write")
    def __str__(self):
        data_str = " ".join(f"{b:02X}" for b in self.data)
        return (
            f"{self.format}: {self.requester_id} -> {self.destination_id} | "
            f"0x{self.address:X} <= [{data_str}]"
        )

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
