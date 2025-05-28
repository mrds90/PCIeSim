from typing import Dict, Tuple
from .pcie_device import PCIEDevice
from .endpoint import Endpoint
from PcieLib.TLP import TLP, Completion, CompletionWithData, ConfigType0Read, ConfigType0Write, MemoryTLPRead, MemoryTLPWrite, CFG0RD, CFG1RD, CFG0WR, CFG1WR

class RootComplex(PCIEDevice):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tlps: Dict[int, TLP] = {}  # mapea TLP IDs a TLPs
        self.enumerated_devices: Dict[Tuple[int, int, int], PCIEDevice] = {}
    
    def receive(self, tlp: TLP, source: PCIEDevice):
        if isinstance(tlp, (MemoryTLPRead, MemoryTLPWrite)):
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
                # Chequeo si el offset (address) es 0, que es el primer registro de configuración
                if (tlp_processing.address & 0xFFF) == 0:
                    # Asigno un BDF al dispositivo que respondió
                    bus = 0  # asumí bus 0 para simplificar, podés cambiar según tu lógica
                    device = self._next_free_device_number(bus)  # siguiente device libre en bus 0
                    function = 0  # generalmente empieza en función 0

                    # Seteo el BDF al dispositivo source
                    source.set_bdf(bus, device, function)

                    # Guardo el dispositivo enumerado con su BDF
                    self.enumerated_devices[(source.bus_number, source.device_number, source.function_number)] = source

                    # Podrías imprimir/loguear esto para debug
                    print(f"Dispositivo enumerado: BDF {bus}:{device}:{function}\n")

                    self.enumerate()##Todo: quede aca donde falta consultar el espacio de configuración para saber si el dispositivo es EP o SW

            # Aquí podrías agregar otros manejos de completion para otros tipos de TLP


                
    def enumerate(self):
        if not self._enabled:
            self.enumerated_devices[(0, 0, 0)] = self
            self.set_bdf(0,0,0)
            self._enabled = True
        
        for device in self._links:
            if not device._enabled:
                cnfrd0 = ConfigType0Read(
                    type="config_read",
                    requester_id=(self._bus_number, self._device_number, self._function_number),
                    tag=0,
                    traffic_class=0,
                    attributes=0,
                    length=1,
                    tlp_id=0,
                    address=0
                )
                self._tlps[cnfrd0.tlp_id] = cnfrd0
                self.send(cnfrd0, device)
                break

    def _next_free_device_number(self, bus_number: int) -> int:
        used_device_numbers = {dev for (bus, dev, _) in self.enumerated_devices if bus == bus_number}
        for num in range(32):  # PCIe permite hasta 32 dispositivos por bus
            if num not in used_device_numbers:
                return num
        raise RuntimeError(f"No hay espacio libre en el bus {bus_number}")
