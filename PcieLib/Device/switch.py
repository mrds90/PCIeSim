from typing import Optional, Tuple, Dict
from .pcie_device import PCIEDevice, BARs
from PcieLib.TLP import TLP, TLPWithData, Config, ConfigType0Read, ConfigType1Read, ConfigType0Write ,ConfigType1Write, MemoryTLPRead, MemoryTLPWithData, Completion, CompletionWithData, CompletionWithoutData

class Switch(PCIEDevice):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._config_space[0x0C] = 0x01  # Header type: Switch
        

    def receive(self, tlp, source: 'PCIEDevice'):
        if isinstance(tlp, ConfigType0Write):
            if tlp.destination_id == self.get_bdf():
                self._handle_config0_write(tlp, source)
        elif isinstance(tlp, ConfigType1Write):
            self._handle_config1_write(tlp, source)
        # Verificamos si el TLP es un ConfigType0Read que nos pertenece
        elif isinstance(tlp, ConfigType0Read):
            super()._handle_config0_read(tlp, source)
        elif isinstance(tlp, ConfigType1Read):
            self._handle_config1_read(tlp, source)
        elif isinstance(tlp, Completion):
            if self.parent:
                self.send(tlp, self.parent)
            else:
                raise RuntimeError(f"[{self.name}] No se puede reenviar Completion: atributo 'parent' no asignado.")

    
    def _handle_config0_write(self, tlp: ConfigType0Write, source: 'PCIEDevice'):
        offset = tlp.address & 0xFF
        data = tlp.data  # List[int]

        # Escribimos en el config space simulado
        for i, byte in enumerate(data):
            self._config_space[offset + i] = byte

        # Si es la configuración de buses, lo interpretamos
        if offset == 0x18 and len(data) >= 3:
            self.primary_bus = data[0]
            self.secondary_bus = data[1]
            self.subordinate_bus = data[2]
            print(f"[{self.name}] 🎛️ Buses configurados: Primary={self.primary_bus}, Secondary={self.secondary_bus}, Subordinate={self.subordinate_bus}")

        # Armamos y enviamos el Completion sin data (como indica la spec PCIe)
        completion = CompletionWithoutData(
            format="Cpl",
            type="completion",
            requester_id=tlp.requester_id,
            tag=tlp.tag,
            traffic_class=tlp.traffic_class,
            attributes=tlp.attributes,
            length=0,
            tlp_id=tlp.tlp_id,
            completer_id=self.get_bdf(),
            byte_count=0
        )
        self.send(completion, source)


    def _handle_config1_read(self, tlp: ConfigType1Read, source: 'PCIEDevice'):
        dst_bdf = tlp.destination_id
        dst_bus = dst_bdf[0]
        offset = tlp.address & 0x7F

        # Verificamos si está dentro del rango de buses que este switch maneja
        if not (self.secondary_bus <= dst_bus <= self.subordinate_bus):
            print(f"[{self.name}] ❌ TLP con destino {dst_bdf} fuera de rango del switch (sec={self.secondary_bus}, sub={self.subordinate_bus})")
            self._send_unsupported_completion(tlp, source)
            return

        # Si va al bus secundario, convertimos a ConfigType0Read
        if dst_bus == self.secondary_bus:
            tlp_to_send = ConfigType0Read(
                requester_id=tlp.requester_id,
                tag=tlp.tag,
                traffic_class=tlp.traffic_class,
                attributes=tlp.attributes,
                address=tlp.address,
                destination_id=tlp.destination_id,
                tlp_id=tlp.tlp_id
            )
        else:
            tlp_to_send = tlp  # Reenvío tal cual

        for device in self.get_downstream_devices():
            # Si es un intento de descubrimiento (offset 0x00), permitir respuesta
            if not device._enabled and offset == 0:
                self.send(tlp_to_send, device)
                return

            # Si es exactamente el device buscado
            if device.get_bdf() == dst_bdf:
                self.send(tlp_to_send, device)
                return

            # Si es un switch que maneja el rango destino, reenviar
            if hasattr(device, 'secondary_bus') and hasattr(device, 'subordinate_bus'):
                if device.secondary_bus <= dst_bus <= device.subordinate_bus:
                    self.send(tlp, device)
                    return

        print(f"[{self.name}] ❌ No se encontró dispositivo para BDF {dst_bdf}")
        self._send_unsupported_completion(tlp, source)


    def _handle_config1_write(self, tlp: ConfigType1Write, source: 'PCIEDevice'):
        dst_bdf = tlp.destination_id
        dst_bus = dst_bdf[0]
        offset = tlp.address & 0xFF
        data = tlp.data  # List[int]
        if offset == 0x18 and len(data) >= 3:
            self.subordinate_bus = data[2]

        # Verificamos si el destino está dentro del rango manejado por el switch
        if not (self.secondary_bus <= dst_bus <= self.subordinate_bus):
            print(f"[{self.name}] ❌ TLP con destino {dst_bdf} fuera de rango del switch (sec={self.secondary_bus}, sub={self.subordinate_bus})")
            self._send_unsupported_completion(tlp, source)
            return

        # Si va al bus secundario, convertimos a ConfigType0Write
        if dst_bus == self.secondary_bus:
            tlp_to_send = ConfigType0Write(
                requester_id=tlp.requester_id,
                tag=tlp.tag,
                traffic_class=tlp.traffic_class,
                attributes=tlp.attributes,
                address=tlp.address,
                data=tlp.data,
                destination_id=tlp.destination_id,
                tlp_id=tlp.tlp_id
            )
        else:
            tlp_to_send = tlp  # Reenviamos tal cual

        for device in self.get_downstream_devices():
            # Solo reenviamos si el dispositivo está enumerado
            if not device._enabled:
                continue

            # Si es exactamente el device buscado
            if device.get_bdf() == dst_bdf:
                self.send(tlp_to_send, device)
                return

            # Si es un switch que maneja el rango destino, reenviamos
            if hasattr(device, 'secondary_bus') and hasattr(device, 'subordinate_bus'):
                if device.secondary_bus <= dst_bus <= device.subordinate_bus:
                    self.send(tlp, device)
                    return

        print(f"[{self.name}] ❌ No se encontró dispositivo para BDF {dst_bdf}")
        self._send_unsupported_completion(tlp, source)


    def _send_unsupported_completion(self, tlp:Config, source:PCIEDevice):
        # Si no está el device, responder con 0xFF's (DWORD 4 bytes)
        
        data = [0xFF, 0xFF, 0xFF, 0xFF]
        completion = CompletionWithData(
            format="CplD",
            type="completion",
            requester_id=tlp.requester_id,
            tag=tlp.tag,
            traffic_class=tlp.traffic_class,
            attributes=tlp.attributes,
            length=1,
            tlp_id=tlp.tlp_id,
            completer_id=(tlp.destination_id[0], tlp.destination_id[1], tlp.destination_id[2]),
            byte_count=4,
            data=data
        )
        self.send(completion, source)


