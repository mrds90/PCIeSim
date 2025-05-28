from typing import Optional, Tuple, Dict
from .pcie_device import PCIEDevice
from PcieLib.TLP import TLP, ConfigType0Read, ConfigType0Write, MemoryTLPRead, MemoryTLPWrite, Completion, CompletionWithData

class Endpoint(PCIEDevice):
    def __init__(self, *args, memory_size=1024, **kwargs):
        super().__init__(*args, **kwargs)
        self._memory: Dict[int, int] = {i: 0 for i in range(memory_size)}  # memoria simulada
        self._config_space = {14:1}  # espacio de configuración Todo: hexa?

    def set_id(self, id:int):
        self._config_space = {0:id}
    
    def receive(self, tlp: TLP, source: PCIEDevice):
        if isinstance(tlp, ConfigType0Read):
            return self._handle_config_read(tlp, source)
        elif isinstance(tlp, ConfigType0Write):
            return self._handle_config_write(tlp)
        elif isinstance(tlp, MemoryTLPRead):
            return self._handle_mem_read(tlp)
        elif isinstance(tlp, MemoryTLPWrite):
            return self._handle_mem_write(tlp)
        else:
            print(f"{self._name} recibió un TLP no soportado: {tlp}")

    # ------------------- Handlers internos -------------------

    def _handle_config_read(self, tlp: ConfigType0Read, source: PCIEDevice):
        offset = tlp.address & 0xFFF
        data = self._config_space.get(offset, 0)
        completion = CompletionWithData(
            format="CplD",
            type="completion",
            requester_id=tlp.requester_id,
            tag=tlp.tag,
            traffic_class=tlp.traffic_class,
            attributes=tlp.attributes,
            length=1,
            tlp_id=tlp.tlp_id,
            completer_id=(self._bus_number, self._device_number, self._function_number),
            byte_count=4,
            data=data
        )
        self.send(completion, source)

    def _handle_config_write(self, tlp: ConfigType0Write):
        offset = tlp.address
        self._config_space[offset] = tlp.data[0]  # simplificado, se asume 1 dword
        completion = Completion(
            format="Cpl",
            type="completion",
            requester_id=tlp.requester_id,
            tag=tlp.tag,
            traffic_class=tlp.traffic_class,
            attributes=tlp.attributes,
            length=0,
            tlp_id=tlp.tlp_id,
            completer_id=(self._bus_number, self._device_number, self._function_number),
            byte_count=0
        )
        self.send(completion)

    def _handle_mem_read(self, tlp: MemoryTLPRead):
        data = self._memory.get(tlp.address, 0)
        completion = CompletionWithData(
            format="CplD",
            type="completion",
            requester_id=tlp.requester_id,
            tag=tlp.tag,
            traffic_class=tlp.traffic_class,
            attributes=tlp.attributes,
            length=1,
            tlp_id=tlp.tlp_id,
            completer_id=(self._bus_number, self._device_number, self._function_number),
            byte_count=4,
            data=data
        )
        self.send(completion)

    def _handle_mem_write(self, tlp: MemoryTLPWrite):
        self._memory[tlp.address] = tlp.data
        if not tlp.attributes.get("posted", False):
            completion = Completion(
                format="Cpl",
                type="completion",
                requester_id=tlp.requester_id,
                tag=tlp.tag,
                traffic_class=tlp.traffic_class,
                attributes=tlp.attributes,
                length=0,
                tlp_id=tlp.tlp_id,
                completer_id=(self._bus_number, self._device_number, self._function_number),
                byte_count=0
            )
            self.send(completion)
