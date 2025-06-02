from PcieLib.Device.endpoint import Endpoint, BARs
from PcieLib.Device.root_complex import RootComplex
from PcieLib.Device.switch import Switch

rc = RootComplex("CPU")
ep1 = Endpoint("GPU",memory_sizes={BARs.BAR0: 1024, BARs.BAR3: 2048})
ep2 = Endpoint("NVMe")
ep3 = Endpoint("SEN1")
sw1 = Switch("SW1")
sw2 = Switch("SW2")

rc.add_link(sw1)
sw1.add_link(sw2)
sw1.add_link(ep2)
sw2.add_link(ep1)
rc.add_link(ep3)

rc.enumerate()


import time; time.sleep(0.5)

rc.print_topology()




rc.stop()
sw1.stop()
sw2.stop()
ep1.stop()
ep2.stop()
ep3.stop()