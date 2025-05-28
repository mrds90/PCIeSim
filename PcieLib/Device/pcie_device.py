from typing import Dict
from abc import ABC, abstractmethod
import threading
from queue import Queue

class PCIEDevice(ABC):
    def __init__(self, name:str):
        self._parent = None
        self._links = []
        self._config_space = {}
        self._bus_number = None
        self._device_number = None
        self._function_number = None
        self._enabled = False
        self._name = name
        self._config_space: Dict[int, int]
        self.incoming_queue = Queue()
        self._running = True

        # Lanzamos el thread en segundo plano para manejar la cola
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def send(self, tlp, destination: 'PCIEDevice'):
        print(f"{self.name} -> {destination.name}: {tlp}\n")
        destination.incoming_queue.put((tlp, self))

    def receive(self, tlp, source: 'PCIEDevice'):
        # Este método lo implementás en cada subclase
        print(f"{self.name} recibió: {tlp} desde {source.name}")

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
    def name(self):
        return self._name