# -*- coding: utf-8 -*-

#import clr
#import sys
#import configparser

#clr.AddReference('System')
#import System

class MCCmdLib:

    def __init__(self):
#        self.__cfg = configparser.ConfigParser()
#        self.__cfg.read("config.ini")
#        try:
#            self.__SN_M1 = self.__cfg['DEFAULT']['SN_motor_1']
#        except KeyError:
#            print('INI file or SN_motor_1 key not found, using default')
#            self.__SN_M1 = '8742 36821'
#        try:
#            self.__SN_M2 = self.__cfg['DEFAULT']['SN_motor_2']
#        except KeyError:
#            print('INI file or SN_motor_2 key not found, using default')
#            self.__SN_M2 = '8742 13798'
#        try:
#            self.__Ax_M1X = int(self.__cfg['DEFAULT']['axis_motor_1X'])
#        except KeyError:
#            print('INI file or axis_motor_1X key not found, using default')
#            self.__Ax_M1X = 3
#        try:
#            self.__Ax_M1Y = int(self.__cfg['DEFAULT']['axis_motor_1Y'])
#        except KeyError:
#            print('INI file or axis_motor_1Y key not found, using default')
#            self.__Ax_M1Y = 4
#        try:
#            self.__Ax_M2X = int(self.__cfg['DEFAULT']['axis_motor_2X'])
#        except KeyError:
#            print('INI file or axis_motor_2X key not found, using default')
#            self.__Ax_M2X = 1
#        try:
#            self.__Ax_M2Y = int(self.__cfg['DEFAULT']['axis_motor_2Y'])
#        except KeyError:
#            print('INI file or axis_motor_2Y key not found, using default')
#            self.__Ax_M2Y = 2
#        
#        try:
#            CmdLibPath = self.__cfg['DEFAULT']['path_to_CmdLib']
#            CmdLibPath = str.replace(CmdLibPath, '\\', '\\\\')
#            # Replace \ with \\ (\ would start escape sequence) (has to be escaped here, too)
#        except KeyError:
#            print('INI file or path_to_CmdLib key not found, trying default')
#            CmdLibPath = 'C:\\Program Files\\New Focus\\New Focus Picomotor Application\\Samples'
#            
#        sys.path.append(CmdLibPath) 
#        
#        try:
#            clr.AddReference('CmdLib')
#        except:
#            raise ModuleNotFoundError('Connection to Picomotor CmdLib failed, path in config.ini incorrect?')
#            
#        print('Import...')
#        from NewFocus import Picomotor
#            
#        print('Searching for Picomotor controllers...')
#        self._ctrl = Picomotor.CmdLib8742(False, 3000)
#        keys = self._ctrl.GetDeviceKeys()
#        print('\nFound the following controllers:')
#        if keys is not None:
#            found1 = False
#            found2 = False
#            for key in keys:
#                print(key)
#                sn = self._ctrl.GetModelSerial(key)
#                print(sn)
#                if sn == self.__SN_M1:
#                    found1=True
#                    self.__Key_M1 = key
#                    print('found Controller', self.__SN_M1)
#                elif sn == self.__SN_M2:
#                    found2=True
#                    self.__Key_M2 = key
#                    print('found Controller', self.__SN_M2)
#            print()
#            if not (found1 and found2):
#                self._ctrl.Shutdown()
#                raise RuntimeError('Expected controllers not found!', keys)
#        else:
#            print('(None)\n')
#            self._ctrl.Shutdown()
#            raise RuntimeError('No controllers found!')
        self.__pos1 = [0,0]
        self.__pos2 = [0,0]
        self.__posHWPs = [0,0]
        print('Demo init of MirrorControlCmdLib')
    
#    def key_and_axis(self, mirror1=True, axisX=True):
#        if mirror1:
#            key = self.__Key_M1
#            if axisX:
#                axis = self.__Ax_M1X
#            else:
#                axis = self.__Ax_M1Y
#        else:
#            key = self.__Key_M2
#            if axisX:
#                axis = self.__Ax_M2X
#            else:
#                axis = self.__Ax_M2Y
#        
#        return key, axis
    
    def check_for_errors(self, axis=0):
        pass # we have no errors
    
    def check_for_errors_HWPs(self):
        pass # we have no errors
        
    def get_HWPs_found(self):
        return True # we have HWPs.
    
    def GetMotionDone(self, axis=0):
#        key1, axis1 = self.key_and_axis(True, axis==0)
#        key2, axis2 = self.key_and_axis(False, axis==0)
#        BoolVar = System.Boolean(0)
#        succ1, done1 = self._ctrl.GetMotionDone(key1, axis1, BoolVar)
#        succ2, done2 = self._ctrl.GetMotionDone(key2, axis2, BoolVar)
#        if not succ1:
#            raise ConnectionError(1, axis, 'GetMotionDone')
#        if not succ1:
#            raise ConnectionError(2, axis, 'GetMotionDone')
#        return done1, done2
        print('Demo GetMotionDone...')
        print('...we are always done!')
        return True, True
    
    def GetMotionDone_HWPs(self):
#        key1, axis1 = self.key_and_axis(True, axis==0)
#        key2, axis2 = self.key_and_axis(False, axis==0)
#        BoolVar = System.Boolean(0)
#        succ1, done1 = self._ctrl.GetMotionDone(key1, axis1, BoolVar)
#        succ2, done2 = self._ctrl.GetMotionDone(key2, axis2, BoolVar)
#        if not succ1:
#            raise ConnectionError(1, axis, 'GetMotionDone')
#        if not succ1:
#            raise ConnectionError(2, axis, 'GetMotionDone')
#        return done1, done2
        print('Demo GetMotionDone_HWPs...')
        print('...we are always done!')
        return True, True
    
    def GetPosition(self, axis=0):
#        key1, axis1 = self.key_and_axis(True, axis==0)
#        key2, axis2 = self.key_and_axis(False, axis==0)
#        IntVar = System.Int32(0)
#        succ1, pos1 = self._ctrl.GetPosition(key1, axis1, IntVar)
#        succ2, pos2 = self._ctrl.GetPosition(key2, axis2, IntVar)
#        if not succ1:
#            raise ConnectionError(1, axis, 'GetPosition')
#        if not succ1:
#            raise ConnectionError(2, axis, 'GetPosition')
        print('Demo GetPosition...')
        xy = 'X' if axis else 'Y'
        print('...Position Mirror 1 (%s): %d' % (xy, self.__pos1[axis]))
        print('...Position Mirror 2 (%s): %d' % (xy, self.__pos2[axis]))
        return self.__pos1[axis], self.__pos2[axis]
    
    def GetPosition_HWPs(self):
#        key1, axis1 = self.key_and_axis(True, axis==0)
#        key2, axis2 = self.key_and_axis(False, axis==0)
#        IntVar = System.Int32(0)
#        succ1, pos1 = self._ctrl.GetPosition(key1, axis1, IntVar)
#        succ2, pos2 = self._ctrl.GetPosition(key2, axis2, IntVar)
#        if not succ1:
#            raise ConnectionError(1, axis, 'GetPosition')
#        if not succ1:
#            raise ConnectionError(2, axis, 'GetPosition')
        print('Demo GetPosition_HWPs...')
        print('...Position HWP 1: %d' % self.__posHWPs[0])
        print('...Position HWP 2: %d' % self.__posHWPs[1])
        return self.__posHWPs[0], self.__posHWPs[1]
    
    def RelativeMove(self, steps1, steps2, axis=0):
#        key1, axis1 = self.key_and_axis(True, axis==0)
#        key2, axis2 = self.key_and_axis(False, axis==0)
#        succ1 = self._ctrl.RelativeMove(key1, axis1, steps1)
#        succ2 = self._ctrl.RelativeMove(key2, axis2, steps2)
#        if not succ1:
#            raise ConnectionError(1, axis, 'RelativeMove')
#        if not succ2:
#            raise ConnectionError(2, axis, 'RelativeMove')
        print('Demo RelativeMove...')
        xy = 'X' if axis else 'Y'
        print('...Moving Mirror 1 (%s) by %d steps' % (xy, steps1))
        print('...Moving Mirror 2 (%s) by %d steps' % (xy, steps2))
        self.__pos1[axis] += steps1
        self.__pos2[axis] += steps2
        
    def RelativeMove_HWPs(self, steps1, steps2):
#        key1, axis1 = self.key_and_axis(True, axis==0)
#        key2, axis2 = self.key_and_axis(False, axis==0)
#        succ1 = self._ctrl.RelativeMove(key1, axis1, steps1)
#        succ2 = self._ctrl.RelativeMove(key2, axis2, steps2)
#        if not succ1:
#            raise ConnectionError(1, axis, 'RelativeMove')
#        if not succ2:
#            raise ConnectionError(2, axis, 'RelativeMove')
        print('Demo RelativeMove_HWPs...')
        print('...Moving HWP 1 by %d steps' % steps1)
        print('...Moving HWP 2 by %d steps' % steps2)
        self.__posHWPs[0] += steps1
        self.__posHWPs[1] += steps2
    
    def Shutdown(self):
#        self._ctrl.Shutdown()
        print('Demo Shutdown')
