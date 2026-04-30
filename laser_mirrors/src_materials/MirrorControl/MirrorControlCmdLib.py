# -*- coding: utf-8 -*-

import clr
import sys
import configparser
from time import sleep

clr.AddReference('System')
import System

class MCCmdLib:

    def __init__(self):
        self._Error_Queue = []
        self.__cfg = configparser.ConfigParser()
        self.__cfg.read("config.ini")
        try:
            self.__SN_M1 = self.__cfg['DEFAULT']['SN_mirror_1']
        except KeyError:
            print('INI file or SN_motor_1 key not found, using default')
            self.__SN_M1 = '8742 36821'
        try:
            self.__SN_M2 = self.__cfg['DEFAULT']['SN_mirror_2']
        except KeyError:
            print('INI file or SN_motor_2 key not found, using default')
            self.__SN_M2 = '8742 13798'
        try:
            self.__SN_HWP = self.__cfg['DEFAULT']['SN_HWP']
        except KeyError:
            print('INI file or SN_HWP key not found, using default')
            self.__SN_HWP = '8742 36821'
        try:
            self.__Ax_M1X = int(self.__cfg['DEFAULT']['axis_mirror_1X'])
        except KeyError:
            print('INI file or axis_motor_1X key not found, using default')
            self.__Ax_M1X = 3
        try:
            self.__Ax_M1Y = int(self.__cfg['DEFAULT']['axis_mirror_1Y'])
        except KeyError:
            print('INI file or axis_motor_1Y key not found, using default')
            self.__Ax_M1Y = 4
        try:
            self.__Ax_M2X = int(self.__cfg['DEFAULT']['axis_mirror_2X'])
        except KeyError:
            print('INI file or axis_motor_2X key not found, using default')
            self.__Ax_M2X = 1
        try:
            self.__Ax_M2Y = int(self.__cfg['DEFAULT']['axis_mirror_2Y'])
        except KeyError:
            print('INI file or axis_motor_2Y key not found, using default')
            self.__Ax_M2Y = 2
        try:
            self.__Ax_HWP1 = int(self.__cfg['DEFAULT']['axis_HWP_1'])
        except KeyError:
            print('INI file or axis_HWP_1 key not found, using default')
            self.__Ax_HWP1 = 1
        try:
            self.__Ax_HWP2 = int(self.__cfg['DEFAULT']['axis_HWP_2'])
        except KeyError:
            print('INI file or axis_HWP_2 key not found, using default')
            self.__Ax_HWP2 = 2
        
        try:
            CmdLibPath = self.__cfg['DEFAULT']['path_to_CmdLib']
            CmdLibPath = str.replace(CmdLibPath, '\\', '\\\\')
            # Replace \ with \\ (\ would start escape sequence) (has to be escaped here, too)
        except KeyError:
            print('INI file or path_to_CmdLib key not found, trying default')
            CmdLibPath = 'C:\\Program Files\\New Focus\\New Focus Picomotor Application\\Samples'
            
        sys.path.append(CmdLibPath) 
        
        try:
            clr.AddReference('CmdLib')
        except: #if "AddReference" fails, it throws "FileNotFoundException" which I cannot find
            raise ModuleNotFoundError('Connection to Picomotor CmdLib failed, path in config.ini incorrect?')
            
        print('Import...')
        from NewFocus import Picomotor
            
        print('Searching for Picomotor controllers...')
        self._ctrl = Picomotor.CmdLib8742(False, 3000)
        print('Waiting for device discovery...')
        sleep(1)
        keys = self._ctrl.GetDeviceKeys()
        print('\nFound the following controllers:')
        
        self.__Key_M1 = None
        self.__Key_M2 = None
        self.__Key_HWP = None
        
        if keys is not None:
            found1 = False
            found2 = False
            foundHWP = False
            for key in keys:
                print(key)
                sn = self._ctrl.GetModelSerial(key)
                print(sn)
                if sn == self.__SN_M1:
                    found1=True
                    self.__Key_M1 = key
                    print('found controller for mirror 1:', self.__SN_M1)
                    if "8743" in self.__SN_M1:      # if controller is type 8743 (with closed loop encoder)
                        self._ctrl.Open(self.__Key_M1)
                        IntVar = System.Int32(0)
                        succ1, addr1 = self._ctrl.GetDeviceAddress(self.__Key_M1, IntVar)
                        if succ1:                   # set Closed Loop Units to encoder counts (1):
                            succAx1 = self._ctrl.SetCLUnits(self.__Key_M1, addr1, self.__Ax_M1X, 1)
                            succAx2 = self._ctrl.SetCLUnits(self.__Key_M1, addr1, self.__Ax_M1Y, 1)
                        self._ctrl.Close(self.__Key_M1)
                        if succ1 and succAx1 and succAx2:
                            print("Setting M1 controller CLUnits to encoder counts successful")
                        else:
                            print("Warning: Setting M1 controller CLUnits to encoder counts NOT successful")
                if sn == self.__SN_M2:
                    found2=True
                    self.__Key_M2 = key
                    print('found controller for mirror 2:', self.__SN_M2)
                    if "8743" in self.__SN_M2:      # if controller is type 8743 (with closed loop encoder)
                        self._ctrl.Open(self.__Key_M2)
                        IntVar = System.Int32(0)
                        succ2, addr2 = self._ctrl.GetDeviceAddress(self.__Key_M2, IntVar)
                        if succ2:                   # set Closed Loop Units to encoder counts (1):
                            succAx1 = self._ctrl.SetCLUnits(self.__Key_M2, addr2, self.__Ax_M2X, 1)
                            succAx2 = self._ctrl.SetCLUnits(self.__Key_M2, addr2, self.__Ax_M2Y, 1)
                        self._ctrl.Close(self.__Key_M2)
                        if succ2 and succAx1 and succAx2:
                            print("Setting M2 controller CLUnits to encoder counts successful")
                        else:
                            print("Warning: Setting M2 controller CLUnits to encoder counts NOT successful")
                if sn == self.__SN_HWP:
                    foundHWP = True
                    self.__Key_HWP = key
                    print('found controller for HWPs:', self.__SN_HWP)
            print()
            if not (found1 and found2):
                self._ctrl.Shutdown()
                if not found1 and not found2:
                    mtext = 'both mirrors'
                elif not found1:
                    mtext = 'mirror 1'
                elif not found2:
                    mtext = 'mirror 2'
                raise RuntimeError('Expected controller for %s not found!' % mtext, keys)
            if not foundHWP:
                print('Expected controller for HWPs not found. Program will continue without HWP functionality.')
                
        else:
            print('(None)\n')
            self._ctrl.Shutdown()
            raise RuntimeError('No controllers found!')
    
    def get_HWPs_found(self):
        return self.__Key_HWP is not None
    
    def key_and_axis(self, mirror1=True, axis=0):
        if mirror1:
            key = self.__Key_M1
            if not axis: # axis == 0 -> X
                axis = self.__Ax_M1X
            else:
                axis = self.__Ax_M1Y
        else:
            key = self.__Key_M2
            if not axis:
                axis = self.__Ax_M2X
            else:
                axis = self.__Ax_M2Y
        
        return key, axis
            
    def GetMotionDone(self, axis=0):
        key1, axis1 = self.key_and_axis(True, axis)
        key2, axis2 = self.key_and_axis(False, axis)
        BoolVar = System.Boolean(0)
        self._ctrl.Open(key1) # we can only talk to one controller at a time and have to use Open() and Close() when communicating over Ethernet
        succ1, done1 = self._ctrl.GetMotionDone(key1, axis1, BoolVar)
        self._ctrl.Close(key1)
        self._ctrl.Open(key2)
        succ2, done2 = self._ctrl.GetMotionDone(key2, axis2, BoolVar)
        self._ctrl.Close(key2)
        if not succ1 and not succ2:
            raise RuntimeWarning(False, 0, axis, 'GetMotionDone')
        if not succ1:
            raise RuntimeWarning(False, 1, axis, 'GetMotionDone')
        if not succ2:
            raise RuntimeWarning(False, 2, axis, 'GetMotionDone')
        return done1, done2
    
    def GetMotionDone_HWPs(self):
        BoolVar = System.Boolean(0)
        self._ctrl.Open(self.__Key_HWP) # we can only talk to one controller at a time and have to use Open() and Close() when communicating over Ethernet
        succ1, done1 = self._ctrl.GetMotionDone(self.__Key_HWP, self.__Ax_HWP1, BoolVar)
        succ2, done2 = self._ctrl.GetMotionDone(self.__Key_HWP, self.__Ax_HWP2, BoolVar)
        self._ctrl.Close(self.__Key_HWP)
        if not succ1 and not succ2:
            raise RuntimeWarning(False, 0, 'GetMotionDone_HWPs')
        if not succ1:
            raise RuntimeWarning(False, 1, 'GetMotionDone_HWPs')
        if not succ2:
            raise RuntimeWarning(False, 2, 'GetMotionDone_HWPs')
        return done1, done2
    
    def GetPosition(self, axis=0):
        key1, axis1 = self.key_and_axis(True, axis)
        key2, axis2 = self.key_and_axis(False, axis)
        IntVar = System.Int32(0)
        self._ctrl.Open(key1)
        succ1, pos1 = self._ctrl.GetPosition(key1, axis1, IntVar)
        self._ctrl.Close(key1)
        self._ctrl.Open(key2)
        succ2, pos2 = self._ctrl.GetPosition(key2, axis2, IntVar)
        self._ctrl.Close(key2)
        if not succ1 and not succ2:
            raise RuntimeWarning(False, 0, axis, 'GetPosition')
        if not succ1:
            raise RuntimeWarning(False, 1, axis, 'GetPosition')
        if not succ2:
            raise RuntimeWarning(False, 2, axis, 'GetPosition')
        return pos1, pos2
    
    def GetPosition_HWPs(self):
        IntVar = System.Int32(0)
        self._ctrl.Open(self.__Key_HWP)
        succ1, pos1 = self._ctrl.GetPosition(self.__Key_HWP, self.__Ax_HWP1, IntVar)
        succ2, pos2 = self._ctrl.GetPosition(self.__Key_HWP, self.__Ax_HWP2, IntVar)
        self._ctrl.Close(self.__Key_HWP)
        if not succ1 and not succ2:
            raise RuntimeWarning(False, 0, 'GetPosition_HWPs')
        if not succ1:
            raise RuntimeWarning(False, 1, 'GetPosition_HWPs')
        if not succ2:
            raise RuntimeWarning(False, 2, 'GetPosition_HWPs')
        return pos1, pos2
    
    def RelativeMove(self, steps1, steps2, axis=0):
        key1, axis1 = self.key_and_axis(True, axis)
        key2, axis2 = self.key_and_axis(False, axis)
        
        succ1 = True
        succ2 = True
        
        if steps1 != 0:
            self._ctrl.Open(key1)
            succ1 = self._ctrl.RelativeMove(key1, axis1, steps1)
            self._ctrl.Close(key1)
        
        if steps2 != 0:
            self._ctrl.Open(key2)
            succ2 = self._ctrl.RelativeMove(key2, axis2, steps2)
            self._ctrl.Close(key2)
        
        if not succ1 and not succ2:
            raise RuntimeWarning(True, 0, axis, 'RelativeMove')
        if not succ1:
            raise RuntimeWarning(True, 1, axis, 'RelativeMove')
        if not succ2:
            raise RuntimeWarning(True, 2, axis, 'RelativeMove')
            
    def RelativeMove_HWPs(self, steps1, steps2):
        
        succ1 = True
        succ2 = True
        
        if steps1 != 0:
            self._ctrl.Open(self.__Key_HWP)
            succ1 = self._ctrl.RelativeMove(self.__Key_HWP, self.__Ax_HWP1, steps1)
            self._ctrl.Close(self.__Key_HWP)
        
        if steps2 != 0:
            self._ctrl.Open(self.__Key_HWP)
            succ2 = self._ctrl.RelativeMove(self.__Key_HWP, self.__Ax_HWP2, steps2)
            self._ctrl.Close(self.__Key_HWP)
        
        if not succ1 and not succ2:
            raise RuntimeWarning(True, 0, 'RelativeMove_HWPs')
        if not succ1:
            raise RuntimeWarning(True, 1, 'RelativeMove_HWPs')
        if not succ2:
            raise RuntimeWarning(True, 2, 'RelativeMove_HWPs')
    
    def read_errors(self):
        StrVar = System.String('')
        self._ctrl.Open(self.__Key_M1)
        succ1, errormsg1 = self._ctrl.GetErrorMsg(self.__Key_M1, StrVar)
        self._ctrl.Close(self.__Key_M1)
        if self.__Key_M1 != self.__Key_M2:
            self._ctrl.Open(self.__Key_M2)
            succ2, errormsg2 = self._ctrl.GetErrorMsg(self.__Key_M2, StrVar)
            self._ctrl.Close(self.__Key_M2)
        else:
            succ2 = succ1
            errormsg2 = errormsg1
            
        if self.__Key_HWP is not None:
            if self.__Key_HWP == self.__Key_M1:
                succHWP = succ1
                errormsgHWP = errormsg1
            elif self.__Key_HWP == self.__Key_M2:
                succHWP = succ2
                errormsgHWP = errormsg2
            else:
                self._ctrl.Open(self.__Key_HWP)
                succHWP, errormsgHWP = self._ctrl.GetErrorMsg(self.__Key_HWP, StrVar)
                self._ctrl.Close(self.__Key_HWP)
        else:
            succHWP = True
            errormsgHWP = ''                
        
        error1 = not (errormsg1 == '' or errormsg1 == '0, NO ERROR DETECTED')
        error2 = not (errormsg2 == '' or errormsg2 == '0, NO ERROR DETECTED')
        errorHWP = not (errormsgHWP == '' or errormsgHWP == '0, NO ERROR DETECTED')
        
        if succ1 and error1:
            self._Error_Queue.append([1, errormsg1])
        if succ2 and error2:
            self._Error_Queue.append([2, errormsg2])
        if succHWP and errorHWP:
            self._Error_Queue.append([0, errormsgHWP])
        
        if not succ1 and not succ2:
            raise RuntimeWarning(False, 0, -1, 'GetErrorMsg')
        if not succ1:
            raise RuntimeWarning(False, 1, -1, 'GetErrorMsg')
        if not succ2:
            raise RuntimeWarning(False, 2, -1, 'GetErrorMsg')
    
    def check_for_errors(self, axis=0):
        self.read_errors()
        key1, axis1 = self.key_and_axis(True, axis)
        key2, axis2 = self.key_and_axis(False, axis)
        
        errorlist = []
        
        for Q, i in zip(self._Error_Queue, range(len(self._Error_Queue))):
            
            ctrlnum = Q[0]
            message = Q[1]
            axnum = self._get_axnum_from_errormsg(message)
            
            if ctrlnum == 1:
                relevant_error = (axnum == axis1 or axnum == 0) # axnum == 0 means there is a general controller error (axis independent)
            elif ctrlnum == 2:
                relevant_error = (axnum == axis2 or axnum == 0)
            else:
                relevant_error = False
                
            if relevant_error:
                del self._Error_Queue[i] # we are now handling this error, delete it from queue
                errorlist.append(Q)            
        
        if len(errorlist)>0:
            raise RuntimeError(*errorlist)
    
    def check_for_errors_HWPs(self):
        self.read_errors()
        
        errorlist = []
        
        for Q, i in zip(self._Error_Queue, range(len(self._Error_Queue))):
            
            ctrlnum = Q[0]
            message = Q[1]
            axnum = self._get_axnum_from_errormsg(message)
            
            if ctrlnum == 0:
                relevant_error = (axnum == self.__Ax_HWP1 or axnum == self.__Ax_HWP2 or axnum == 0) # axnum == 0 means there is a general controller error (axis independent)
            else:
                relevant_error = False
                
            if relevant_error:
                del self._Error_Queue[i] # we are now handling this error, delete it from queue
                errorlist.append(Q)            
        
        if len(errorlist)>0:
            raise RuntimeError(*errorlist)
    
    def _get_axnum_from_errormsg(self, errormsg):
        index = errormsg.find(',')
        errornum = int(errormsg[:index])
        axnum = errornum//100
        return axnum
        
    def Shutdown(self):
        self._ctrl.Shutdown()
