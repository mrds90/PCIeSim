from typing import Optional, Tuple, Dict, List
from .pcie_device import PCIEDevice, BARs
from .endpoint import Endpoint
from PcieLib.TLP import TLP, Completion, CompletionWithData, ConfigType0Read, ConfigType0Write, ConfigType1Read, ConfigType1Write, MemoryTLPRead, MemoryTLPWithData, CFG0RD, CFG1RD, CFG0WR, CFG1WR
from itertools import count
from enum import Enum

class EnumState(Enum):
    DISCOVERY = "discovery"
    HEADER_TYPE = "header_type"
    BAR_PROBE = "bar_probe"
    BAR_ASSIGN = "bar_assign"
    DONE = "done"
    SEC_BUS = "sec_bus"


class RootComplex(PCIEDevice):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_bus = 0
        self._tlps: Dict[int, TLP] = {}  # mapea TLP IDs a TLPs
        self.enumerated_devices: Dict[Tuple[int, int, int], str] = {}
        self.memory_map: Dict[Tuple[int, int, int], List[Tuple[int, int, int]]] = {}
        self.device_state: Dict[Tuple[int, int, int], str] = {}
        self.next_free_address = 0x80000000  # o desde donde quieras empezar a mapear



    def receive(self, tlp: TLP, source: PCIEDevice):
        if isinstance(tlp, (MemoryTLPRead, MemoryTLPWithData)):
            return self._handle_memory(tlp)
        elif isinstance(tlp, Completion):
            return self._handle_completion(tlp, source)
        else:
            print(f"{self._name} recibió un TLP no soportado: {tlp}")

    def _handle_memory(self, tlp: TLP):
        # Aquí se manejarían las solicitudes de memoria
        pass

    def _handle_completion(self, tlp: Completion, source: PCIEDevice):
    # Verifico si el tlp_id corresponde a una TLP que estamos esperando (request)

        if tlp.tlp_id in self._tlps:
            # Obtengo la TLP original que generó esta respuesta
            tlp_processing = self._tlps.pop(tlp.tlp_id)  # la saco del dict, ya que fue respondida
            state = self.device_state.get(tlp.completer_id, EnumState.DISCOVERY)

            if state == EnumState.DISCOVERY:
                self._fsm_handle_discovery(tlp_processing, tlp, source)
            elif state == EnumState.HEADER_TYPE:
                self._fsm_handle_header_type(tlp_processing, tlp, source)
            elif state == EnumState.BAR_PROBE:
                self._fsm_handle_bar_probe(tlp_processing, tlp, source)
            elif state == EnumState.BAR_ASSIGN:
                self._fsm_handle_bar_assign(tlp_processing, tlp, source)

    def _set_enum_state(self, tlp:Completion, state:EnumState):
        print(f"{self._completion_device_name(tlp)}: Enum state {state.value}")
        self.device_state[tlp.completer_id] = state

    def _fsm_handle_discovery(self, tlp_processing: TLP, tlp_received:CompletionWithData, source:PCIEDevice):
        if tlp_processing.format == CFG0RD:
                offset = tlp_processing.address & 0xFF
                if (offset) == 0:
                    device_name = ''.join(chr(b) for b in tlp_received.data).replace(' ', '')
                    self.enumerated_devices[tlp_received.completer_id] = device_name
                    print(f"{device_name} enumerado: BDF {tlp_received.completer_id}\n")
                    self._set_enum_state(tlp_received, EnumState.HEADER_TYPE)
                    self._send_cfg_read(tlp_received.completer_id, 0x0C, source)
                    return
        self.enumerate()

    def _fsm_handle_header_type(self, tlp_processing: TLP, tlp_received:Completion, source:PCIEDevice):
        if tlp_processing.format == CFG0RD:
            offset = tlp_processing.address & 0xFF
            if (offset) == 0x0C:
                header_type = tlp_received.data[0]  # asumimos que data es una lista de bytes
                bdf = tlp_received.completer_id
                if (header_type & 0x7F) == 0x01:
                    print(f"Dispositivo {self._completion_device_name(tlp_received)}:{bdf} es un Switch (Header Type 0x{header_type:02X}).")
                    self._set_enum_state(tlp_received, EnumState.SEC_BUS)
                    self._current_bus = self._next_available_bus_number()
                    self.enumerate(source)  # 🚀 enumerar el nuevo bus detrás del switch (todo: en realidad tengo que configurar el espacio de memoria del switch con su secondary y subordinate)
                    return
                elif (header_type & 0x7F) == 0x00:
                    print(f"Dispositivo {self._completion_device_name(tlp_received)}:{bdf} es un Endpoint (Header Type 0x{header_type:02X}).")
                    self._set_enum_state(tlp_received, EnumState.BAR_PROBE)
                    self._send_cfg_read(tlp_received.completer_id, BARs.BAR0.value, source)
                    return
                else:
                    print(f"Dispositivo {self._completion_device_name(tlp_received)}:{bdf} tiene un tipo desconocido: 0x{header_type:02X}.\n")
        self.enumerate()

    def _fsm_handle_bar_probe(self, tlp_processing: TLP, tlp_received:Completion, source:PCIEDevice):
        offset = tlp_processing.address & 0xFF
        if tlp_processing.format == CFG0RD:
            if BARs.BAR0.value <= offset <= BARs.BAR5.value and offset % 4 == 0:
                if tlp_received.bytes_to_dwords()[0] == 0:
                    # Trigger de size detection
                    self._send_cfg_write(tlp_received.completer_id, offset, [0xFF]*4, source)
                    return

        elif tlp_processing.format == CFG0WR:
            data = tlp_processing.data
            if BARs.BAR0.value <= offset <= BARs.BAR5.value and data == [0xFF, 0xFF, 0xFF, 0xFF]:
                self._set_enum_state(tlp_received, EnumState.BAR_ASSIGN)
                self._send_cfg_read(tlp_received.completer_id, offset, source)
                return

        if offset < BARs.BAR5.value:
            self._send_cfg_read(tlp_received.completer_id, (offset + 0x4), source)
            return

        self.enumerate()

    def _fsm_handle_bar_assign(self, tlp_processing: TLP, tlp_received:Completion, source:PCIEDevice):
        offset = tlp_processing.address & 0xFF
        if tlp_processing.format == CFG0RD:
            if getattr(source, "bar_addresses", 0)[BARs(offset)] == 0xFFFFFFF0:
                # El dispositivo acaba de responder con la máscara (ej: 0xFFFFFC00)
                mask_bytes = tlp_received.data
                mask_dword = int.from_bytes(mask_bytes, byteorder='little')
                size = ~(mask_dword & 0xFFFFFFF0) + 1  # Solo si es BAR de memoria
                # Asignar dirección alineada
                base_address = (self.next_free_address + size - 1) & ~(size - 1)
                self.next_free_address = base_address + size
                # Guardar en source y memoria del RC
                self.memory_map.setdefault(tlp_received.completer_id, []).append((offset, base_address, size))
                # Escribir la dirección al BAR del dispositivo
                addr_bytes = base_address.to_bytes(4, byteorder='little')
                self._send_cfg_write(tlp_received.completer_id, offset, addr_bytes, source)
                return
        elif tlp_processing.format == CFG0WR:
            if offset < BARs.BAR5.value:
                self._set_enum_state(tlp_received, EnumState.BAR_PROBE)
                self._send_cfg_read(tlp_received.completer_id, (offset + 0x4), source)
                return
            else:
                self._set_enum_state(tlp_received, EnumState.DONE)
        self.enumerate()

    def _next_tlp_id(self) -> int:
        return next(i for i in count() if i not in self._tlps)

    def enumerate(self, source: PCIEDevice | None = None):
        if not self._enabled:
            self.enumerated_devices[(0, 0, 0)] = self.name
            self.set_bdf(0,0,0)
            self._enabled = True
        self._current_bus = self._current_bus - 1 if self._current_bus > 0 else 0
        if self._current_bus > 0 and source == None:
            raise ValueError("Falta especificar el SW que conduce a ese Bus")
        if source == None:
            for device in self._links:
                if not device._enabled: #Todo: si no tienen estados definidos en la FSM de enumeracion
                    source = device
                    break
            else:
                return
        device_number = self._next_free_device_number(self._current_bus)  # siguiente device libre en bus 0
        bfd = (self._current_bus, device_number, 0)
        self.device_state[bfd] = EnumState.DISCOVERY
        self._send_cfg_read(bfd, 0x00, source)

    
    def _send_cfg_read(self, bdf: Tuple[int, int, int], offset, source):
        bus = bdf[0]
        tlp = self._build_config_tlp(
            CFG0RD if bus == 0 else CFG1RD,
            bdf,
            offset
        )
        self.send(tlp, source)

    def _send_cfg_write(self, bdf: Tuple[int, int, int], offset, data, source):
        bus = bdf[0]
        tlp = self._build_config_tlp(
            CFG0WR if bus == 0 else CFG1WR,
            bdf,
            offset,
            data=data
        )
        self.send(tlp, source)

    def send(self, tlp:TLP, dest:PCIEDevice):
        self._tlps[tlp.tlp_id] = tlp
        super().send(tlp,dest)

    def enumerate_secondary_bus(self, device: PCIEDevice):
        # 1. Asignar bus secundario al switch
        secondary_bus = self._next_available_bus_number()
        device.set_secondary_bus_number(secondary_bus)

        print(f"{device.name} asignado Secondary Bus = {secondary_bus}")

        # 2. Enumerar todos los dispositivos conectados a ese bus
        for dev in device.get_downstream_devices():
            if not dev._enabled:
                tlp_id = self._next_tlp_id()
                cfg0rd = ConfigType0Read(
                    requester_id=(self._bus_number, self._device_number, self._function_number),
                    destination_id=(secondary_bus, 0, 0),  # empezamos con Dev 0, Func 0
                    tag=0,
                    traffic_class=0,
                    attributes=0,
                    length=1,
                    tlp_id=tlp_id,
                    address=0x00
                )
                self.send(cfg0rd, dev)
                break  # enumeramos de a uno como en el bus 0

    def _next_available_bus_number(self) -> int:
        used_buses = {bus for (bus, _, _) in self.enumerated_devices}
        for bus_num in range(256):
            if bus_num not in used_buses:
                return bus_num
        raise RuntimeError("No hay buses disponibles")

    def _completion_device_name(self, tlp_completion:Completion):
        return self.enumerated_devices[tlp_completion.completer_id]

    def _next_free_device_number(self, bus_number: int) -> int:
        used_device_numbers = {dev for (bus, dev, _) in self.enumerated_devices if bus == bus_number}
        for num in range(32):  # PCIe permite hasta 32 dispositivos por bus
            if num not in used_device_numbers:
                return num
        raise RuntimeError(f"No hay espacio libre en el bus {bus_number}")

    def _build_config_tlp(self, tlp_type: str, destination_id: Tuple[int, int, int], address: int, data: Optional[List[int]] = None) -> TLP:
        tlp_id = self._next_tlp_id()
        requester_id = (self._bus_number, self._device_number, self._function_number)

        if tlp_type == CFG0RD:
            return ConfigType0Read(
                requester_id=requester_id,
                destination_id=destination_id,
                tag=0,
                traffic_class=0,
                attributes=0,
                length=1,
                tlp_id=tlp_id,
                address=address
            )
        elif tlp_type == CFG1RD:
            return ConfigType1Read(
                requester_id=requester_id,
                destination_id=destination_id,
                tag=0,
                traffic_class=0,
                attributes=0,
                length=1,
                tlp_id=tlp_id,
                address=address
            )
        elif tlp_type == CFG0WR:
            return ConfigType0Write(
                requester_id=requester_id,
                destination_id=destination_id,
                tag=0,
                traffic_class=0,
                attributes=0,
                length=1,
                tlp_id=tlp_id,
                address=address,
                data=data or [0x00]
            )
        elif tlp_type == CFG1WR:
            return ConfigType1Write(
                requester_id=requester_id,
                destination_id=destination_id,
                tag=0,
                traffic_class=0,
                attributes=0,
                length=1,
                tlp_id=tlp_id,
                address=address,
                data=data or [0x00]
            )
        else:
            raise ValueError(f"TLP type '{tlp_type}' no reconocido.")

