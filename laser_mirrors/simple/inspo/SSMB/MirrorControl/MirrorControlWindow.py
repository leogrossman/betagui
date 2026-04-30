# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import messagebox
import MirrorControlCalculate as Calculate
#import MirrorControlCmdLib as CmdLib
import MirrorControlCmdLibDemo as CmdLib
import configparser
from time import sleep

class Window(tk.Frame):
    
    def __init__(self, master=None):
        self.cmd = None
        self.calc = Calculate.MCcalc()
                
        tk.Frame.__init__(self, master)
        self.master = master
        self.master.title('SSMB Laser Position Control')
        
        self.__OffsetXScl = tk.Scale(self.master, label='Vertical offset (mm)', from_=-10, to=10,
                              orient=tk.HORIZONTAL, length=400, showvalue=1 ,tickinterval=2,
                              resolution=0.01, command=self.__calib_X)
        self.__OffsetXScl.grid(row=1, column = 0, rowspan=2, columnspan=6)

        self.__ZeroOffsetXBtn = tk.Button(self.master, text='go to zero', command=self.__zero_offset_X)
        self.__ZeroOffsetXBtn.grid(row=2, column=7, sticky=tk.NW)

#        self.__toggleResOXBtn = tk.Button(self.master, text='Toggle resolution', command=self.toggle_resolution)
#        self.__toggleResOXBtn.grid(row=1, column = 0)

        self.__OffsetXLbl = tk.Label(self.master, text = 'readback')
        self.__OffsetXLbl.grid(row=1, column=6, sticky=tk.SW)
        self.__OffsetXActual = tk.DoubleVar(self.master)
        self.__OffsetXEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__OffsetXActual,
                                     bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__OffsetXEtr.grid(row=2, column=6, sticky=tk.NW, padx=5)
        
        self.__OffsetYScl = tk.Scale(self.master, label='Horizontal offset (mm)', from_=-10, to=10,
                              orient=tk.HORIZONTAL, length=400, showvalue=1 ,tickinterval=2,
                              resolution=0.01, command=self.__calib_Y)
        self.__OffsetYScl.grid(row=1, column = 9, rowspan=2, columnspan=6)
        
        self.__ZeroOffsetYBtn = tk.Button(self.master, text='go to zero', command=self.__zero_offset_Y)
        self.__ZeroOffsetYBtn.grid(row=2, column=16, sticky=tk.NW)
        
        self.__OffsetYLbl = tk.Label(self.master, text = 'readback')
        self.__OffsetYLbl.grid(row=1, column=15, sticky=tk.SW)
        self.__OffsetYActual = tk.DoubleVar(self.master)
        self.__OffsetYEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__OffsetYActual,
                                     bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__OffsetYEtr.grid(row=2, column=15, sticky=tk.NW, padx=5)

        self.__AngleXScl = tk.Scale(self.master, label='Vertical angle (µrad)', from_=-2000, to=2000,
                             orient=tk.HORIZONTAL, length=400, showvalue=1 ,tickinterval=500,
                             resolution=1, command=self.__calib_X)
        self.__AngleXScl.grid(row=3, column = 0, rowspan=2, columnspan=6)
        
        self.__ZeroAngleXBtn = tk.Button(self.master, text='go to zero', command=self.__zero_angle_X)
        self.__ZeroAngleXBtn.grid(row=4, column=7, sticky=tk.NW)

        self.__AngleXLbl = tk.Label(self.master, text = 'readback')
        self.__AngleXLbl.grid(row=3, column=6, sticky=tk.SW)
        self.__AngleXActual = tk.DoubleVar(self.master)
        self.__AngleXEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__AngleXActual,
                                    bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__AngleXEtr.grid(row=4, column=6, sticky=tk.NW, padx=5)

        self.__AngleYScl = tk.Scale(self.master, label='Horizontal angle (µrad)', from_=-2000, to=2000,
                             orient=tk.HORIZONTAL, length=400, showvalue=1 ,tickinterval=500,
                             resolution=1, command=self.__calib_Y)
        self.__AngleYScl.grid(row=3, column = 9, rowspan=2, columnspan=6)
        
        self.__ZeroAngleYBtn = tk.Button(self.master, text='go to zero', command=self.__zero_angle_Y)
        self.__ZeroAngleYBtn.grid(row=4, column=16, sticky=tk.NW)

        self.__AngleYLbl = tk.Label(self.master, text = 'readback')
        self.__AngleYLbl.grid(row=3, column=15, sticky=tk.SW)
        self.__AngleYActual = tk.DoubleVar(self.master)
        self.__AngleYEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__AngleYActual,
                                    bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__AngleYEtr.grid(row=4, column=15, sticky=tk.NW, padx=5)

        self.__AngleM1XLbl = tk.Label(self.master, text = 'Mirror 1:\nVertical Angle (µrad)')
        self.__AngleM1XLbl.grid(row=5, column=0, sticky=tk.S, columnspan=3)
        self.__AngleM1X = tk.DoubleVar(self.master)
        self.__AngleM1XEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__AngleM1X,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__AngleM1XEtr.grid(row=6, column=1, sticky=tk.N, padx=5)
        
        self.__AngleM2XLbl = tk.Label(self.master, text = 'Mirror 2:\nVertical Angle (µrad)')
        self.__AngleM2XLbl.grid(row=5, column=3, sticky=tk.S, columnspan=3)
        self.__AngleM2X = tk.DoubleVar(self.master)
        self.__AngleM2XEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__AngleM2X,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__AngleM2XEtr.grid(row=6, column=4, sticky=tk.N, padx=5)

        self.__AngleM1YLbl = tk.Label(self.master, text = 'Mirror 1:\nHorizontal Angle (µrad)')
        self.__AngleM1YLbl.grid(row=5, column=9, sticky=tk.S, columnspan=3)
        self.__AngleM1Y = tk.DoubleVar(self.master)
        self.__AngleM1YEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__AngleM1Y,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__AngleM1YEtr.grid(row=6, column=10, sticky=tk.N, padx=5)
        
        self.__AngleM2YLbl = tk.Label(self.master, text = 'Mirror 2:\nHorizontal Angle (µrad)')
        self.__AngleM2YLbl.grid(row=5, column=12, sticky=tk.S, columnspan=3)
        self.__AngleM2Y = tk.DoubleVar(self.master)
        self.__AngleM2YEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__AngleM2Y,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__AngleM2YEtr.grid(row=6, column=13, sticky=tk.N, padx=5)
        
        
        self.__StepsM1XLbl = tk.Label(self.master, text = 'Mirror 1:\nVertical Steps')
        self.__StepsM1XLbl.grid(row=7, column=0, sticky=tk.S, columnspan=3)
        self.__StepsM1X = tk.DoubleVar(self.master)
        self.__StepsM1XEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__StepsM1X,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__StepsM1XEtr.grid(row=8, column=1, sticky=tk.N, padx=5)
        
        self.__StepsM2XLbl = tk.Label(self.master, text = 'Mirror 2:\nVertical Steps')
        self.__StepsM2XLbl.grid(row=7, column=3, sticky=tk.S, columnspan=3)
        self.__StepsM2X = tk.DoubleVar(self.master)
        self.__StepsM2XEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__StepsM2X,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__StepsM2XEtr.grid(row=8, column=4, sticky=tk.N, padx=5)

        self.__StepsM1YLbl = tk.Label(self.master, text = 'Mirror 1:\nHorizontal Steps')
        self.__StepsM1YLbl.grid(row=7, column=9, sticky=tk.S, columnspan=3)
        self.__StepsM1Y = tk.DoubleVar(self.master)
        self.__StepsM1YEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__StepsM1Y,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__StepsM1YEtr.grid(row=8, column=10, sticky=tk.N, padx=5)
        
        self.__StepsM2YLbl = tk.Label(self.master, text = 'Mirror 2:\nHorizontal Steps')
        self.__StepsM2YLbl.grid(row=7, column=12, sticky=tk.S, columnspan=3)
        self.__StepsM2Y = tk.DoubleVar(self.master)
        self.__StepsM2YEtr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__StepsM2Y,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__StepsM2YEtr.grid(row=8, column=13, sticky=tk.N, padx=5)
        
        self.__SpacerLbl = tk.Label(self.master, width=10)
        self.__SpacerLbl.grid(row=1, column = 8)
        
        self.__StatusXLbl = tk.Label(self.master, width = 20, bg = 'white', fg = 'black', text = '')
        self.__StatusXLbl.grid(row = 6, column = 6, columnspan=2)
        
        self.__StatusYLbl = tk.Label(self.master, width = 20, bg = 'white', fg = 'black', text = '')
        self.__StatusYLbl.grid(row = 6, column = 15, columnspan=2)
        
        self.__StatusXResetBtn = tk.Button(self.master, text='Restart', command=self.__reset_state_X)
        self.__StatusXResetBtn.grid(row=7, column = 6, columnspan=2)
        self.__StatusXResetBtn.grid_remove()
        
        self.__StatusYResetBtn = tk.Button(self.master, text='Restart', command=self.__reset_state_Y)
        self.__StatusYResetBtn.grid(row=7, column = 15, columnspan=2)
        self.__StatusYResetBtn.grid_remove()
        
        self.__StopXBtn = tk.Button(self.master, text='Stop', command=self.__stop_motion_X)
        self.__StopXBtn.grid(row=7, column = 6, columnspan=2)
        self.__StopXBtn.grid_remove()
        
        self.__StopYBtn = tk.Button(self.master, text='Stop', command=self.__stop_motion_Y)
        self.__StopYBtn.grid(row=7, column = 15, columnspan=2)
        self.__StopYBtn.grid_remove()
        
        self.__CalibModeXBtn = tk.Button(self.master, text = 'Go to calibration mode', command=self.__toggle_calib_mode_X)
        self.__CalibModeXBtn.grid(row=8, column=6, columnspan=2)
        self.__CalibModeYBtn = tk.Button(self.master, text = 'Go to calibration mode', command=self.__toggle_calib_mode_Y)
        self.__CalibModeYBtn.grid(row=8, column=15, columnspan=2)
        
        self.__IncM1XBtn = tk.Button(self.master, text='-->', command=self.__inc_M1X)
        self.__IncM1XBtn.grid(row=8, column=2, sticky=tk.W)
        self.__IncM1XBtn.grid_remove()
        self.__DecM1XBtn = tk.Button(self.master, text='<--', command=self.__dec_M1X)
        self.__DecM1XBtn.grid(row=8, column=0, sticky=tk.E)
        self.__DecM1XBtn.grid_remove()
        
        self.__IncM2XBtn = tk.Button(self.master, text='-->', command=self.__inc_M2X)
        self.__IncM2XBtn.grid(row=8, column=5, sticky=tk.W)
        self.__IncM2XBtn.grid_remove()
        self.__DecM2XBtn = tk.Button(self.master, text='<--', command=self.__dec_M2X)
        self.__DecM2XBtn.grid(row=8, column=3, sticky=tk.E)
        self.__DecM2XBtn.grid_remove()
        
        self.__IncM1YBtn = tk.Button(self.master, text='-->', command=self.__inc_M1Y)
        self.__IncM1YBtn.grid(row=8, column=11, sticky=tk.W)
        self.__IncM1YBtn.grid_remove()
        self.__DecM1YBtn = tk.Button(self.master, text='<--', command=self.__dec_M1Y)
        self.__DecM1YBtn.grid(row=8, column=9, sticky=tk.E)
        self.__DecM1YBtn.grid_remove()
        
        self.__IncM2YBtn = tk.Button(self.master, text='-->', command=self.__inc_M2Y)
        self.__IncM2YBtn.grid(row=8, column=14, sticky=tk.W)
        self.__IncM2YBtn.grid_remove()
        self.__DecM2YBtn = tk.Button(self.master, text='<--', command=self.__dec_M2Y)
        self.__DecM2YBtn.grid(row=8, column=12, sticky=tk.E)
        self.__DecM2YBtn.grid_remove()
        
        
        self.__Stepsize = tk.IntVar(self.master, value=10)
        self.__StepsizeEtr = tk.Entry(self.master, width=10, textvariable=self.__Stepsize)
        self.__StepsizeEtr.grid(row=10, column=1)
        self.__StepsizeEtr.grid_remove()
        self.__StepsizeLbl = tk.Label(self.master, text='step size in calibration mode\n(for all axes and HWPs):')
        self.__StepsizeLbl.grid(row=9, column=0, columnspan=3, sticky=tk.S)
        self.__StepsizeLbl.grid_remove()
        
        
        self.__ToggleHWPsBtn = tk.Button(self.master, text='show HWP controls', command=self.__toggle_HWPs)
        self.__ToggleHWPsBtn.grid(row=9, column=3, columnspan=3, rowspan=2, pady=15)
        self.__ToggleHWPsBtn.grid_remove()
        
        
        self.__StepsHWP1Lbl = tk.Label(self.master, text = 'Steps HWP 1:')
        self.__StepsHWP1Lbl.grid(row=11, column=0, columnspan=3, sticky=tk.E)
        self.__StepsHWP1Lbl.grid_remove()
        self.__StepsHWP1 = tk.DoubleVar(self.master)
        self.__StepsHWP1Etr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__StepsHWP1,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__StepsHWP1Etr.grid(row=11, column=4, padx=5)
        self.__StepsHWP1Etr.grid_remove()
        
        self.__IncHWP1Btn = tk.Button(self.master, text='-->', command=self.__inc_HWP1)
        self.__IncHWP1Btn.grid(row=11, column=5, sticky=tk.W)
        self.__IncHWP1Btn.grid_remove()
        self.__DecHWP1Btn = tk.Button(self.master, text='<--', command=self.__dec_HWP1)
        self.__DecHWP1Btn.grid(row=11, column=3, sticky=tk.E)
        self.__DecHWP1Btn.grid_remove()
        
        self.__StepsHWP2Lbl = tk.Label(self.master, text = 'Steps HWP 2:', width=30, anchor='e')
        self.__StepsHWP2Lbl.grid(row=12, column=0, columnspan=3, sticky=tk.E)
        self.__StepsHWP2Lbl.grid_remove()
        self.__StepsHWP2 = tk.DoubleVar(self.master)
        self.__StepsHWP2Etr = tk.Label(self.master, width=10, anchor='e', textvariable = self.__StepsHWP2,
                                      bg='white', fg='black', relief = tk.SUNKEN, bd=1)
        self.__StepsHWP2Etr.grid(row=12, column=4, padx=5)
        self.__StepsHWP2Etr.grid_remove()
        
        self.__IncHWP2Btn = tk.Button(self.master, text='-->', command=self.__inc_HWP2)
        self.__IncHWP2Btn.grid(row=12, column=5, sticky=tk.W)
        self.__IncHWP2Btn.grid_remove()
        self.__DecHWP2Btn = tk.Button(self.master, text='<--', command=self.__dec_HWP2)
        self.__DecHWP2Btn.grid(row=12, column=3, sticky=tk.E)
        self.__DecHWP2Btn.grid_remove()
        
        
        
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.__yellow = 'yellow2'
        self.__red = 'red3'
        self.__green = 'green3'
        self.__blue = 'dodger blue'
        self.__orange = 'orange2'
        
        self.state = [0,0] # 0: idle, 1: moving, 2: read error (retry), 3: write error (retry), 4: controller error (retry)
                           # ..-1: calib mode,   5: read error (stop),  6: write error (stop),  7: controller error (stop)
                           # 8..: stopped by user
                           # one each for X and Y axes
        self.state_HWP = False # Control active or inactive (similar to mirror calib mode)
        
        self.angle_state_1 = [0,0] # actual angular positions of mirror 1 axes (X, Y) (microrad)
        self.angle_state_2 = [0,0] # actual angular positions of mirror 2 axes (X, Y) (microrad)
        
        self.step_pos_1 = [0,0]
        self.step_pos_2 = [0,0]
        self.step_pos_HWPs = [0,0]
        #will be set in startup()
        
        self._conf = configparser.ConfigParser()
        self._conf.read("mirror_state.ini")
        
        try:
            offsetX = float(self._conf["last_known"]["OffsetX"])
            angleX  = float(self._conf["last_known"]["AngleX"])
            offsetY = float(self._conf["last_known"]["OffsetY"])
            angleY  = float(self._conf["last_known"]["AngleY"])
            
            self.angle_state_1[0], self.angle_state_2[0] = self.calc.to_mirror_angles(offsetX, angleX, 0)
            self.angle_state_1[1], self.angle_state_2[1] = self.calc.to_mirror_angles(offsetY, angleY, 1)
            
            self.__OffsetXScl.set(offsetX)
            self.__AngleXScl.set(angleX)
            self.__OffsetYScl.set(offsetY)
            self.__AngleYScl.set(angleY)
            self._update_displays(axis=0)
            self._update_displays(axis=1)
            
            
            offsetXset = float(self._conf["last_set"]["OffsetX"])
            angleXset  = float(self._conf["last_set"]["AngleX"])
            offsetYset = float(self._conf["last_set"]["OffsetY"])
            angleYset  = float(self._conf["last_set"]["AngleY"])
            
            self.__OffsetXScl.set(offsetXset)
            self.__AngleXScl.set(angleXset)
            self.__OffsetYScl.set(offsetYset)
            self.__AngleYScl.set(angleYset)
            
        except (KeyError, ValueError):
            print('Failed to read last known mirror positions from file "mirror_state.ini", starting with 0')
            self.angle_state_1 = [0,0]
            self.angle_state_2 = [0,0]
            try:
                self._conf.add_section("last_known")
            except configparser.DuplicateSectionError:
                print('Section "last_known" exists, maybe wrong keys or corrupt values?')
            try:
                self._conf.add_section("last_set")
            except configparser.DuplicateSectionError:
                print('Section "last_set" exists, maybe wrong keys or corrupt values?')
        
        self.max_steps_per_cycle = 25
        self.cycle_period = 250 # ms
        
        
    def startup(self):
        try:
            
            self.__StatusXLbl.configure(bg=self.__yellow, text = 'searching controllers...')
            self.__StatusYLbl.configure(bg=self.__yellow, text = 'searching controllers...')
            self.master.update_idletasks()
            self.cmd = CmdLib.MCCmdLib()
            print('startup!')
            self._save_all_current_mirror_steps()
            self._update_displays(axis=0)
            self._update_displays(axis=1)
            self._save_current_HWP_steps()
            self._update_HWP_displays()
            self.__StatusXLbl.configure(bg=self.__green, text = 'ready!')
            self.__StatusYLbl.configure(bg=self.__green, text = 'ready!')
            self.master.after(int(self.cycle_period), self.control_cycle, 0) # start control loop for X-axis
            self.master.after(int(self.cycle_period * 1.5), self.control_cycle, 1) # start control loop for Y-axis
            if self.cmd.get_HWPs_found(): # start control cycle for HWPs if HWPs have been found
                self._save_current_HWP_steps()
                self._update_HWP_displays()
                self.__ToggleHWPsBtn.grid()
                self.master.after(int(self.cycle_period * 1.25), self.control_cycle_HWPs)
            
        except ModuleNotFoundError as e:
            self.__StatusXLbl.configure(bg=self.__red, text = 'interface error')
            self.__StatusYLbl.configure(bg=self.__red, text = 'interface error')
            if messagebox.askretrycancel('Software Interface failed', e.args[0]):
                self.master.after(int(self.cycle_period), self.startup)
            else:
                self.master.destroy()
                
        except RuntimeError as e:
            self.__StatusXLbl.configure(bg=self.__red, text = 'connection error')
            self.__StatusYLbl.configure(bg=self.__red, text = 'connection error')
            if messagebox.askretrycancel('Connection to controllers failed', e.args[0]):
                self.master.after(int(self.cycle_period), self.startup)
            else:
                self.master.destroy()
                
        except RuntimeWarning: # save_current_mirror_steps failed, try again once after a delay
            self.__StatusXLbl.configure(bg=self.__orange, text = 'communication error')
            self.__StatusYLbl.configure(bg=self.__orange, text = 'communication error')
            sleep(0.5)
            try:
                self._save_all_current_mirror_steps()
                self._update_displays(axis=0)
                self._update_displays(axis=1)
                self.__StatusXLbl.configure(bg=self.__green, text = 'ready!')
                self.__StatusYLbl.configure(bg=self.__green, text = 'ready!')
                self.master.after(int(self.cycle_period), self.control_cycle, 0) # start control loop for X-axis
                self.master.after(int(self.cycle_period * 1.5), self.control_cycle, 1) # start control loop for Y-axis
            except RuntimeWarning: #failed again...
                if messagebox.askokcancel('No response from controller', 'Could not read position from controller, try reconnecting?'):
                    self.cmd.Shutdown()
                    self.master.after(int(self.cycle_period), self.startup)                
    
        
    def control_cycle(self, axis = 0, mirror1=True):
        try:
            if self.state[axis] > 4:
                pass # we are in an error state, schedule next cycle and quit
                
            elif self.state[axis] < 0: # calibration mode
                self.cmd.check_for_errors(axis)
                self._save_current_mirror_steps(axis)
                self._update_displays(axis)
                
            else:
                self.cmd.check_for_errors(axis) # will raise a RuntimeError if there is an error
                
                done1, done2 = self.cmd.GetMotionDone(axis)
                
                if done1 and done2: # only do something if motors stopped moving
                    
                    self._update_actual_state(axis) # read motor positions and update the actual state
            
                    steps1, steps2 = self._get_steps_to_move(axis) # calculate next moves
                    if abs(steps1) > self.max_steps_per_cycle:
                        steps1 = self.max_steps_per_cycle * (1 if steps1>0 else -1)
                    if abs(steps2) > self.max_steps_per_cycle:
                        steps2 = self.max_steps_per_cycle * (1 if steps2>0 else -1)
                    
                    steps1 = round(steps1)
                    steps2 = round(steps2)
                    
                    # move only one mirror!
                    # but if the scheduled mirror is not commanded to move, move the other mirror instead
                    if mirror1:
                        if steps1 != 0:
                            steps2 = 0
                    else:
                        if steps2 != 0:
                            steps1 = 0
                    
                    if steps1 != 0 or steps2 != 0:
                        self.cmd.RelativeMove(steps1, steps2, axis) # do next moves
                        self.state[axis] = 1
                        if not axis: #axis==0 -> X
                            self.__StopXBtn.grid() # show the stop button
                        else:
                            self.__StopYBtn.grid() # show the stop button
                    else:
                        self.state[axis] = 0
                        if not axis: #axis==0 -> X
                            self.__StopXBtn.grid_remove() # remove the stop button
                        else:
                            self.__StopYBtn.grid_remove() # remove the stop button
        
        except RuntimeWarning as e:
            # This is a communication failure with the controller
            if self.state[axis] < 0: # calib mode, only print error to console
                xy = 'horizontal' if axis else 'vertical'
                print('communication error on reading mirror positions (%s axis)!' % xy)
                print(e.args)
            
            elif self.state[axis] < 2: # If this is the first error, set error state and quietly try again
                if e.args[0]: #True for write error (RelativeMove), False for read error
                    self.state[axis] = 3
                else:
                    self.state[axis] = 2
            else: # This is an error on the retry, alert the user
                self._update_state_indicators(axis)
                action = 'write' if e.args[0] else 'read'
                xy = 'horizontal' if axis else 'vertical'
                if e.args[2]<0:
                    axistext = ''
                else:
                    axistext = ', horizontal axis' if e.args[2] else ', vertical axis'
                if e.args[1] == 0:
                    mirror = 'both mirrors'
                else:
                    mirror = 'mirror %d' % e.args[1]
                msg = 'Communication with Picomotor controller failed (%s%s) when trying to %s "%s".' % (mirror, axistext, action, e.args[3])
                if not messagebox.askretrycancel('Communication Error (%s axis)' % xy, msg):
                    self.state[axis] += 3 # the user has opted to cancel, raise error state to stop level
                    if not axis: #axis==0, X
                        self.__StopXBtn.grid_remove() # remove the stop button
                        self.__StatusXResetBtn.grid() # show reset button
                    else:
                        self.__StopYBtn.grid_remove() # remove the stop button
                        self.__StatusYResetBtn.grid() # show reset button
        
        except RuntimeError as e:
            if self.state[axis] < 0: #calib mode, only print error to console
                print('controller error!')
                print(e.args)
            else:
                # A controller has reported an error, report to the user
                self.state[axis] = 4
                self._update_state_indicators(axis)
                lines = ''
                xy = 'horizontal' if axis else 'vertical'
                for error in e.args:
                    lines += '\nThe controller for mirror %d says "%s"' % (error[0], error[1])
                
                if not messagebox.askretrycancel('Controller Error (%s axis)' % xy,
                                                 ('The Picomotor controllers have reported errors relevant to the %s axis!' % xy) + lines):
                    self.state[axis] += 3 # the user has opted to cancel, raise error state to stop level
                    if not axis: #axis==0, X
                        self.__StopXBtn.grid_remove() # remove the stop button
                        self.__StatusXResetBtn.grid() # show reset button
                    else:
                        self.__StopYBtn.grid_remove() # remove the stop button
                        self.__StatusYResetBtn.grid() # show reset button
               
        finally: #schedule next cycle, always do this, we don't want our control loop to die
            if self.state[axis]>=2 and self.state[axis]<=4:
                mirror1new = mirror1 # we are in an error, retry state, so in next cycle try the SAME mirror again
            else:
                mirror1new = not mirror1 # next cycle, move the other mirror
            
            self._update_state_indicators(axis)
            self.master.after(int(self.cycle_period), self.control_cycle, axis, mirror1new)
            
    def control_cycle_HWPs(self):
        try:
            if self.state_HWP: # HWP controls active
                self.cmd.check_for_errors_HWPs()
                self._save_current_HWP_steps()
                self._update_HWP_displays()
        
        except RuntimeWarning as e:
            # This is a communication failure with the controller
            # for HWPs, only print error to console as in calib mode
            print('communication error on reading HWP positions!')
            print(e.args)
        
        except RuntimeError as e:
            # for HWPs, only print error to console as in calib mode
            print('controller error (HWPs)!')
            print(e.args)
               
        finally: #schedule next cycle, always do this, we don't want our control loop to die
            self.master.after(int(self.cycle_period), self.control_cycle_HWPs)
    
            
    def __toggle_calib_mode_X(self):
        if self.state[0]<0: # we already are in calib mode, now end it
            self.state[0] = -self.state[0] -1 #recover old state
            self.__CalibModeXBtn.configure(text='Go to calibration mode')
            self.__ZeroOffsetXBtn.configure(text='go to zero')
            self.__ZeroAngleXBtn.configure(text='go to zero')
            self.__IncM1XBtn.grid_remove()
            self.__DecM1XBtn.grid_remove()
            self.__IncM2XBtn.grid_remove()
            self.__DecM2XBtn.grid_remove()
            if not self.state[1] < 0 and not self.state_HWP: # only hide Stepsize controls if calib mode is also disabled on the other axis and HWPs are inactive
                self.__StepsizeEtr.grid_remove()
                self.__StepsizeLbl.grid_remove()
        elif self.state[0] == 0 or self.state[0] >= 5: # only start calib mode if we are idle or stopped (after an error or by user)
            self.state[0] = -1 - self.state[0] # save old state in the negative
            self.__CalibModeXBtn.configure(text='End calibration mode')
            self.__ZeroOffsetXBtn.configure(text='set to zero')
            self.__ZeroAngleXBtn.configure(text='set to zero')
            self.__IncM1XBtn.grid()
            self.__DecM1XBtn.grid()
            self.__IncM2XBtn.grid()
            self.__DecM2XBtn.grid()
            self.__StepsizeEtr.grid()
            self.__StepsizeLbl.grid()
        else: # motors are moving or we are retrying an error, do not start calib mode now
            pass
        self._update_state_indicators(axis=0)
        
    def __toggle_calib_mode_Y(self):
        if self.state[1]<0: # we already are in calib mode, now end it
            self.state[1] = -self.state[1] -1 #recover old state
            self.__CalibModeYBtn.configure(text='Go to calibration mode')
            self.__ZeroOffsetYBtn.configure(text='go to zero')
            self.__ZeroAngleYBtn.configure(text='go to zero')
            self.__IncM1YBtn.grid_remove()
            self.__DecM1YBtn.grid_remove()
            self.__IncM2YBtn.grid_remove()
            self.__DecM2YBtn.grid_remove()
            if not self.state[0] < 0 and not self.state_HWP: # only hide Stepsize controls if calib mode is also disabled on the other axis and HWPs are inactive
                self.__StepsizeEtr.grid_remove()
                self.__StepsizeLbl.grid_remove()
        elif self.state[1] == 0 or self.state[1] >= 5: # only start calib mode if we are idle or stopped after an error
            self.state[1] = -1 - self.state[1] # save old state in the negative
            self.__CalibModeYBtn.configure(text='End calibration mode')
            self.__ZeroOffsetYBtn.configure(text='set to zero')
            self.__ZeroAngleYBtn.configure(text='set to zero')
            self.__IncM1YBtn.grid()
            self.__DecM1YBtn.grid()
            self.__IncM2YBtn.grid()
            self.__DecM2YBtn.grid()
            self.__StepsizeEtr.grid()
            self.__StepsizeLbl.grid()
        else: # motors are moving or we are retrying an error, do not start calib mode now
            pass
        self._update_state_indicators(axis=1)
    
    
    def __toggle_HWPs(self):
        if self.state_HWP:
            self.state_HWP = False
            self.__ToggleHWPsBtn.configure(text='show HWP controls')
            
            self.__StepsHWP1Etr.grid_remove()
            self.__StepsHWP1Lbl.grid_remove()
            self.__IncHWP1Btn.grid_remove()
            self.__DecHWP1Btn.grid_remove()
            self.__StepsHWP2Etr.grid_remove()
            self.__StepsHWP2Lbl.grid_remove()
            self.__IncHWP2Btn.grid_remove()
            self.__DecHWP2Btn.grid_remove()
            
            if not any([s<0 for s in self.state]):
                self.__StepsizeEtr.grid_remove()
                self.__StepsizeLbl.grid_remove()                
            
        else:
            self.state_HWP = True
            self.__ToggleHWPsBtn.configure(text='hide HWP controls')
            
            self.__StepsHWP1Etr.grid()
            self.__StepsHWP1Lbl.grid()
            self.__IncHWP1Btn.grid()
            self.__DecHWP1Btn.grid()
            self.__StepsHWP2Etr.grid()
            self.__StepsHWP2Lbl.grid()
            self.__IncHWP2Btn.grid()
            self.__DecHWP2Btn.grid()
            
            self.__StepsizeEtr.grid()
            self.__StepsizeLbl.grid()
            
    
    def __calib_X(self, new_value):
        if self.state[0] < 0: # Of course, only do this if we are in calib mode!
            offset = self.__OffsetXScl.get()
            angle = self.__AngleXScl.get()
            
            self.angle_state_1[0], self.angle_state_2[0] = self.calc.to_mirror_angles(offset, angle, axis=0)
            self._update_displays(axis=0)
            
    
    def __calib_Y(self, new_value):
        if self.state[1] < 0: # Of course, only do this if we are in calib mode!
            offset = self.__OffsetYScl.get()
            angle = self.__AngleYScl.get()
            
            self.angle_state_1[1], self.angle_state_2[1] = self.calc.to_mirror_angles(offset, angle, axis=1)
            self._update_displays(axis=1)
            
            
    def __inc_M1X(self):
        if self.state[0] < 0: # calib mode
            self.__move_steps(axis = 0, mirror1=True, inc=True)
            
    def __dec_M1X(self):
        if self.state[0] < 0: # calib mode
            self.__move_steps(axis = 0, mirror1=True, inc=False)
    
    
    def __inc_M2X(self):
        if self.state[0] < 0: # calib mode
            self.__move_steps(axis = 0, mirror1=False, inc=True)
    
    def __dec_M2X(self):
        if self.state[0] < 0: # calib mode
            self.__move_steps(axis = 0, mirror1=False, inc=False)
    
    
    def __inc_M1Y(self):
        if self.state[1] < 0: # calib mode
            self.__move_steps(axis = 1, mirror1=True, inc=True)
    
    def __dec_M1Y(self):
        if self.state[1] < 0: # calib mode
            self.__move_steps(axis = 1, mirror1=True, inc=False)
    
    
    def __inc_M2Y(self):
        if self.state[1] < 0: # calib mode
            self.__move_steps(axis = 1, mirror1=False, inc=True)
        
    def __dec_M2Y(self):
        if self.state[1] < 0: # calib mode
            self.__move_steps(axis = 1, mirror1=False, inc=False)
    
    
    def __inc_HWP1(self):
        if self.state_HWP:
            self.__move_steps_HWP(HWP1=True, inc=True)
    
    def __dec_HWP1(self):
        if self.state_HWP:
            self.__move_steps_HWP(HWP1=True, inc=False)
    
    def __inc_HWP2(self):
        if self.state_HWP:
            self.__move_steps_HWP(HWP1=False, inc=True)
    
    def __dec_HWP2(self):
        if self.state_HWP:
            self.__move_steps_HWP(HWP1=False, inc=False)
    
    
    def __move_steps_HWP(self, HWP1=True, inc=True):
        try:
            step = (1 if inc else -1) * self.__Stepsize.get()
            if HWP1:
                self.cmd.RelativeMove_HWPs(step, 0)
            else:
                self.cmd.RelativeMove_HWPs(0, step)
            #self._save_current_HWP_steps() # this cannot be triggered immediately I guess... => is done in control cycle
                        
        except tk.TclError:
            messagebox.showerror('Value Error', 'Please enter integers only for the step size!')
            
        except RuntimeWarning:
            print('communicaton error on trying to do Relative Move (HWP %d)' % 1 if HWP1 else 2)
    
    
    def __move_steps(self, axis=0, mirror1=True, inc=True):
        try:
            step = (1 if inc else -1) * self.__Stepsize.get()
            if mirror1:
                self.cmd.RelativeMove(step, 0, axis)
            else:
                self.cmd.RelativeMove(0, step, axis)
            #self._save_current_mirror_steps(axis) # this cannot be triggered immediately I guess... => is done in control cycle
                        
        except tk.TclError:
            messagebox.showerror('Value Error', 'Please enter integers only for the step size!')
            
        except RuntimeWarning:
            xy = 'horizontal' if axis else 'vertical'
            print('communicaton error on trying to do Relative Move (Mirror %d, %s axis)' % (1 if mirror1 else 2, xy))
    
    
    
    def _save_current_mirror_steps(self, axis = 0):
        pos_1, pos_2 = self.cmd.GetPosition(axis)
        self.step_pos_1[axis] = pos_1
        self.step_pos_2[axis] = pos_2
        
    def _save_all_current_mirror_steps(self):
        self._save_current_mirror_steps(axis = 0)
        self._save_current_mirror_steps(axis = 1)
        
    def _save_current_HWP_steps(self):
        pos_1, pos_2 = self.cmd.GetPosition_HWPs()
        self.step_pos_HWPs[0] = pos_1
        self.step_pos_HWPs[1] = pos_2
                
    
    def _update_actual_state(self, axis = 0):
        new1, new2 = self.cmd.GetPosition(axis)
        diff1 = new1 - self.step_pos_1[axis]
        diff2 = new2 - self.step_pos_2[axis]
        
        angle_diff_1, angle_diff_2 = self.calc.steps_to_angle(diff1, diff2, axis)
        
        self.step_pos_1[axis] = new1
        self.step_pos_2[axis] = new2
        self.angle_state_1[axis] += angle_diff_1
        self.angle_state_2[axis] += angle_diff_2
        
        self._update_displays(axis)
        
    def _update_displays(self, axis = 0):
        angle1 = self.angle_state_1[axis]
        angle2 = self.angle_state_2[axis]
        offset, angle = self.calc.to_undulator_beam_pos(angle1, angle2, axis)
        steps1 = self.step_pos_1[axis]
        steps2 = self.step_pos_2[axis]
        angle1 = round(angle1, 2)
        angle2 = round(angle2, 2)
        offset = round(offset, 4)
        angle  = round(angle , 2)
        if not axis: # axis == 0: X
            self.__AngleM1X.set(angle1)
            self.__AngleM2X.set(angle2)
            self.__OffsetXActual.set(offset)
            self.__AngleXActual.set(angle)
            self.__StepsM1X.set(steps1)
            self.__StepsM2X.set(steps2)
        else:
            self.__AngleM1Y.set(angle1)
            self.__AngleM2Y.set(angle2)
            self.__OffsetYActual.set(offset)
            self.__AngleYActual.set(angle)
            self.__StepsM1Y.set(steps1)
            self.__StepsM2Y.set(steps2)
    
    def _update_HWP_displays(self):
        self.__StepsHWP1.set(self.step_pos_HWPs[0])
        self.__StepsHWP2.set(self.step_pos_HWPs[1])

    def _update_state_indicators(self, axis=0):
        s = self.state[axis]
        if s==1: # motors are moving
            colour = self.__yellow
            text = 'moving...'
        elif s==2 or s==3:
            colour = self.__orange
            text = 'communication error'
        elif s==4:
            colour = self.__orange
            text = 'controller error'
        elif s==5 or s==6:
            colour = self.__red
            text = 'communication error'
        elif s==7:
            colour = self.__red
            text = 'controller error'
        elif s>=8:
            colour = self.__red
            text = 'stopped by user'
        elif s==0:
            colour = self.__green
            text = 'idle'
        else: # s<0, calib mode
            colour = self.__blue
            text = 'calibration mode'
            
        if not axis: # axis==0 -> X
            self.__StatusXLbl.configure(bg = colour, text = text)
        else:
            self.__StatusYLbl.configure(bg = colour, text = text)
    

    def __stop_motion_X(self):
        self.state[0] += 8
        self.__StopXBtn.grid_remove() # remove the stop button
        self.__StatusXResetBtn.grid() # show the reset button

    def __stop_motion_Y(self):
        self.state[1] += 8
        self.__StopYBtn.grid_remove() # remove the stop button
        self.__StatusYResetBtn.grid() # show the reset button
        
            
    def __reset_state_X(self):
        if self.state[0] >= 8: # return from stopped by user state
            self.state[0] -= 8
            self.__StatusXResetBtn.grid_remove() # remove the reset button
        if self.state[0] >= 5:
            self.state[0] -= 3 # return to error, retry state
            self.__StatusXResetBtn.grid_remove() # remove the reset button
        
    def __reset_state_Y(self):
        if self.state[1] >= 8: # return from stopped by user state
            self.state[1] -= 8
            self.__StatusYResetBtn.grid_remove() # remove the reset button
        if self.state[1] >= 5:
            self.state[1] -= 3 # return to error, retry state
            self.__StatusYResetBtn.grid_remove() # remove the reset button
            

    def _get_angle_to_move(self, axis = 0):
        if not axis: # axis == 0: X
            offset = self.__OffsetXScl.get()
            angle = self.__AngleXScl.get()
        else:
            offset = self.__OffsetYScl.get()
            angle = self.__AngleYScl.get()
        soll1, soll2 = self.calc.to_mirror_angles(offset, angle, axis)
        diff1 = soll1 - self.angle_state_1[axis]
        diff2 = soll2 - self.angle_state_2[axis]
        return diff1, diff2
    
    def _get_steps_to_move(self, axis = 0):
        angle_diff_1, angle_diff_2 = self._get_angle_to_move(axis)
        return self.calc.angle_to_steps(angle_diff_1, angle_diff_2, axis)
        
    
#    def toggle_resolution(self):
#        if self.__OffsetXScl['resolution'] < 0.05:
#            self.__OffsetXScl.configure(resolution=0.1)
#            
#        else:
#            self.__OffsetXScl.configure(resolution=0.01)
#        self.print_selection(str(self.__OffsetXScl.get()))
    
    def __zero_offset_X(self):
        self.__OffsetXScl.set(0)
        #self.__calib_X(0) # this is only needed for calibration mode, handled inside the function
    
    def __zero_angle_X(self):
        self.__AngleXScl.set(0)
        #self.__calib_X(0) # this is only needed for calibration mode, handled inside the function
    
    def __zero_offset_Y(self):
        self.__OffsetYScl.set(0)
        #self.__calib_Y(0) # this is only needed for calibration mode, handled inside the function
    
    def __zero_angle_Y(self):
        self.__AngleYScl.set(0)
        #self.__calib_Y(0) # this is only needed for calibration mode, handled inside the function
    
    
    def on_closing(self):
        if self.state[0] == 1 or self.state[1] == 1:
            addition = '\nMotors are moving!!'
        elif self.state[0] > 1 or self.state[1] > 1:
            addition = '\nThe program is in an error state, motors might be moving!'
        else:
            addition = ''
        if messagebox.askokcancel('Quit?', 'Do you really want to quit?' + addition):
            if self.cmd is not None:
                self.cmd.Shutdown()
                print('Shutdown!')
            
            offsetX, angleX = self.calc.to_undulator_beam_pos(self.angle_state_1[0], self.angle_state_2[0], 0)
            offsetY, angleY = self.calc.to_undulator_beam_pos(self.angle_state_1[1], self.angle_state_2[1], 1)
                        
            self._conf["last_known"]["OffsetX"] = str(offsetX)
            self._conf["last_known"]["AngleX"] = str(angleX)
            self._conf["last_known"]["OffsetY"] = str(offsetY)
            self._conf["last_known"]["AngleY"] = str(angleY)
            
            self._conf["last_set"]["OffsetX"] = str(self.__OffsetXScl.get())
            self._conf["last_set"]["AngleX"] = str(self.__AngleXScl.get())
            self._conf["last_set"]["OffsetY"] = str(self.__OffsetYScl.get())
            self._conf["last_set"]["AngleY"] = str(self.__AngleYScl.get())
            
            with open("mirror_state.ini", 'w') as file:
                self._conf.write(file)
            
            self.master.destroy()
