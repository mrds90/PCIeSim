from typing import Optional, Tuple, Dict, List
from .pcie_device import PCIEDevice
from .endpoint import Endpoint
from PcieLib.TLP import TLP, Completion, CompletionWithData, ConfigType0Read, ConfigType0Write, ConfigType1Read, ConfigType1Write, MemoryTLPRead, MemoryTLPWithData, CFG0RD, CFG1RD, CFG0WR, CFG1WR  
from itertools import count


class RootComplex(PCIEDevice):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tlps: Dict[int, TLP] = {}  # mapea TLP IDs a TLPs
        self.enumerated_devices: Dict[Tuple[int, int, int], PCIEDevice] = {}
        self.memory_map: Dict[Tuple[int, int, int], List[Tuple[int, int, int]]] = {}
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

            # Verifico si es un Config Type 0 Read (CFG0RD es tu constante que indica esto)
            if tlp_processing.format == CFG0RD:
                self._handle_completion_CFG0RD(tlp_processing, tlp, source)

            elif tlp_processing.format == CFG0WR:
                addr = tlp_processing.address
                data = tlp_processing.data

                # Verificamos si fue una escritura a un BAR (offset 0x10 - 0x24)
                if 0x10 <= addr <= 0x24 and data == [0xFF, 0xFF, 0xFF, 0xFF]:
                    # Probing de tamaño de BAR
                    self._handle_bar_probe(tlp_processing, source)
                
    
    def _handle_bar_probe(self, cfg_write: ConfigType0Write, device: PCIEDevice):
        addr = cfg_write.address
        cfg_read = self._build_config_tlp(CFG0RD,device.get_bdf(), addr)
        self.send(cfg_read, device)
    
    def _handle_completion_CFG0RD(self, tlp_sent: ConfigType0Read, tlp_received: CompletionWithData, source: PCIEDevice):
        offset = tlp_sent.address & 0xFF
        if (offset) == 0:
            # Asigno un BDF al dispositivo que respondió
            
            self.enumerated_devices[source.get_bdf()] = source
            print(f"{source.name} enumerado: BDF {source.get_bdf()}\n")

            # ⬇️ Ahora generamos otro Config Read para el offset 0x0C (Header Type)
            cfg_header_type = self._build_config_tlp(CFG0RD,source.get_bdf(), 0x0C)
            self.send(cfg_header_type, source)
        elif (offset) == 0x0C:
            header_type = tlp_received.data[0]  # asumimos que data es una lista de bytes
            bdf = f"{source.bus_number}.{source.device_number}.{source.function_number}"
            if (header_type & 0x7F) == 0x01:
                print(f"Dispositivo {source.name}:{bdf} es un Switch (Header Type 0x{header_type:02X}).")
                self.enumerate_secondary_bus(source)  # 🚀 enumerar el nuevo bus detrás del switch
            elif (header_type & 0x7F) == 0x00:
                print(f"Dispositivo {source.name}:{bdf} es un Endpoint (Header Type 0x{header_type:02X}).")
                bar0_read = self._build_config_tlp(CFG0RD, source.get_bdf(), 0x10)
                self.send(bar0_read, source)

            else:
                print(f"Dispositivo {source.name}:{bdf} tiene un tipo desconocido: 0x{header_type:02X}.\n")
        elif 0x10 <= offset <= 0x24 and offset % 4 == 0:
            if tlp_received.bytes_to_dwords()[0] == 0:
                # Trigger de size detection
                bar_probe_write = self._build_config_tlp(CFG0WR, source.get_bdf(), 0x10, data=[0xFF, 0xFF, 0xFF, 0xFF])
                self.send(bar_probe_write, source)

            elif getattr(source, "bar_address", 0) == 0xFFFFFFF0:
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
                bar_write = self._build_config_tlp(CFG0WR, source.get_bdf(), 0x10, data=addr_bytes)
                self.send(bar_write, source)
                self.enumerate()


                



    def _next_tlp_id(self) -> int:
        return next(i for i in count() if i not in self._tlps)
         
    def enumerate(self):
        if not self._enabled:
            self.enumerated_devices[(0, 0, 0)] = self
            self.set_bdf(0,0,0)
            self._enabled = True
        
        for device in self._links:
            if not device._enabled:
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

