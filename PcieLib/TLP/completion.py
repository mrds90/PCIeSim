from dataclasses import dataclass, field
from typing import Optional, Tuple, List
from PcieLib.TLP.tlp import TLP, TLPWithData

@dataclass
class Completion(TLP):
    completer_id: Optional[Tuple[int, int, int]] = None
    completer_status: int = 0
    byte_count: int = 0

@dataclass
class CompletionWithData(Completion, TLPWithData):
    data: List[int] = field(default_factory=list)
    # Podrías agregar atributos o métodos específicos si los hubiera
    pass

@dataclass
class CompletionWithoutData(Completion):
    # Aquí data puede quedarse vacía o no usarse
    pass

@dataclass
class CompletionError(Completion):
    # Podrías agregar campos adicionales relacionados a error
    error_code: Optional[int] = None
