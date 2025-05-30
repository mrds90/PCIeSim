from PcieLib.Device.endpoint import Endpoint, BARs
from PcieLib.Device.root_complex import RootComplex

rc = RootComplex("CPU")
ep1 = Endpoint("GPU",memory_sizes={BARs.BAR0: 1024, BARs.BAR3: 2048})
ep2 = Endpoint("NVMe")

rc.add_link(ep1)
rc.add_link(ep2)
rc.enumerate()

import time; time.sleep(0.5)




rc.stop()
ep1.stop()
ep2.stop()