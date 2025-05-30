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
        self._tlps: Dict[int, TLP] = {}  # mapea TLP IDs a TLPs
        self.enumerated_devices: Dict[Tuple[int, int, int], PCIEDevice] = {}
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
            bdf = source.get_bdf()
            state = self.device_state.get(bdf, EnumState.DISCOVERY)

            if state == EnumState.DISCOVERY:
                self._fsm_handle_discovery(tlp_processing, tlp, source)
            elif state == EnumState.HEADER_TYPE:
                self._fsm_handle_header_type(tlp_processing, tlp, source)
            elif state == EnumState.BAR_PROBE:
                self._fsm_handle_bar_probe(tlp_processing, tlp, source)
            elif state == EnumState.BAR_ASSIGN:
                self._fsm_handle_bar_assign(tlp_processing, tlp, source)

    def _fsm_handle_discovery(self, tlp_processing: TLP, tlp_received:TLP, source:PCIEDevice):
        if tlp_processing.format == CFG0RD:
                offset = tlp_processing.address & 0xFF
                if (offset) == 0:
                    self.enumerated_devices[source.get_bdf()] = source
                    print(f"{source.name} enumerado: BDF {source.get_bdf()}\n")
                    cfg_header_type = self._build_config_tlp(CFG0RD,source.get_bdf(), 0x0C)
                    self._set_enum_state(source, EnumState.HEADER_TYPE)
                    self.send(cfg_header_type, source)
                    return
        self.enumerate()

    def _set_enum_state(self, device:PCIEDevice, state:EnumState):
        print(f"{device.name}: Enum state {state.value}")
        self.device_state[device.get_bdf()] = state

    def _fsm_handle_header_type(self, tlp_processing: TLP, tlp_received:TLP, source:PCIEDevice):
        if tlp_processing.format == CFG0RD:
            offset = tlp_processing.address & 0xFF
            if (offset) == 0x0C:
                header_type = tlp_received.data[0]  # asumimos que data es una lista de bytes
                bdf = f"{source.bus_number}.{source.device_number}.{source.function_number}"
                if (header_type & 0x7F) == 0x01:
                    print(f"Dispositivo {source.name}:{bdf} es un Switch (Header Type 0x{header_type:02X}).")
                    self._set_enum_state(source, EnumState.SEC_BUS)
                    self.enumerate_secondary_bus(source)  # 🚀 enumerar el nuevo bus detrás del switch
                    return
                elif (header_type & 0x7F) == 0x00:
                    print(f"Dispositivo {source.name}:{bdf} es un Endpoint (Header Type 0x{header_type:02X}).")
                    bar0_read = self._build_config_tlp(CFG0RD, source.get_bdf(), BARs.BAR0.value)
                    self._set_enum_state(source, EnumState.BAR_PROBE)
                    self.send(bar0_read, source)
                    return
                else:
                    print(f"Dispositivo {source.name}:{bdf} tiene un tipo desconocido: 0x{header_type:02X}.\n")
        self.enumerate()

    def _fsm_handle_bar_probe(self, tlp_processing: TLP, tlp_received:TLP, source:PCIEDevice):
        offset = tlp_processing.address & 0xFF
        if tlp_processing.format == CFG0RD:
            if BARs.BAR0.value <= offset <= BARs.BAR5.value and offset % 4 == 0:
                if tlp_received.bytes_to_dwords()[0] == 0:
                    # Trigger de size detection
                    bar_probe_write = self._build_config_tlp(CFG0WR, source.get_bdf(), offset, data=[0xFF, 0xFF, 0xFF, 0xFF])
                    self.send(bar_probe_write, source)
                    return
                
        elif tlp_processing.format == CFG0WR:
            data = tlp_processing.data
            if BARs.BAR0.value <= offset <= BARs.BAR5.value and data == [0xFF, 0xFF, 0xFF, 0xFF]:
                cfg_read = self._build_config_tlp(CFG0RD,source.get_bdf(), offset)
                self._set_enum_state(source, EnumState.BAR_ASSIGN)
                self.send(cfg_read, source)
                return
        
        if offset < BARs.BAR5.value:
            bar_n_read = self._build_config_tlp(CFG0RD, source.get_bdf(), (offset + 0x4))
            self.send(bar_n_read, source)
            return
        
        self.enumerate()

    def _fsm_handle_bar_assign(self, tlp_processing: TLP, tlp_received:TLP, source:PCIEDevice):
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
                self.memory_map.setdefault(source.get_bdf(), []).append((offset, base_address, size))
                # Escribir la dirección al BAR del dispositivo
                addr_bytes = base_address.to_bytes(4, byteorder='little')
                bar_write = self._build_config_tlp(CFG0WR, source.get_bdf(), offset, data=addr_bytes)
                self.send(bar_write, source)
                return
        elif tlp_processing.format == CFG0WR:
            if offset < BARs.BAR5.value:
                bar_n_read = self._build_config_tlp(CFG0RD, source.get_bdf(), (offset + 0x4))
                self._set_enum_state(source, EnumState.BAR_PROBE)
                self.send(bar_n_read, source)
                return
            else:
                self._set_enum_state(source, EnumState.DONE)
        self.enumerate()

    def _next_tlp_id(self) -> int:
        return next(i for i in count() if i not in self._tlps)

    def enumerate(self):
        if not self._enabled:
            self.enumerated_devices[(0, 0, 0)] = self
            self.set_bdf(0,0,0)
            self._enabled = True

        for device in self._links:
            if not device._enabled: #Todo: si no tienen estados definidos en la FSM de enumeracion
                tlp_id = self._next_tlp_id()
                device_number = self._next_free_device_number(self._bus_number)  # siguiente device libre en bus 0
                cnfrd0 = ConfigType0Read(
                    requester_id=(self._bus_number, self._device_number, self._function_number),
                    destination_id=(self._bus_number, device_number, 0),
                    tag=0,
                    traffic_class=0,
                    attributes=0,
                    length=1,       # 1 dword = 4 bytes
                    tlp_id=tlp_id,
                    address=0x00    # lee desde offset 0x00 → Vendor ID (2 bytes) + Device ID (2 bytes)
                )

                self.send(cnfrd0, device)
                break

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

