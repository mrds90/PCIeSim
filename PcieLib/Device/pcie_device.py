from typing import Dict, List
from abc import ABC, abstractmethod
import threading
from queue import Queue
from PcieLib.TLP import TLP, Completion, CompletionWithData, ConfigType0Read
import random
from enum import Enum

class BARs(Enum):
    BAR0 = 0x10
    BAR1 = 0x14
    BAR2 = 0x18
    BAR3 = 0x1C
    BAR4 = 0x20
    BAR5 = 0x24

class PCIEDevice(ABC):

    MAX_NAME_LENGTH = 4  # 2 chars for vendor_id, 2 for device_id

    def __init__(self, name: str):
        if len(name) > self.MAX_NAME_LENGTH:
            raise ValueError(f"Name '{name}' exceeds {self.MAX_NAME_LENGTH} characters.")

        padded_name = name.ljust(self.MAX_NAME_LENGTH)  # pad with spaces if needed
        vendor_str = padded_name[:2]
        device_str = padded_name[2:]

        # Convert characters to integer byte values
        vendor_id = (ord(vendor_str[1]) << 8) + ord(vendor_str[0])
        device_id = (ord(device_str[1]) << 8) + ord(device_str[0])

        self._parent = None
        self._links: List['PCIEDevice'] = []
        self._bus_number = None
        self._device_number = None
        self._function_number = None
        self._enabled = False
        self.incoming_queue = Queue()
        self._running = True

        self._config_space: Dict[int, int] = {
            0x00: vendor_id & 0xFF,         # Vendor ID low byte
            0x01: (vendor_id >> 8) & 0xFF,  # Vendor ID high byte
            0x02: device_id & 0xFF,         # Device ID low byte
            0x03: (device_id >> 8) & 0xFF,  # Device ID high byte
            0x04: 0x00,                     # Command register low byte
            0x05: 0x00,                     # Command register high byte
            0x06: 0x00,                     # Status register low byte
            0x07: 0x00,                     # Status register high byte
            0x08: random.randint(0x00, 0xFF), # Revision ID
            0x09: random.randint(0x00, 0xFF), # Class Code byte 2 (Base class)
            0x0A: random.randint(0x00, 0xFF), # Class Code byte 1 (Sub-class)
            0x0B: random.randint(0x00, 0xFF), # Class Code byte 0 (Programming Interface)
            0x0D: 0x00,                      # BIST
        }
        # Lanzamos el thread en segundo plano para manejar la cola
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()      

    def send(self, tlp: TLP, destination: 'PCIEDevice'):
        if isinstance(tlp, Completion):
            print(f"{destination.name} <- {self.name}: {tlp}\n")
        else:
            dest_name = destination.name if destination._enabled else "Unknown"
            print(f"{self.name} -> {dest_name}: {tlp}\n")
        destination.incoming_queue.put((tlp, self))

    def receive(self, tlp, source: 'PCIEDevice'):
        # Este método lo implementás en cada subclase
        print(f"{self.name} recibió: {tlp} desde {source.name}")

    def _handle_config0_read(self, tlp: ConfigType0Read, source: 'PCIEDevice'):
        offset = tlp.address & 0xFF  # los 8 bits bajos del address
        if offset == 0:
            self.set_bdf(tlp.destination_id[0],tlp.destination_id[1],tlp.destination_id[2])
        data = [
            self._config_space.get(offset + i, 0xFF) for i in range(4)
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

    def _read_config_dword(self, offset: int) -> int:
        val = 0
        for i in range(4):
            val |= self._config_space.get(offset + i, 0) << (8 * i)
        return val

    def _write_config_dword(self, offset: int, value: int):
        for i in range(4):
            self._config_space[offset + i] = (value >> (8 * i)) & 0xFF


    def _process_loop(self):
        while self._running:
            tlp, source = self.incoming_queue.get()  # bloquea hasta que haya algo
            if tlp!= None:
                self.receive(tlp, source)         

    def stop(self):
        self._running = False
        self.incoming_queue.put((None, None))  # fuerza el desbloqueo de get()
        self._thread.join()
        print(f"{self.name} turned off")

    def add_link(self, device: 'PCIEDevice'):
        """Agrega un dispositivo conectado directamente a través de un enlace PCIe."""
        if device not in self._links:
            self._links.append(device)
            device.parent = self

    def set_bdf(self, bus_number, device_number, function_number):
        """Establece el bus, dispositivo y función del dispositivo PCIe."""
        self._bus_number = bus_number
        self._device_number = device_number
        self._function_number = function_number
        self._enabled = True
    
    def get_bdf(self):
        return(self._bus_number,self._device_number,self._function_number)
    
    def get_downstream_devices(self) -> List['PCIEDevice']:
        return self._links
   
    @property
    def parent(self):
        """Devuelve el dispositivo padre (switch o RC) al que está conectado este dispositivo."""
        return self._parent
    @parent.setter
    def parent(self, value: 'PCIEDevice'):
        """Establece el dispositivo padre (switch o RC) al que está conectado este dispositivo."""
        if value is not None and isinstance(value, PCIEDevice):
            self._parent = value
        else:
            raise TypeError("Parent must be a PCIEDevice or None")
    
    @property
    def bus_number(self):
        """Devuelve el número de bus del dispositivo PCIe."""
        return self._bus_number
    
    @property
    def device_number(self):
        """Devuelve el número de dispositivo del dispositivo PCIe."""
        return self._device_number
    
    @property
    def function_number(self):
        """Devuelve el número de función del dispositivo PCIe."""
        return self._function_number
    
    @property
    def name(self) -> str:
        # Reconstruct name from vendor_id and device_id in config space
        vendor_id = (self._config_space[0x01] << 8) + self._config_space[0x00]
        device_id = (self._config_space[0x03] << 8) + self._config_space[0x02]

        vendor_str = chr(vendor_id & 0xFF) + chr((vendor_id >> 8) & 0xFF)
        device_str = chr(device_id & 0xFF) + chr((device_id >> 8) & 0xFF)

        return (vendor_str + device_str).rstrip() # strip right-side spaces