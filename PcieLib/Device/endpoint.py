from typing import Optional, Tuple, Dict
from .pcie_device import PCIEDevice, BARs
from PcieLib.TLP import TLP, TLPWithData, ConfigType0Read, ConfigType0Write, MemoryTLPRead, MemoryTLPWithData, Completion, CompletionWithData, CompletionWithoutData
import random

from typing import Optional, Dict, Tuple


class Endpoint(PCIEDevice):
    def __init__(self, *args, memory_sizes: Optional[Dict[BARs, int]] = None, **kwargs):
        super().__init__(*args, **kwargs)

        self._config_space[0x0C] = 0x00  # Header type: endpoint

        self._bar_addresses: Dict[BARs, int] = {}
        self._bar_sizes: Dict[BARs, int] = {}
        self._memory: Dict[BARs, Dict[int, int]] = {}

        if memory_sizes is None:
            memory_sizes = {BARs.BAR0: 1024}

        for bar_enum, size in memory_sizes.items():
            self._bar_addresses[bar_enum] = 0  # Will be set by RC
            self._bar_sizes[bar_enum] = size
            self._memory[bar_enum] = {i: 0 for i in range(size)}

            # Initialize BAR register in config space
            for i in range(4):
                self._config_space[bar_enum.value + i] = 0

    def set_id(self, device_id: int, vendor_id: int):
        self._config_space[0x00] = vendor_id & 0xFF
        self._config_space[0x01] = (vendor_id >> 8) & 0xFF
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
            print(f"{self.name} recibió un TLP no soportado: {tlp}")

    def _bar_enum_from_offset(self, offset: int) -> Optional[BARs]:
        try:
            return BARs(offset)
        except ValueError:
            return None

    def _handle_config0_read(self, tlp: ConfigType0Read, source: PCIEDevice):
        offset = tlp.address & 0xFF

        if offset % 4 == 0:
            bar_enum = self._bar_enum_from_offset(offset)
            if bar_enum:
                if bar_enum in self._bar_sizes:
                    if self._read_config_dword(offset) == 0xFFFFFFFF:
                        mask = ~(self._bar_sizes[bar_enum] - 1) & 0xFFFFFFFF
                        val = mask
                        print(f"{bar_enum.name} needs 0x{self._bar_sizes[bar_enum]:X} addresses")
                    else:
                        val = self._bar_addresses[bar_enum]

                    data = [(val >> (8 * i)) & 0xFF for i in range(4)]
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
                    return
                else:
                    print(f"{bar_enum.name} not used")
        super()._handle_config0_read(tlp, source)

    def _handle_config_write(self, tlp: ConfigType0Write, source: PCIEDevice):
        offset = tlp.address
        data = tlp.bytes_to_dwords()[0]
        self._write_config_dword(offset, data)

        if offset % 4 == 0:
            bar_enum = self._bar_enum_from_offset(offset)
            if bar_enum and bar_enum in self._bar_sizes:
                self._bar_addresses[bar_enum] = data & 0xFFFFFFF0
                print(f"{self.name} -  0x{self._bar_addresses[bar_enum]:X} asignado a {bar_enum.name}")

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

    def _get_bar_and_offset(self, addr: int) -> Optional[Tuple[BARs, int]]:
        for bar_enum, base_addr in self._bar_addresses.items():
            size = self._bar_sizes[bar_enum]
            if base_addr <= addr < base_addr + size:
                return bar_enum, addr - base_addr
        return None

    def _handle_mem_read(self, tlp: MemoryTLPRead, source: PCIEDevice):
        result = self._get_bar_and_offset(tlp.address)
        data = 0
        if result:
            bar_enum, offset = result
            data = self._memory[bar_enum].get(offset, 0)

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
        result = self._get_bar_and_offset(tlp.address)
        if result:
            bar_enum, offset = result
            self._memory[bar_enum][offset] = tlp.data

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
    def bar_addresses(self):
        return self._bar_addresses
