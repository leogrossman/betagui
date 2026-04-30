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

print("Start")

ctrl = Picomotor.CmdLib8742(False, 10000)
try:
    keys = ctrl.GetDeviceKeys()
    
    boolvar = System.Boolean(False)
    intvar = System.Int32(-1)
    stringvar = System.String("")
    
#    for key in keys:
#        print("open", key)
#        print(ctrl.Open(key))

    for i in range(4):
        sleep(1)
        print("\ntest\n")
        print(keys)
        for key in keys:
#            print(key)
            
            print("open", key)
            print(ctrl.Open(key))
            print(ctrl.GetModelSerial(key))
            print(ctrl.GetMotionDone(key, 3, boolvar))
            print(ctrl.GetPosition(key, 3, intvar))
            print(ctrl.GetErrorMsg(key, stringvar))
            print("close", key)
            print(ctrl.Close(key))
        print("\ntest\n")
finally:
    ctrl.Shutdown()
    print('Shutdown')