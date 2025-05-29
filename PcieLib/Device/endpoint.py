from typing import Optional, Tuple, Dict
from .pcie_device import PCIEDevice
from PcieLib.TLP import TLP, TLPWithData, ConfigType0Read, ConfigType0Write, MemoryTLPRead, MemoryTLPWithData, Completion, CompletionWithData, CompletionWithoutData
import random

class Endpoint(PCIEDevice):
    def __init__(self, *args, memory_size=1024, **kwargs):
        super().__init__(*args, **kwargs)

        # Header Type 0x00 para endpoint (bit 7 indica si es multi-función, ignoramos por ahora)
        self._config_space[0x0C] = 0x00

        # Inicializo BARs en 0 (serán asignados luego en enumeración)
        for addr in range(0x10, 0x28, 4):
            for i in range(4):
                self._config_space[addr + i] = 0

        self._memory = {i: 0 for i in range(memory_size)}
        self._bar_size = memory_size  # bytes
        self._bar_address = 0  # se completará cuando el RC lo asigne




    def set_id(self, device_id: int, vendor_id: int):
        # Vendor ID en offset 0x00 (2 bytes)
        self._config_space[0x00] = vendor_id & 0xFF
        self._config_space[0x01] = (vendor_id >> 8) & 0xFF

        # Device ID en offset 0x02 (2 bytes)
        self._config_space[0x02] = device_id & 0xFF
        self._config_space[0x03] = (device_id >> 8) & 0xFF

    
    def receive(self, tlp: TLP, source: PCIEDevice):
        if isinstance(tlp, ConfigType0Read):
            return self._handle_config0_read(tlp, source)
        elif isinstance(tlp, ConfigType0Write):
            return self._handle_config_write(tlp, source)
        elif isinstance(tlp, MemoryTLPRead):
            return self._handle_mem_read(tlp, source)
        elif isinstance(tlp, MemoryTLPWithData):
            return self._handle_mem_write(tlp, source)
        else:
            print(f"{self._name} recibió un TLP no soportado: {tlp}")

    # ------------------- Handlers internos -------------------
    def _handle_config0_read(self, tlp: ConfigType0Read, source: PCIEDevice):
        offset = tlp.address & 0xFF

        if 0x10 <= offset <= 0x24 and (offset % 4 == 0):
            bar_value = self._read_config_dword(offset)
            if bar_value == 0xFFFFFFFF:
                mask = ~(self._bar_size - 1) & 0xFFFFFFFF
                data = [
                    mask & 0xFF,
                    (mask >> 8) & 0xFF,
                    (mask >> 16) & 0xFF,
                    (mask >> 24) & 0xFF
                ]
            else:
                if offset == 0x10:
                    val = self._bar_address
                else:
                    val = bar_value
                data = [
                    val & 0xFF,
                    (val >> 8) & 0xFF,
                    (val >> 16) & 0xFF,
                    (val >> 24) & 0xFF
                ]

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
        else:
            super()._handle_config0_read(tlp, source)

    def _handle_config_write(self, tlp: ConfigType0Write, source: PCIEDevice):
        offset = tlp.address
        data = tlp.bytes_to_dwords()[0]  # asumimos 1 dword

        self._write_config_dword(offset, data)

        if 0x10 <= offset <= 0x24 and offset % 4 == 0:
            bar_index = (offset - 0x10) // 4
            if bar_index == 0:
                self._bar_address = data & 0xFFFFFFF0
                print(f"{self._name} - BAR{bar_index} asignado a 0x{self._bar_address:X}")

        completion = CompletionWithoutData(
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
        self.send(completion, source)

    def _handle_mem_read(self, tlp: MemoryTLPRead, source: PCIEDevice):
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
        self.send(completion, source)

    def _handle_mem_write(self, tlp: MemoryTLPWithData, source: PCIEDevice):
        self._memory[tlp.address] = tlp.data
        if not tlp.attributes.get("posted", False):
            completion = CompletionWithoutData(
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
            self.send(completion, source)
    @property
    def bar_address(self):
        return self._bar_address