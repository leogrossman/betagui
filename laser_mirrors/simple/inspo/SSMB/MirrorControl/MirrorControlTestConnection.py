# -*- coding: utf-8 -*-

import sys
import clr
from time import sleep

CmdLibPath = 'C:\\Program Files\\New Focus\\New Focus Picomotor Application\\Samples'
sys.path.append(CmdLibPath)

clr.AddReference('CmdLib')

from NewFocus import Picomotor

clr.AddReference('System')
import System

ctrl = Picomotor.CmdLib8742(False, 3000)
try:
    keys = ctrl.GetDeviceKeys()
    testkey = "8742 14119"
    found = False

    for key in keys:
        print(key)
        print(ctrl.GetModelSerial(key))
        found |= key == testkey

    stringvar = System.String("")
    
    if found:
        print(ctrl.GetErrorMsg(testkey, stringvar))
        print(ctrl.RelativeMove(testkey, 4, 100))
        for i in range(10):
            print(ctrl.GetErrorMsg(testkey, stringvar))
            print(ctrl.GetErrorMsg(testkey, stringvar))
            print(ctrl.GetErrorMsg(testkey, stringvar))
            sleep(.1)

finally:
    ctrl.Shutdown()