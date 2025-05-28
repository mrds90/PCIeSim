import random
from abc import ABC, abstractmethod

# ================
# DEVICE CLASSES
# ================

class PCIDevice:
    def __init__(self, name):
        self.name = name
        self.parent = None
        self.connections = []
        self.bdf = None
        self.enumerated = False
        self.bus = None
        self.device = None
        self.function = None

    def connect(self, other_device):
        if other_device not in self.connections:
            self.connections.append(other_device)
        if self not in other_device.connections:
            other_device.connections.append(self)
        print(f"[CONEXIÓN] {self.name} <--> {other_device.name}")

    def set_bdf(self, bus, device, function):
        self.bus = bus
        self.device = device
        self.function = function
        self.enumerated = True

    def get_bdf(self):
        bus = f"{self.bus:02X}" if self.bus is not None else "??"
        device = f"{self.device:02X}" if self.device is not None else "??"
        function = f"{self.function:X}" if self.function is not None else "?"
        return f"{bus}:{device}.{function}"

    def get_id(self):
        return f"{self.get_bdf()} ({self.name})"

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
        # Allow Config responses during enumeration
        if not self.enumerated and not isinstance(tlp, (ConfigRead0, ConfigWrite0, Completion)):
            print(f"🚫 {self.name} no puede enviar (no enumerado): {tlp}")
            return

        print(f"\n[{self.name} -> {target.name}] Enviando TLP:\n{tlp}\n")
        visited = set()
        path = self.find_path_to(target, visited)
        if path:
            print(f"🔗 Ruta encontrada: {' -> '.join(device.get_id() for device in path)}")
            if len(path) > 1:
                next_hop = path[1]
                next_hop.receive(tlp, origin=self, path=path[1:])
        else:
            print(f"❌ {self.name} no puede alcanzar a {target.name}")

    def receive(self, tlp, origin=None, path=None):
        if not self.enumerated and not isinstance(tlp, (ConfigRead0, ConfigWrite0)):
            print(f"🚫 {self.name} ignoró TLP (no enumerado): {tlp}")
            return

        print(f"📥 [{self.name} <- {origin.name if origin else 'N/A'}] Recibido TLP\n{tlp}")

        if path:
            if len(path) > 1:
                next_hop = path[1]
                next_hop.receive(tlp, origin=self, path=path[1:])
            else:
                self._handle_tlp(tlp)
        else:
            self._handle_tlp(tlp)

    def _handle_tlp(self, tlp):
        if isinstance(tlp, ConfigRead0):
            # Set BDF before responding
            self.set_bdf(0, tlp.device_num, tlp.function_num)
            response = Completion(
                fmt="CplD",
                completer_id=self,
                requester_id=tlp.requester_id,
                tag=tlp.tag,
                address=0,
                data=0xFFFFFFFF  # Device present
            )
            self.send(response, tlp.requester_id)
            return True
            
        elif isinstance(tlp, ConfigWrite0):
            if tlp.device_num == self.device and tlp.function_num == self.function:
                if tlp.offset == 0x10:  # BAR0
                    self.bar_start = tlp.data
                    print(f"💾 [{self.name}] BAR0 configurado: {hex(self.bar_start)}")
                elif tlp.offset == 0x18 and isinstance(self, Switch):
                    self.secondary_bus = tlp.data
                    print(f"🔄 [{self.name}] Bus secundario configurado: {hex(self.secondary_bus)}")
                return True
            
        elif isinstance(tlp, MemoryRead):
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

    def print_topology(self, visited=None, indent=0):
        if visited is None:
            visited = set()
        visited.add(self)
        print("    " * indent + f"└─ {self.get_id()}")
        for conn in self.connections:
            if conn not in visited:
                conn.print_topology(visited, indent + 1)
    
    def _probe_device(self, cfg_read):
        """Probe for device existence using Config Read"""
        for device in self.connections:
            if not device.enumerated:  # Only probe unenumerated devices
                self.send(cfg_read, device)
                return device
        return None


class Endpoint(PCIDevice):
    def __init__(self, name, bar_start=0xC000_0000):
        super().__init__(name)
        self.bar_start = bar_start
        self.memory = {
            0x1000: 0xABCD1234,
            0x2000: 0xDEADBEEF
        }
        self.interrupt_capable = True


class Host(PCIDevice):
    def __init__(self, name):
        super().__init__(name)


class RootComplex(PCIDevice):
    def __init__(self, name):
        super().__init__(name)
        self.next_bus = 1
        
    def _find_device_by_bdf(self, bus, device, function):
        """Support finding devices behind the switch"""
        if bus == self.secondary_bus:
            for dev in self.connections:
                if not isinstance(dev, (RootComplex, Switch)):
                    return dev  # Return first endpoint device found
        return None

    def _enumerate_secondary_bus(self, switch, bus_num):
        """Enumerate devices behind a switch"""
        print(f"\n🔄 Enumerando bus secundario {bus_num} detrás de {switch.name}")
        
        # Probe for devices on secondary bus
        for dev_num in range(32):
            cfg_read = ConfigRead0(
                requester_id=self,
                device_num=dev_num,
                function_num=0
            )
            
            device = switch._find_device_by_bdf(bus_num, dev_num, 0)
            if device and not device.enumerated:
                device.set_bdf(bus_num, dev_num, 0)
                
                # Configure BAR for endpoints
                if isinstance(device, Endpoint):
                    cfg_write = ConfigWrite0(
                        requester_id=self,
                        device_num=dev_num,
                        function_num=0,
                        offset=0x10,
                        data=device.bar_start
                    )
                    self.send(cfg_write, device)

    def enumerate(self, bus = 0, node = None):
        current_device = 0
        if bus == 0:
            print("\n🔍 Iniciando enumeración PCIe...")
            self.set_bdf(0, 0, 0)  # RC siempre es 0:0.0
            current_device = 1  # Start from device 1 (0 is RC)
        if node is None:
            node = self
            # Enumerar dispositivos en el bus primario
        for device in node.connections:
            if not device.enumerated:
                cfg_read = ConfigRead0(
                    requester_id=self,
                    device_num=current_device,
                    function_num=0
                )
                
                # Configure device if found
                node.send(cfg_read, device)
                device.set_bdf(bus, current_device, 0)
                
                # Configure BAR for endpoints
                if isinstance(device, Endpoint):
                    cfg_write = ConfigWrite0(
                        requester_id=node,
                        device_num=current_device,
                        function_num=0,
                        offset=0x10,  # BAR0
                        data=device.bar_start
                    )
                    node.send(cfg_write, device)
                
                # Configure switches and enumerate secondary bus
                elif isinstance(device, Switch):
                    new_bus = self.next_bus
                    self.next_bus += 1
                    cfg_write = ConfigWrite0(
                        requester_id=self,
                        device_num=device.device,
                        function_num=0,
                        offset=0x18,  # Secondary bus number register
                        data=new_bus
                    )
                    node.send(cfg_write, device)
                    self.enumerate(new_bus, device)
                
                current_device += 1


class Switch(PCIDevice):
    def __init__(self, name):
        super().__init__(name)
        self.primary_bus = None
        self.secondary_bus = None
        
    def _find_device_by_bdf(self, bus, device, function):
        """Support finding devices behind the switch"""
        if bus == self.secondary_bus:
            for dev in self.connections:
                if not isinstance(dev, (RootComplex, Switch)) and not dev.enumerated:
                    return dev
        return None

# ================
# TLP CLASSES
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
        self.posted = posted

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


class ConfigRead(TLP):
    def __init__(self, type, requester_id, address, offset):
        super().__init__(fmt=f"cfg{type}", requester_id=requester_id, tag=random.randint(0, 255), address=offset)
        self.cfg_type = type
        self.offset = offset

    def __str__(self):
        return (
            f"TLP Type : Config Read 0 ({self.fmt})\n"
            f"Address  : {self.address}\n"
            f"Offset   : {self.offset}"
        )


class ConfigWrite(TLP):
    def __init__(self, type, requester_id, address, offset, data):
        super().__init__(fmt=f"cfg{type}", requester_id=requester_id, tag=random.randint(0, 255), address=offset)
        self.cfg_type = type
        self.offset = offset
        self.data = data

    def __str__(self):
        return (
            f"TLP Type : Config Write 0 ({self.fmt})\n"
            f"Address  : {self.address}\n"
            f"Offset   : {self.offset}\n"
            f"Data     : {self.data}"
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


class ConfigRead0(TLP):
    def __init__(self, requester_id, device_num, function_num):
        super().__init__(fmt="CfgRd0", requester_id=requester_id, 
                        tag=random.randint(0, 255), address=0)
        self.device_num = device_num
        self.function_num = function_num

    def __str__(self):
        return (
            f"TLP Type : Configuration Read Type 0 ({self.fmt})\n"
            f"Requester ID : {self.requester_id.get_id()}\n"
            f"Device      : {self.device_num:02X}\n"
            f"Function    : {self.function_num:X}"
        )


class ConfigWrite0(TLP):
    def __init__(self, requester_id, device_num, function_num, offset, data):
        super().__init__(fmt="CfgWr0", requester_id=requester_id,
                        tag=random.randint(0, 255), address=0)
        self.device_num = device_num
        self.function_num = function_num
        self.offset = offset
        self.data = data

    def __str__(self):
        return (
            f"TLP Type : Configuration Write Type 0 ({self.fmt})\n"
            f"Requester ID : {self.requester_id.get_id()}\n"
            f"Device      : {self.device_num:02X}\n"
            f"Function    : {self.function_num:X}\n"
            f"Offset      : {hex(self.offset)}\n"
            f"Data        : {hex(self.data)}"
        )

# ========================
#  SIMULACIÓN DE TRÁFICO
# ========================

def run_simulation():
    print("\n🚀 Iniciando simulación PCIe...")
    
    # 1. Crear dispositivos
    print("\n📦 Creando dispositivos...")
    CPU = RootComplex("CPU")
    SW1 = Switch("SW1")
    SW2 = Switch("SW2")
    GPU = Endpoint("GPU", bar_start=0xC000_0000)
    NVME = Endpoint("NVME", bar_start=0xC000_1000)
    

    # 2. Establecer conexiones físicas
    print("\n🔌 Estableciendo conexiones...")
    CPU.connect(SW1)
    SW1.connect(GPU)
    CPU.connect(NVME)

    # 3. Proceso de enumeración
    print("\n📝 Iniciando proceso de enumeración...")
    CPU.enumerate()

    # 4. Mostrar topología resultante
    print("\n📡 Topología PCIe final:")
    CPU.print_topology()

    # 5. Simular transacciones de memoria
    print("\n💾 Simulando transacciones de memoria...")
    
    # Read transaction
    read_tlp = MemoryRead(
        fmt="3DW w/o Data",
        length=4,
        requester_id=CPU,
        tag=0x1A,
        address=0xC000_1000
    )
    CPU.send(read_tlp, GPU)

    # Non-posted write
    write_tlp_np = MemoryWrite(
        fmt="3DW w/ Data",
        requester_id=CPU,
        tag=0x2B,
        address=0xC000_2000,
        data=0xCAFEBABE,
        posted=False
    )
    CPU.send(write_tlp_np, NVME)

    # Posted write
    write_tlp_p = MemoryWrite(
        fmt="3DW w/ Data",
        requester_id=CPU,
        tag=0x2C,
        address=0xC000_2004,
        data=0xDEADBEEF,
        posted=True
    )
    CPU.send(write_tlp_p, GPU)

if __name__ == "__main__":
    run_simulation()
