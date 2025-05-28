from PcieLib.Device.endpoint import Endpoint
from PcieLib.Device.root_complex import RootComplex

rc = RootComplex("CPU")
ep1 = Endpoint("GPU")
ep2 = Endpoint("NVMe")

rc.add_link(ep1)
rc.add_link(ep2)
rc.enumerate()

import time; time.sleep(0.5)




rc.stop()
ep1.stop()
ep2.stop()