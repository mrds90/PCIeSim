import random
from abc import ABC, abstractmethod

# ================
#  DEVICE CLASSES
# ================
class Device(ABC):
    def __init__(self, name, bus, device, function):
        self.name = name
        self.bus = bus
        self.device = device
        self.function = function
        self.connections = []

    def get_bdf(self):
        return f"{self.bus:02X}:{self.device:02X}.{self.function:X}"

    def get_id(self):
        return f"{self.get_bdf()} ({self.name})"

    def connect(self, other_device):
        if other_device not in self.connections:
            self.connections.append(other_device)
        if self not in other_device.connections:
            other_device.connections.append(self)
        print(f"[CONEXIÓN] {self.name} <--> {other_device.name}")

    
    def find_path_to(self, target, visited):
        if self == target:
            return [self]
        visited.add(self)
        for conn in self.connections:
            if conn not in visited:
                path = conn.find_path_to(target, visited)
                if path:
                    return [self] + path
        return None

    def send(self, tlp, target):
        print(f"\n[{self.name} -> {target.name}] Enviando TLP:\n{tlp}")
        visited = set()
        path = self.find_path_to(target, visited)
        if path:
            next_hop = path[1]  # el siguiente nodo después de self
            next_hop.receive(tlp, origin=self, path=path[1:])
        else:
            print(f"❌ {self.name} no puede alcanzar a {target.name}")


    def receive(self, tlp, origin=None, path=None):
        print(f"📥 [{self.name}] Recibido TLP desde {origin.name if origin else 'N/A'}\n{tlp}")
        if path:
            next_hop = path[0]
            next_hop.receive(tlp, origin=self, path=path[1:])
        else:
            # print(f"[{self.name}] Recibido TLP desde {origin.name}:\n{tlp}")
            if isinstance(tlp, MemoryRead):
                offset = tlp.address - getattr(self, 'bar_start', 0)
                data = hex(self.memory.get(offset, 0x12345678))
                response = Completion(
                    fmt="CplD",
                    completer_id=self,
                    requester_id=tlp.requester_id,
                    tag=tlp.tag,
                    address=tlp.address,
                    data=data
                )
                self.send(response, tlp.requester_id)


class Endpoint(Device):
    def __init__(self, name, bus, device, function, bar_start=0xC000_0000):
        super().__init__(name, bus, device, function)
        self.bar_start = bar_start
        self.memory = {
            0x1000: 0xABCD1234,
            0x2000: 0xDEADBEEF
        }
        self.interrupt_capable = True


class Host(Device):
    def __init__(self, name, bus=0x00, device=0x00, function=0x0):
        super().__init__(name, bus, device, function)


class RootComplex(Device):
    def __init__(self, name="RC", bus=0x00, device=0x00, function=0x0):
        super().__init__(name, bus, device, function)


class Switch(Device):
    def __init__(self, name, bus, device, function):
        super().__init__(name, bus, device, function)


# ================
#  TLP CLASSES
# ================
class TLP(ABC):
    def __init__(self, fmt, requester_id, tag, address):
        self.fmt = fmt
        self.requester_id = requester_id
        self.tag = tag
        self.address = address
        self.tlp_type = self.__class__.__name__

    @abstractmethod
    def __str__(self):
        ...


class MemoryRead(TLP):
    def __init__(self, fmt, length, requester_id, tag, address):
        super().__init__(fmt, requester_id, tag, address)
        self.length = length

    def __str__(self):
        return (
            f"TLP Type : Memory Read ({self.fmt})\n"
            f"Requester ID : {self.requester_id.get_id()}\n"
            f"Tag          : 0x{self.tag:02X}\n"
            f"Length       : {self.length} DW\n"
            f"Address      : {hex(self.address)}"
        )


class MemoryWrite(TLP):
    def __init__(self, fmt, requester_id, tag, address, data):
        super().__init__(fmt, requester_id, tag, address)
        self.data = data

    def __str__(self):
        return (
            f"TLP Type : Memory Write ({self.fmt})\n"
            f"Requester ID : {self.requester_id.get_id()}\n"
            f"Tag          : 0x{self.tag:02X}\n"
            f"Address      : {hex(self.address)}\n"
            f"Data         : {self.data}"
        )


class Completion(TLP):
    def __init__(self, fmt, completer_id, requester_id, tag, address, data):
        super().__init__(fmt, requester_id, tag, address)
        self.completer_id = completer_id
        self.data = data

    def __str__(self):
        return (
            f"TLP Type : Completion with Data ({self.fmt})\n"
            f"Completer ID : {self.completer_id.get_id()}\n"
            f"Requester ID : {self.requester_id.get_id()}\n"
            f"Tag          : 0x{self.tag:02X}\n"
            f"Address      : {hex(self.address)}\n"
            f"Data         : {self.data}"
        )

# ========================
#  SIMULACIÓN DE TRÁFICO
# ========================
# Crear dispositivos
CPU = Host("CPU", bus=0x00, device=0x00, function=0)
RC = RootComplex("RC", bus=0x00, device=0x00, function=0)
SW1 = Switch("SW1", bus=0x00, device=0x01, function=0)
GPU = Endpoint("GPU", bus=0x02, device=0x00, function=0)

# Conectar dispositivos
CPU.connect(RC)
RC.connect(SW1)
SW1.connect(GPU)

# Flujo: CPU lee memoria de la GPU
read_tlp = MemoryRead(
    fmt="3DW w/o Data",
    length=4,
    requester_id=CPU,
    tag=0x1A,
    address=0xC000_1000
)
CPU.send(read_tlp, GPU)

# Flujo: CPU escribe en memoria de la GPU
write_tlp = MemoryWrite(
    fmt="3DW w/ Data",
    requester_id=CPU,
    tag=0x2B,
    address=0xC000_2000,
    data="0xCAFEBABE"
)
CPU.send(write_tlp, GPU)
