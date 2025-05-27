import random
from abc import ABC, abstractmethod

# ================
#  DEVICE CLASSES
# ================
class Device(ABC):
    def __init__(self, name):
        self.name = name
        self.bus = None
        self.device = None
        self.function = None
        self.connections = []

    def get_bdf(self):
        # Devuelve en formato XX:XX.X, o placeholders si no enumerado aún
        bus = f"{self.bus:02X}" if self.bus is not None else "??"
        device = f"{self.device:02X}" if self.device is not None else "??"
        function = f"{self.function:X}" if self.function is not None else "?"
        return f"{bus}:{device}.{function}"

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
            print(f"🔗 Ruta encontrada: {' -> '.join(device.get_id() for device in path)}")
            next_hop = path[1]  # el siguiente nodo después de self
            next_hop.receive(tlp, origin=self, path=path[1:])
        else:
            print(f"❌ {self.name} no puede alcanzar a {target.name}")

    def receive(self, tlp, origin=None, path=None):
        print(f"📥 [{self.name}] Recibido TLP desde {origin.name if origin else 'N/A'}\n{tlp}")
        
        if path:
            if len(path) > 1:
                print(f"🔗 Ruta: {' -> '.join(device.get_id() for device in path)}")
                next_hop = path[1]
                next_hop.receive(tlp, origin=self, path=path[1:])
            else:
                # Ya estamos al final del camino
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
        else:
            # Último nodo (caso inicial sin path, no debería ocurrir si hay topología)
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


    def enumerate(self, bus=0, device_start=0, visited=None):
        if visited is None:
            visited = set()

        if self in visited:
            return device_start

        visited.add(self)
        self.bus = bus
        self.device = device_start
        self.function = 0

        next_device = device_start + 1

        for conn in self.connections:
            if conn not in visited:
                if isinstance(self, Switch):
                    # Switches asignan bus incrementado a sus conexiones
                    next_device = conn.enumerate(bus + 1, 0, visited)
                else:
                    # Otros dispositivos en el mismo bus con device++ 
                    next_device = conn.enumerate(bus, next_device, visited)
        return next_device

    def print_topology(self, visited=None, indent=0):
        if visited is None:
            visited = set()
        visited.add(self)
        print("    " * indent + f"└─ {self.get_id()}")
        for conn in self.connections:
            if conn not in visited:
                conn.print_topology(visited, indent + 1)


class Endpoint(Device):
    def __init__(self, name, bar_start=0xC000_0000):
        super().__init__(name)
        self.bar_start = bar_start
        self.memory = {
            0x1000: 0xABCD1234,
            0x2000: 0xDEADBEEF
        }
        self.interrupt_capable = True


class Host(Device):
    def __init__(self, name):
        super().__init__(name)


class RootComplex(Device):
    def __init__(self, name="RC"):
        super().__init__(name)


class Switch(Device):
    def __init__(self, name):
        super().__init__(name)


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
    def __init__(self, fmt, requester_id, tag, address, data, posted=True):
        super().__init__(fmt, requester_id, tag, address)
        self.data = data
        self.posted = posted  # True o False

    def __str__(self):
        posted_str = "posted" if self.posted else "non-posted"
        return (
            f"TLP Type : Memory Write ({self.fmt}, {posted_str})\n"
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

class ConfigRead0(TLP):
    def __init__(self, requester_id, tag, address):
        super().__init__(fmt="CfgRd0", requester_id=requester_id, tag=tag, address=address)

    def __str__(self):
        return (
            f"TLP Type : Configuration Read Type 0 ({self.fmt})\n"
            f"Requester ID : {self.requester_id.get_id()}\n"
            f"Tag          : 0x{self.tag:02X}\n"
            f"Address      : {hex(self.address)}"
        )


class ConfigWrite0(TLP):
    def __init__(self, requester_id, tag, address, data):
        super().__init__(fmt="CfgWr0", requester_id=requester_id, tag=tag, address=address)
        self.data = data

    def __str__(self):
        return (
            f"TLP Type : Configuration Write Type 0 ({self.fmt})\n"
            f"Requester ID : {self.requester_id.get_id()}\n"
            f"Tag          : 0x{self.tag:02X}\n"
            f"Address      : {hex(self.address)}\n"
            f"Data         : {self.data}"
        )


class ConfigRead1(TLP):
    def __init__(self, requester_id, tag, address):
        super().__init__(fmt="CfgRd1", requester_id=requester_id, tag=tag, address=address)

    def __str__(self):
        return (
            f"TLP Type : Configuration Read Type 1 ({self.fmt})\n"
            f"Requester ID : {self.requester_id.get_id()}\n"
            f"Tag          : 0x{self.tag:02X}\n"
            f"Address      : {hex(self.address)}"
        )


class ConfigWrite1(TLP):
    def __init__(self, requester_id, tag, address, data):
        super().__init__(fmt="CfgWr1", requester_id=requester_id, tag=tag, address=address)
        self.data = data

    def __str__(self):
        return (
            f"TLP Type : Configuration Write Type 1 ({self.fmt})\n"
            f"Requester ID : {self.requester_id.get_id()}\n"
            f"Tag          : 0x{self.tag:02X}\n"
            f"Address      : {hex(self.address)}\n"
            f"Data         : {self.data}"
        )

# ========================
#  SIMULACIÓN DE TRÁFICO
# ========================

# Crear dispositivos (sin asignar bus/device/function manualmente)
CPU = Host("CPU")
RC = RootComplex("RC")
SW1 = Switch("SW1")
GPU = Endpoint("GPU")

# Conectar dispositivos
CPU.connect(RC)
RC.connect(SW1)
SW1.connect(GPU)

# Enumerar automáticamente según jerarquía PCIe
RC.enumerate()

# Mostrar topología
print("\n📡 Topología PCIe:")
RC.print_topology()

# Flujo: CPU lee memoria de la GPU
read_tlp = MemoryRead(
    fmt="3DW w/o Data",
    length=4,
    requester_id=CPU,
    tag=0x1A,
    address=0xC000_1000
)
CPU.send(read_tlp, GPU)

# Flujo: CPU escribe en memoria de la GPU, non-posted
write_tlp_np = MemoryWrite(
    fmt="3DW w/ Data",
    requester_id=CPU,
    tag=0x2B,
    address=0xC000_2000,
    data="0xCAFEBABE",
    posted=False
)
CPU.send(write_tlp_np, GPU)

# Flujo: CPU escribe en memoria de la GPU, posted
write_tlp_p = MemoryWrite(
    fmt="3DW w/ Data",
    requester_id=CPU,
    tag=0x2C,
    address=0xC000_2004,
    data="0xDEADBEEF",
    posted=True
)
CPU.send(write_tlp_p, GPU)
