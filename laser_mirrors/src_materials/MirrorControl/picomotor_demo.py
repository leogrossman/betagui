"""
Simple test script to run a New Focus 8742 controller. 
Requires drivers to be installed and CmdLib.dll to be present either on the path or in the same folder as the script
Also needs python .NET module to be installed 
(https://stackoverflow.com/questions/14633695/how-to-install-python-for-net-on-windows for more information, or use pip to install it ["pip install pythonnet"])
Run this from the windows shell by typing "python -i picomotor_demo.py"
(The parameter -i makes python run the script and remain in python for an interactive command prompt)

Tested on a 64 bit machine with the 64 bit driver installed
"""

import clr #import python .NET module
clr.AddReference("CmdLib") #load DLL
from NewFocus import Picomotor #import Picomotor namespace

obj = Picomotor.CmdLib8742(False,1000) #Instantiate controller
keys = obj.GetDeviceKeys() #Get device keys
if keys is not None:
    print('Found device with serial no. ' +str(keys[0])) #Print first device found (serial no)
    ret = obj.Open(keys[0]) #open device
else:
    print('No device found')

def pico_rel_move(axis,steps):
    obj.RelativeMove(keys[0],axis,steps)
    
print('######################\nTo move picomotor, type pico_rel_move(axis,steps).\ne.g. pico_rel_move(1,10) moves the first axis by 10 steps\npico_rel_move(1,-10) moves it by 10 steps the other way.\n######################')
    
