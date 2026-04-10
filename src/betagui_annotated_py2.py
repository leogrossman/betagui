#!usr/bin/python
######## Author: Ji Li ########

# Annotated legacy copy of the original Python 2 tool.
#
# Goal of this file:
# - stay close to the original structure
# - document what each section appears to do
# - mark risky areas, likely bugs, and write paths
# - avoid "fixing" behavior at this stage
#
# Important:
# - this is still Python 2 style code
# - EPICS PV objects are created at import time, exactly as in the original
# - several paths below are clearly incomplete or inconsistent; they are
#   intentionally preserved for later porting work

from Tkinter import *
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import threading, thread
import numpy as np
import time
from scipy import constants
from FileDialog import *
from scipy.optimize import fsolve
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt
import threading, thread,epics
from matplotlib import rc
import matplotlib,sys
from tkFileDialog import *
from scipy.optimize import curve_fit
import os

# Matplotlib is configured globally at import time. `usetex=True` makes the GUI
# depend on a working LaTeX installation, which is a likely startup blocker.
rc('font', **{'family':'serif','serif':['Palatino']})
rc('text', usetex=True)
LARGE_FONT= ("Verdana", 11)
DEFAULT_FONT = ('Helvetica', 12)
t = None
runD = True
Nharmonic=80
deincrease=False

## BPM variables
# Readback PV for BPM buffer. In the current script the BPM buffer is not really
# used: the helper below returns zeros instead of decoding the waveform.
BPMIOC=epics.PV('BPMZ1X003GP:rdBufBpm')

## Tunes
pvfreqX=epics.PV('TUNEZRP:measX')               # in kHz?
pvfreqY=epics.PV('TUNEZRP:measY')               # in kHz?
pvfreqS=epics.PV('TUNEZRP:measZ')               # in kHz?
#pvfreqS=epics.PV('cumz4x003gp:tuneSyn')
#pvfreqS=epics.PV('JLC09VP')

## RF frequency
pvfrfSet=epics.PV('MCLKHGP:setFrq')             # comment says kHz, later code treats as Hz

## Sextupole settings
pvS1P1=epics.PV('S1P1RP:setCur')  # A
pvS1P2=epics.PV('S1P2RP:setCur')  # A
pvS2P1=epics.PV('S2P1RP:setCur')  # A
pvS2P2=epics.PV('S2P2RP:setCur')  # A
pvS2P2K=epics.PV('S2P2KRP:setCur')
pvS2P2L=epics.PV('S2P2LRP:setCur')
pvS3P1=epics.PV('S3P1RP:setCur')  # A
pvS3P2=epics.PV('S3P2RP:setCur')  # A

## Orbit, feedback, phase modulation, optics mode
pvorbit  = epics.PV('ORBITCCP:selRunMode')
pvorbitrdbk =epics.PV('RMC00VP')
pvfdbsetS=epics.PV('IGPF:Z:FBCTRL')
pvfdbsetX=epics.PV('IGPF:X:FBCTRL')
pvfdbsetY=epics.PV('IGPF:Y:FBCTRL')
pvphasmod=epics.PV('PAHRP:cmdExtPhasMod')
pvOptTab=epics.PV('MLSOPCCP:actOptRmpTblSet')

## Additional diagnostics used mainly in the sextupole scan window
pv10lt=epics.PV('CUM1ZK3RP:rdLt10')
pv100lt=epics.PV('CUM1ZK3RP:rdLt100')
pvcurlt=epics.PV('OPCHECKCCP:calcCurrLife')
QPD1HS=epics.PV('QPD01ZL2RP:rdSigmaX')
QPD1VS=epics.PV('QPD01ZL2RP:rdSigmaY')
QPD0HS=epics.PV('QPD00ZL4RP:rdSigmaX')
QPD0VS=epics.PV('QPD00ZL4RP:rdSigmaY')
sepdose=epics.PV('SEKRRP:rdDose')
pvcur=epics.PV('CUM1ZK3RP:measCur')
pvE=epics.PV('ERMPCGP:rdRmp')
pvwhitenosie=epics.PV('WFGENC1CP:rdVolt')

# Startup readback happens immediately on import. If EPICS is unavailable or a
# PV does not connect, import may block or return unexpected None values.
frf0=pvfrfSet.get()
freqX0 =pvfreqX.get()
freqY0 =pvfreqY.get()
freqS0 =pvfreqS.get()


sextslist=[pvS1P1,pvS1P2,pvS2P1,pvS2P2K,pvS2P2L,pvS3P1,pvS3P2]
ini_sext=[ele.get() for ele in sextslist]
ini_fdb=[pvfdbsetX.get(),pvfdbsetY.get(),pvfdbsetS.get()]
ini_orbit=pvorbitrdbk.get()

def save_setting():
    # Save the current machine state into globals so the GUI can later restore
    # them via "reset". This does not write to the machine.
    global ini_sext,ini_fdb,frf0,ini_orbit
    ini_sext=[ele.get() for ele in sextslist]
    print ini_sext
    ini_fdb=[pvfdbsetX.get(),pvfdbsetY.get(),pvfdbsetS.get()]
    frf0=pvfrfSet.get()
    print 'initial rf frequency is:',frf0,' MHz'
    ini_orbit=pvorbitrdbk.get()
    print 'initial orbit correction status is:',ini_orbit
    print 'save the current setting'

def bumppolyfit(X,p1,p2):  # bumppolyfit means intercept = 0
    # Quadratic-through-origin fit used in the sextupole scan window.
    x=X
    return p1*x*x + p2*x

def set_all2ini(dchrom_readout,bt1,bt2):
    # MACHINE WRITE PATH: restores RF, sextupoles, feedback, orbit mode, and
    # external phase modulation state to the saved startup values.
    print '********** reset the parameters **********'
    global ini_sext,ini_fdb,frf0,ini_orbit
    print ini_sext
    for i in range(3):
        dchrom_readout[i].delete('1.0',END)
        dchrom_readout[i].insert(END,'0')
        dchrom_readout[i].tag_config('1.0', justify='center')
    bt1.config(state='normal')
    bt1.update()
    bt2.config(state='normal')
    bt2.update()
    set_frf_slowly(frf0)
    pvS1P1.put(ini_sext[0])
    pvS1P2.put(ini_sext[1])
    pvS2P1.put(ini_sext[2])
    pvS2P2K.put(ini_sext[3])
    pvS2P2L.put(ini_sext[4])
    pvS3P1.put(ini_sext[5])
    pvS3P2.put(ini_sext[6])
    pvfdbsetX.put(ini_fdb[0])
    pvfdbsetY.put(ini_fdb[1])
    pvfdbsetS.put(ini_fdb[2])
    pvorbit.put(ini_orbit)
    pvphasmod.put('disabled')

def set_frf_slowly(target_frf_in_Hz):
    # MACHINE WRITE PATH: ramps the RF setpoint in 10 evenly spaced steps.
    Nsteps=10
    start_frf_in_Hz=pvfrfSet.get()
    #rfstep=np.arange(0,Nsteps)/Nsteps*(target_frf_in_Hz-start_frf_in_Hz)+start_frf_in_Hz
    rfstep=np.linspace(start_frf_in_Hz,target_frf_in_Hz,Nsteps)
    #pvfrfSet=PV('MCLKHGP:setFrq')
    for ii in range(Nsteps):
        pvfrfSet.put(rfstep[ii])
        time.sleep(0.2)
    print rfstep[ii]

def set_Isextupole_slowly(sname,target_current):
    # Intended as a slow sextupole ramp helper, but this function is broken:
    # - `sname` is treated both as a PV name string and as a PV object
    # - `pvSextupole` is never used
    # - `aself` is undefined
    # - no callers are active in the main workflow
    pvSextupole=epics.PV(sname)
    start_current=sname.get()
    pvdiff=target_current-start_current
    if aself.cor_wgt(int(pvdiff))<=1:
        Nsteps=2
    else:
        Nsteps=aself.cor_wgt(int(pvdiff))*2
    Istep=np.linspace(start_current,target_current,Nsteps)
    for ii in range(Nsteps):
        sname.put(Istep[ii])
        time.sleep(0.1)

def set_sext_degauss(sextlist,target):
    # MACHINE WRITE PATH: applies an oscillating current pattern around target,
    # then returns the listed sextupoles to the final value.
    #
    # The two unconditional writes to pvS1P1/pvS1P2 at the end look suspicious:
    # they ignore the supplied `sextlist`.
    finalV=target
    N=7
    mini=target-2
    maxi=target+2
    if target==int(target):
        target=target-0.0001
    t1=int(target)
    t2=t1+1
    A1=np.linspace(mini,t1,N)
    A2=np.linspace(maxi,t2,N)
    II=np.array([])
    for kn in range(N):
        II=np.append(II,[A1[kn],A2[kn]])
    for ii in range(len(II)):
        for svar in sextlist:
            svar.put(II[ii])
    for svar in sextlist:
        svar.put(finalV)
    pvS1P1.put(finalV)
    pvS1P2.put(finalV)

def cal_alpha0():
    # Computes momentum compaction proxy `alpha0` from synchrotron tune, RF,
    # cavity voltage, and beam energy. Assumes all units line up correctly.
    mfs=[]
    for i in range(10):
        #mfs.append(pvfreqS.get()/1000)
        mfs.append(pvfreqS.get())
        time.sleep(0.5)
    freqS0=np.mean(mfs)
    print freqS0, "frf"
    #freqS0 =pvfreqS.get()
    frf0Set=pvfrfSet.get()  # in Hz according to later use
    pvUcavSet=epics.PV('PAHRP:setVoltCav')
    Ucav=pvUcavSet.get()*1000 # in V
    pvErd=epics.PV('ERMPCGP:rdRmp')
    Erd=pvErd.get()*1e6 # in eV
    print Erd
    alpha=(freqS0*1000)**2/(frf0Set*1000)**2*2.0*3.1415926*Nharmonic*Erd/Ucav
    print alpha
    return alpha

def BPDM():
    # Intended BPM display/measurement helper. In its current state it returns
    # hard-coded BPM positions and an all-zero orbit array because waveform
    # decoding is commented out.
#    BPMIOC=epics.PV('BPMZ1X003GP:rdBufBpm')
#    BPMdata=BPMIOC.get()
    Pos=[1.2034,2.1040,4.2490,5.2290,6.2040,8.1872,9.0466,14.9534,15.8540,17.9990,
         18.9790,19.9540,21.9372,22.7966,25.2034,26.1040,28.2490,29.2290,30.2040,
         32.1872,33.0466,38.9534,39.8540,41.9990,42.9790,43.9540,45.9372,46.7966]
    inx = [1,2,3,4,5,6,7,9,10,11,12,13,14,15,17,18,19,20,21,22,23,25,26,27,28,29,30,31];
#    BPM=list(BPMdata[i] for i in np.array(inx)-1)
    BPM=[0 for i in range(len(Pos))]
    return(Pos,BPM)

def set_all_sexts(delta_chrom):
    # MACHINE WRITE PATH: applies the inverse response matrix to requested
    # chromaticity changes and increments sextupole setpoints.
    global B, mat_status
    print mat_status
    Minv=B
    MI=np.dot(Minv,delta_chrom[0:B.shape[0]])
    print delta_chrom
    print MI
    pvS1P2.put(pvS1P2.get()+MI[0])
    if  mat_status==1 or  mat_status==3:
        print 'not P2 correction'
        pvS1P1.put(pvS1P1.get()+MI[0])
        pvS2P1.put(pvS2P1.get()+MI[1])
    pvS2P2K.put(pvS2P2K.get()+MI[1])
    pvS2P2L.put(pvS2P2L.get()+MI[1])
    if B.shape[0]==3:
        if  mat_status==3:
            pvS3P1.put(pvS3P1.get()+MI[2])
        pvS3P2.put(pvS3P2.get()+MI[2])

def MeaChrom(bt_obj,bt_obj2,f_obj,fig,InputVar,bt_cor):
    # Main chromaticity measurement routine.
    #
    # Workflow:
    # 1. disable GUI buttons
    # 2. turn off transverse/longitudinal feedback and orbit correction
    # 3. sweep RF over a computed range
    # 4. measure tunes at each RF step
    # 5. fit tune versus dRF
    # 6. restore RF and feedback/orbit settings
    # 7. return measured chromaticities
    #
    # MACHINE WRITE PATH: this function writes feedback PVs, orbit mode, and RF.
    global runD,mea_bump_status

##    alpha0=cal_alpha0()
    bt_obj.config(state = 'disable')
    bt_obj.update()
    bt_obj2.config(state = 'disable')
    bt_obj2.update()
    bt_buf=bt_cor  ## save the information of correction buttons
    bt_buf=[[[],[]] for i in range(3)]
    for i in range(3):   ## disable all the correction buttons
        bt_buf[i][0]=bt_cor[0][i].cget('state')
        bt_buf[i][1]=bt_cor[1][i].cget('state')
    for i in range(3):   ## disable all the correction buttons
        bt_cor[0][i].config(state='disable')
        bt_cor[0][i].update()
        bt_cor[1][i].config(state='disable')
        bt_cor[1][i].update()

 ##   alpha0=0.0265685828781   #call for the function#
    for i in range(len(f_obj)):
        f_obj[i].clear()
    pvfdbsetX.put(0)
    pvfdbsetY.put(0)
    pvfdbsetS.put(0)
    pvorbit.put(0)
    time.sleep(0.5)
    if InputVar[7].get()=='dynamic':
        alpha0=cal_alpha0()
    else:
        alpha0=float(InputVar[7].get())
    print alpha0 ## to show this value, a box needed
    print "\n\n##### Chromaticity Measurement #####"
    print "####################################"
    frev=1.0/(48.0/constants.c) / 1000.0   # frev = 6246 kHz
    npoints=int(InputVar[1].get()) # Number of RF points
    orderfit=int(InputVar[4].get())
    delt_xmax=float(InputVar[3].get())/1000           # mm -> m?
    delt_xmin=float(InputVar[2].get())/1000
    if epics.PV('MLSOPCCP:actOptRmpTblSet').get()==1:
        Dmax=1.5            # maximum dispersion guess for this machine mode
    elif epics.PV('MLSOPCCP:actOptRmpTblSet').get()==3:
        Dmax=1
    else:
        Dmax=2
    print Dmax
    frfmax=frf0 +(-delt_xmin*alpha0*frf0/Dmax)
    frfmin=frf0 - (delt_xmax*alpha0*frf0/Dmax)
    delayChangefrf=float(InputVar[5].get()) # seconds after changing RF
    nmeasurements=int(InputVar[0].get())   # number of tune measurements to average
    delayMeasTune=float(InputVar[6].get())   # intended delay between tune reads
    frfrange=np.linspace(frfmin, frfmax, npoints)
    delta=frfrange-frf0
    tunes= np.array([[],[],[]])
    deltabuf=np.array([])
    axs=[[],[[],[]],[[],[]],[[],[]]]
    print "\n-----Start chromaticity measurement - vary frf and measure tunes:"
    Ini_Positions,Ini_BPMs=BPDM()
    for i in range(npoints):
        if runD:
            set_frf_slowly(frfrange[i])
            if i==0:
                time.sleep(5)

            print frfrange[i]
            time.sleep(delayChangefrf)
            fbuf=[[],[],[]]
            for j in range(nmeasurements):
                fbuf[0]=np.append(fbuf[0],pvfreqX.get())
                fbuf[1]=np.append(fbuf[1],pvfreqY.get())
                fbuf[2]=np.append(fbuf[2],pvfreqS.get())
                # BUG/RISK: `delayMeasTune` is never used, even though the UI
                # exposes it as an input parameter.
                #fbuf[2]=np.append(fbuf[2],pvfreqS.get()/1000)
            # BUG/RISK: this loop mutates `nmeasurements`, so later iterations
            # of the outer loop use fewer reads than the UI requested.
            while nmeasurements>5:
                for l in range(3):
                    fbuf[l]=np.delete(fbuf[l],np.argmax(fbuf[l]),np.argmin(fbuf[l]))
                nmeasurements-=2
            tunes = [np.append(tunes[0],np.mean(fbuf[0])),np.append(tunes[1],np.mean(fbuf[1])),np.append(tunes[2],np.mean(fbuf[2]))]
            deltabuf = np.append(deltabuf,delta[i])
            fitPara =  (np.polyfit(deltabuf,tunes[0],orderfit), np.polyfit(deltabuf,tunes[1],orderfit), np.polyfit(deltabuf,tunes[2],orderfit))
            (fitPolyX, fitPolyY, fitPolyS) = (np.poly1d(fitPara[0]), np.poly1d(fitPara[1]), np.poly1d(fitPara[2]))
            fitVal = (fitPolyX(deltabuf), fitPolyY(deltabuf), fitPolyS(deltabuf))
            axis_labels = [['BPM position','Orbit displacement'],['dfrf','fx'],['dfrf','fy'],['dfrf','fs']]
            if i==0:
                Positions,BPMs = BPDM()
                Bdisplacement = (np.array(BPMs)-np.array(Ini_BPMs))*0.3051758e-3
                axs[0] = f_obj[0].plot(Positions,Bdisplacement,'r-')[0]
                f_obj[0].set_ylim(-4,4)
                f_obj[0].set_xlabel(axis_labels[0][0], fontsize =12,fontstyle='italic')
                f_obj[0].set_ylabel(axis_labels[0][1], fontsize =12,fontstyle='italic')
                for nn in range(3):
                    axs[nn+1][0] = f_obj[nn+1].plot(deltabuf, tunes[nn], 'ro')[0]
                    axs[nn+1][1] = f_obj[nn+1].plot(deltabuf, fitVal[nn])[0]
                    f_obj[nn+1].set_xlim( frfmin-frf0,  frfmax-frf0)
                    f_obj[nn+1].set_xlabel(axis_labels[nn+1][0], fontsize =12,fontstyle='italic')
                    f_obj[nn+1].set_ylabel(axis_labels[nn+1][1], fontsize =12,fontstyle='italic')
            Positions,BPMs=BPDM()
            Bdisplacement=(np.array(BPMs)-np.array(Ini_BPMs))*0.3051758e-3
            axs[0].set_ydata(Bdisplacement)
            f_obj[0].autoscale_view(tight=None, scalex=False, scaley=True)
            for nn in range(3):
                    axs[nn+1][0].set_xdata(np.array(deltabuf))
                    axs[nn+1][0].set_ydata(tunes[nn])
                    axs[nn+1][1].set_xdata(np.array(deltabuf))
                    axs[nn+1][1].set_ydata(fitVal[nn])
                    f_obj[nn+1].set_xlim( frfmin-frf0,  frfmax-frf0)
                    f_obj[nn+1].autoscale_view(tight=None, scalex=False, scaley=True)
            f_obj[3].set_ylim( np.max(tunes[2])-2,  np.max(tunes[2]+2))
            fig.canvas.draw()

        else:
            print 'I am going to break'
            break
    set_frf_slowly(frf0)
    for i in range(3):
        bt_cor[0][i].config(state=bt_buf[i][0])
        bt_cor[0][i].update()
        bt_cor[1][i].config(state=bt_buf[i][1])
        bt_cor[1][i].update()
    pvfdbsetX.put(ini_fdb[0])
    pvfdbsetY.put(ini_fdb[1])
    pvfdbsetS.put(ini_fdb[2])
    pvorbit.put(ini_orbit)
    if not mea_bump_status:
        bt_obj.config(state = 'normal')
        bt_obj.update()
        bt_obj2.config(state = 'normal')
        bt_obj2.update()

    if runD:
        Positions,BPMs = BPDM()
        Bdisplacement = (np.array(BPMs)-np.array(Ini_BPMs))*0.3051758e-3
        axs[0].set_ydata(Bdisplacement)
        f_obj[0].set_ylim(-4,4)
        f_obj[0].autoscale_view(tight=None, scalex=False, scaley=True)
        Xi_mea=[-fitPara[0][-2]*frf0*alpha0/frev,-fitPara[1][-2]*frf0*alpha0/frev,-fitPara[2][-2]*frf0*alpha0/frev]
        Xi_names=[r'$\xi$$x$',r'$\xi$$y$',r'$\xi$$s$']
        for x in range(3):
            f_obj[x+1].annotate(Xi_names[x] + ' = ' +str("{:10.4f}".format(Xi_mea[x])), xy=(0.3, -0.015), xycoords='axes fraction', fontsize=14,
                                            xytext=(0, -15), textcoords='offset points',
                                            ha='right', va='top',bbox=dict(boxstyle="round4", fc="y"))
        fig.canvas.draw()
        print Xi_mea
        print np.transpose(Xi_mea)
        return Xi_mea
    else:
        Xi_mea=np.NAN
        Xi_names=['xix','xiy','xis']
        for x in range(3):
            f_obj[x+1].annotate('paused', xy=(0.3, -0.015), xycoords='axes fraction', fontsize=11,
                                            xytext=(0, -15), textcoords='offset points',
                                            ha='right', va='top')
        fig.canvas.draw()

class mainwindow(Frame):
    # Main Tkinter window. Most application behavior is implemented as nested
    # functions inside `__init__`, which tightly couples UI widgets to the
    # measurement logic and global PV objects.
    def __init__(self, master):
        Frame.__init__(self,master)
        self.master = master
        self.master.title("Chromaticity tool pos alpha@MLS")

        # Layout frames for inputs, matrix controls, correction controls, side
        # buttons, and the matplotlib canvas.
        Frame1 = Frame(master, bg="#C5C1AA",width=100, height=150)
        Frame1.grid(row = 0, column = 0, rowspan = 9, columnspan = 2, sticky = W+E+N+S)
        xf = Frame(Frame1, relief=GROOVE, borderwidth=2)
        xf.place(relx=0.125, rely=0.125, anchor=NW)
        Frame2 = Frame(master, bg="#dabd6d",width=200, height=116.67)
        Frame2.grid(row = 0, column = 2, rowspan = 5, columnspan = 5, sticky = W+E+N+S)
        Frame2.pack_propagate(0)
        Frame5 = Frame(master, bg="#dabd6d",width=200, height=33.33)
        Frame5.grid(row =5, column =2, rowspan =4, columnspan = 11, sticky = W+E+N+S)
        Frame2.pack_propagate(0)
        Frame3 = Frame(master, bg="#8FA880",width=100, height=150)
        Frame3.grid(row = 0, column =13, rowspan = 9, columnspan = 1, sticky = W+E+N+S)

        Frame4 = Frame(master, width=400, height=160)
        Frame4.grid(row = 9, column =0, rowspan =1, columnspan = 14, sticky = W+E+N+S)
##        Frame4.pack_propagate(0)
        Label(master=Frame1, text=' Inputs').grid(row=0,column=1, padx = 5, pady = 5, ipadx = 6, ipady = 4,sticky=E+W)
        F1_lab_names=['N of Q measurements','Ndfrf','dfrfmin w.r.t Xdisp /mm','dfrfmax w.r.t Xdisp /mm','fit ordr','delay after setting rf /s','t between Q measuremnts /s']
        self.F1_entry_names=['ntimes','Npoints','dfmin','dfmax','fit_order','delay_set_rf','delay_mea_Tunes','alpha0']
        F1_entry_num=['7','11','-2','2','2','5','1','dynamic']
        for r in range(2):
            Frame1.columnconfigure(r, weight=1)
        for c in range(7):
            Frame1.rowconfigure(c, weight=1)
            Label(master=Frame1, text=F1_lab_names[c]).grid(row=c+1,column=0,padx = 2, pady = 2,sticky=E+W)
            self.F1_entry_names[c]=StringVar()
            Entry(master=Frame1, textvariable=self.F1_entry_names[c],justify='center',width=1).grid(row=c+1,column=1,padx = 2, pady = 2,sticky=E+W)
            self.F1_entry_names[c].set(F1_entry_num[c])
        self.F1_entry_names[7]=StringVar()
        Entry(master=Frame1, textvariable=self.F1_entry_names[7],justify='center',width=1).grid(row=8,column=1,padx = 2, pady = 2,sticky=E+W)
        self.F1_entry_names[7].set(F1_entry_num[7])

        # Button: launch the main chromaticity measurement in a worker thread.
        self.mea_button=Button(master=Frame1, text='Measure the chromaticity',bg='#008000',fg='white',font=('bold','10'),command=lambda: start_mea(self.mea_button, self.mea_bump,self.cor_wgt))
        self.mea_button.grid(row =0, column = 0, padx = 5, pady = 5)

        # Button: compute alpha0 and display it in the corresponding input box.
        self.mea_alpha=Button(master=Frame1, text='Measure alpha0',bg='#008000',height=1,fg='white',font=('bold','10'),command=lambda: dis_alpha())
        self.mea_alpha.grid(row =8, column = 0, padx = 5, pady = 0)
        def dis_alpha():
            alpha_num=cal_alpha0()
            self.F1_entry_names[7].set(str(alpha_num))

##        stopmea_button=Button(master=Frame1, text='Stop measurement',command=lambda: stop_mea())
##        stopmea_button.grid(row =8, column = 1, padx = 10, pady = 10)
        button_obj=self.mea_button

        # Four matplotlib axes: orbit displacement plus X/Y/S tune curves.
        self.fig = Figure(figsize=(10,6))
        self.ax1 = self.fig.add_subplot(211)
        self.ax4 = self.fig.add_subplot(234)
        self.ax5 = self.fig.add_subplot(235)
        self.ax6 = self.fig.add_subplot(236)
        self.fig_obj=[self.ax1,self.ax4,self.ax5,self.ax6]
        obj_label_names=[[' BPM position','Orbit displacement'],['drf','fx'],['drf','fy'],['drf','fs']]
        for i in range(len(self.fig_obj)):
            self.line = self.fig_obj[0].plot([], [], '|')
            self.fig_obj[i].set_xlabel(obj_label_names[i][0], fontsize =11,fontstyle='italic')
            self.fig_obj[i].set_ylabel(obj_label_names[i][1], fontsize =11,fontstyle='italic')
        self.canvas = FigureCanvasTkAgg(self.fig,master=Frame4)
        self.canvas.get_tk_widget().pack(side='top', fill='both', expand=1)
        self.fig.tight_layout()

        def start_mea(button_obj,button_obj2,obj3):
            # Thread wrapper around `MeaChrom`.
            print 'starting mea now!!!!!!'
            global runD,mea_bump_status
            runD = True
            mea_bump_status=False
            t = threading.Thread(target=MeaChrom,args=(button_obj,button_obj2,self.fig_obj,self.fig,self.F1_entry_names,obj3))
            t.start()

        # Matrix measurement / save / load controls.
        self.mea_bump=Button(master=Frame2, text='Measure matrix',bg='#88ACE0',command=lambda: start_thread2(self.mea_button,self.mea_bump))
        self.mea_bump.grid(row =1, column =2, columnspan=1,padx = 5, sticky=E+W)
        self.save_button=Button(master=Frame2, text='Save  matrix',bg='#88ACE0',command=lambda: save_matrix())
        self.save_button.grid(row =1, column =3,columnspan=1,padx = 5, sticky=E+W)
        self.save_button.config(state='disable')
        self.save_button.update()
        self.load_button=Button(master=Frame2, text='Load matrix',bg='#88ACE0',command=lambda: load_matrix())
        self.load_button.grid(row =1, column =4,columnspan=1,padx = 5, sticky=E+W)

        def save_matrix():
            # FILE WRITE PATH: writes the measured inverse response matrix to disk.
            global B
            buf_sign=[[0001,0001],[0002,0002],[0003,0003,0003],[0004,0004,0004]]
            f=asksaveasfilename(defaultextension='.txt')
            print f
            if not f:
                return
            Mres=np.vstack((buf_sign[mat_status-1],B))
            np.savetxt(f,Mres)
##            self.save_button.config(state='disable')
##            self.save_button.update()

        def load_matrix():
            # FILE READ PATH: loads a previously saved matrix and enables the
            # manual correction buttons without touching hardware immediately.
            global B,bump_option,bump_dim,mat_status
            mat_status=bump_option
            for i in range(2):
                self.cor_radiobt[i].config(state='disable')
                self.cor_radiobt[i].update()
            for r in range(3):
                cor_readout[r].delete("1.0",END)
                cor_readout[r].insert(END,' 0 ','a')
                cor_readout[r].tag_config('a', justify='center')
                self.cor_wgt[0][r].config(state='disable')
                self.cor_wgt[0][r].update()
                self.cor_wgt[1][r].config(state='disable')
                self.cor_wgt[1][r].update()
            f=askopenfilename(defaultextension='.txt')
            if not f: # asksaveasfile return `None` if dialog closed with "cancel".
                return
            for r in range(3):
                for c in range(3):
                    F2_matrix_texts[r][c].delete("1.0",END)
                    F2_matrix_texts[r][c].insert(END,'not ready' )
                    F2_matrix_texts[r][c].tag_config('a', justify='center')
            Mres=np.loadtxt(f)
            mat_status=int(Mres[0,0])
##            v.set(mat_status)
            bump_dim=Mres.shape[0]-1
            B=Mres[1:bump_dim+1,:]
            print B
            for r in range(bump_dim):
                self.cor_wgt[0][r].config(state='normal')
                self.cor_wgt[0][r].update()
                self.cor_wgt[1][r].config(state='normal')
                self.cor_wgt[1][r].update()
                for c in range(bump_dim):
                    F2_matrix_texts[r][c].delete("1.0",END)
                    F2_matrix_texts[r][c].insert(END,'%5.3f' % B[r,c] )
                    F2_matrix_texts[r][c].tag_config('a', justify='center')
            F2_rlab[1].config(text='d'+sexts_combination[int(Mres[0,0])-1][0]+' /A')
            F2_rlab[2].config(text='d'+sexts_combination[int(Mres[0,0])-1][1]+' /A')
            if bump_dim==3 :
                F2_rlab[3].config(text='d'+sexts_combination[int(Mres[0,0])-1][2]+' /A')
            else:
                F2_rlab[3].config(text=' ')
            self.save_button.config(state='normal')
            self.save_button.update()
            self.cor_radiobt[0].config(state='normal')
            self.cor_radiobt[0].update()
            v1.set(0)
            if bump_dim==3:
                self.cor_radiobt[1].config(state='normal')
                self.cor_radiobt[1].update()
                v1.set(1)

        # Response-matrix display and bump-mode selection.
        F2_clab_names=['d'+u"\N{GREEK SMALL LETTER Xi}"+'x=1','d'+u"\N{GREEK SMALL LETTER Xi}"+'y=1','d'+u"\N{GREEK SMALL LETTER Xi}"+'s=1']
        F2_rlab_names=['response matrix','dx1 /A','dx2 /A','dx3 /A']
        F2_matrix_texts=[['m00','m01','m02'],['m10','m11','m12'],['m20','m21','m22']]
        bump_options=[('2D',1),('2D(P2)',2),('3D',3),('3D(P2)',4)]
        F2_rlab=[[] for i in  range(4)]
        for r in range(len(F2_rlab_names)):
            Frame2.rowconfigure(r+2, weight=1)
            F2_rlab[r]=Label(master=Frame2, text=F2_rlab_names[r],width=12)
            F2_rlab[r].grid(row=r+2,column=1, columnspan=1,padx = 8,pady =2,sticky=E+W)
        for c in range(len(F2_clab_names)):
            Frame2.columnconfigure(c+1, weight=1)
            Label(master=Frame2, text=F2_clab_names[c],width=12).grid(row=2,column=c+2,columnspan=1,padx = 9, pady = 2,sticky=E+W)
            for r in range(len(F2_matrix_texts)):
                F2_matrix_texts[r][c] = Text(master= Frame2, height=1,width=10)
                F2_matrix_texts[r][c].insert(END,'not ready','a')
                F2_matrix_texts[r][c].grid(row=r+3,column=2+c,columnspan=1,padx = 6, pady = 2,sticky=E+W)
                F2_matrix_texts[r][c].tag_config('a', justify='center')
                show_hidden = False
        display_sexts = Text(master= Frame2, height=1,width=14)
        display_sexts.insert(END,'S1P2,S2P2,S3P2','a')
        display_sexts.grid(row=5,column=0,columnspan=1,padx = 2, pady = 2,sticky=E+W)
        v=IntVar()
        v.set(4)
        global bump_option
        bump_option=4
        for txt, val in bump_options:
            Radiobutton(master=Frame2,text=txt,variable=v,justify='left',command=lambda: SetBump(),value=val).grid(row=val,column=0,columnspan=1,padx = 10, pady =5,sticky=W)
        sexts_combination=[['S1','S2',' '],['S1P2','S2P2', ' '],['S1','S2','S3'],['S1P2','S2P2','S3P2']]
        def SetBump():
            global bump_option
            print v.get()
            bump_option=v.get()
            display_sexts.delete("1.0",END)
            display_sexts.insert(END,sexts_combination[bump_option-1][0]+','+sexts_combination[bump_option-1][1]+','+sexts_combination[bump_option-1][2] )
            display_sexts.tag_config('a', justify='center')

        # Correction controls use the loaded or measured response matrix B.
        global B
        B=np.zeros([3,3])
        self.cor_wgt=[[[],[],[]],[[],[],[]],[[],[],[]],[[],[],[]],[]]
        cor_readout=[[] for i in range(3)]
        Xi_names=['x','y','s']
        Label(master=Frame5, text='d'+u"\N{GREEK SMALL LETTER Xi}"+' readout',width=6,height=2).grid(row=1,column=0, columnspan=1,padx = 1, pady =5,sticky=E+W+N+S)
        for i in range(3):
            self.cor_wgt[0][i]=Button(master=Frame5, text='- '+u"\N{GREEK SMALL LETTER Xi}"+Xi_names[i],width=2,bg='#88ACE0',command=lambda j=i :  change_sext_cur(j*2))
            self.cor_wgt[0][i].grid(row =0, column =2+i*3,padx=1,pady=5,sticky=E+W)
            self.cor_wgt[2][i]=StringVar()
            self.cor_wgt[3][i]=Entry(master=Frame5,textvariable=self.cor_wgt[2][i],justify='center',width=3).grid(row=0,column=3+i*3,ipadx=2,ipady=1,padx=0,pady=5,sticky=E+W)
            self.cor_wgt[2][i].set('0.0')
            self.cor_wgt[1][i]=Button(master=Frame5, text='+'+u"\N{GREEK SMALL LETTER Xi}"+Xi_names[i],width=2,bg='#88ACE0',command=lambda j=i: change_sext_cur(j*2+1))
            self.cor_wgt[1][i].grid(row =0, column = 4+i*3,padx=1,pady=5,sticky=E+W)
            self.cor_wgt[0][i].config(state='disable')
            self.cor_wgt[0][i].update()
            self.cor_wgt[1][i].config(state='disable')
            self.cor_wgt[1][i].update()
            cor_readout[i]= Text(master= Frame5, height=1,width=7)
            cor_readout[i].insert(END,' 0 ','a')
            cor_readout[i].grid(row=1,column=3+i*3,ipadx=2,ipady=2,padx=0,pady=5,sticky=E+W)
            cor_readout[i].tag_config('a', justify='center')
        cor_list=[('2D cor',0),('3D cor',1)]
        self.cor_radiobt=[[],[]]
        v1=IntVar()
        v1.set(1)
        global flag2D3D
        flag2D3D=False
        for txt, valcor in cor_list:
            self.cor_radiobt[valcor]=Radiobutton(master=Frame5,text=txt,variable=v1,justify='left',command=lambda: SetCor(),value=valcor,width=5,state='disable')
            self.cor_radiobt[valcor].grid(row=0,column=valcor,columnspan=1,padx = 0, pady =5,sticky=W)

        def SetCor():
            # Switch between full 3D correction and the upper-left 2x2 block.
            global B, cor_option,mat_status, Bbuf,flag2D3D
            cor_option=v1.get()
            if  cor_option==0 :
                self.cor_wgt[0][2].config(state='disable')
                self.cor_wgt[0][2].update()
                self.cor_wgt[1][2].config(state='disable')
                self.cor_wgt[1][2].update()
                Bbuf=B
                D=np.linalg.inv(B)
                D=D[0:2,0:2]
                B=np.linalg.inv(D)
                for r in range(3):
                    cor_readout[r].delete("1.0",END)
                    cor_readout[r].insert(END,' 0 ','a')
                    cor_readout[r].tag_config('a', justify='center')
                    for c in range(3):
                        if r>1 or c>1:
                            F2_matrix_texts[r][c].delete("1.0",END)
                            F2_matrix_texts[r][c].insert(END,'not ready' )
                            F2_matrix_texts[r][c].tag_config('a', justify='center')
                        else:
                            F2_matrix_texts[r][c].delete("1.0",END)
                            F2_matrix_texts[r][c].insert(END,'%5.3f' % B[r,c] )
                            F2_matrix_texts[r][c].tag_config('a', justify='center')
                print B
                flag2D3D=True
            elif  cor_option==1and flag2D3D:
                # TYPO/RISK: `1and` relies on Python tokenization; it is valid
                # but hard to read and easy to misinterpret.
                self.cor_wgt[0][2].config(state='normal')
                self.cor_wgt[0][2].update()
                self.cor_wgt[1][2].config(state='normal')
                self.cor_wgt[1][2].update()
                B=Bbuf
                for r in range(3):
                    for c in range(3):
                        F2_matrix_texts[r][c].delete("1.0",END)
                        F2_matrix_texts[r][c].insert(END,'%5.3f' % B[r,c] )
                        F2_matrix_texts[r][c].tag_config('a', justify='center')
                print B

        def start_thread2(var1,var2):
            # Thread wrapper around response-matrix measurement.
            global runD,mea_bump_status,bump_option
            runD = True
            mea_bump_status=True
            t2 = threading.Thread(target=start_bump,args=(var1,var2))
            t2.start()

        def start_bump(obj,obj2):
            # Measure the response matrix by stepping chosen sextupole families,
            # calling `MeaChrom` twice per dimension, then inverting A^T.
            #
            # MACHINE WRITE PATH: changes sextupole currents and indirectly RF /
            # feedback / orbit through `MeaChrom`.
            print 'starting thread now!!!!!!'
            global runD,mea_bump_status,B,bump_option,bump_dim,mat_status
            mea_end=False

            self.load_button.config(state='disable')
            self.load_button.update()
            self.save_button.config(state='disable')
            self.save_button.update()
            for i in range(2):
                self.cor_radiobt[i].config(state='disable')
                self.cor_radiobt[i].update()
            for r in range(3):
                cor_readout[r].delete("1.0",END)
                cor_readout[r].insert(END,' 0 ','a')
                cor_readout[r].tag_config('a', justify='center')
                self.cor_wgt[0][r].config(state='disable')
                self.cor_wgt[0][r].update()
                self.cor_wgt[1][r].config(state='disable')
                self.cor_wgt[1][r].update()
                for c in range(3):
                    F2_matrix_texts[r][c].delete("1.0",END)
                    F2_matrix_texts[r][c].insert(END,'not ready' )
                    F2_matrix_texts[r][c].tag_config('a', justify='center')
            nsextP2=[[pvS1P2],[pvS2P2K,pvS2P2L],[pvS3P2]]
            nsextS=[[pvS1P1,pvS1P2],[pvS2P1,pvS2P2K,pvS2P2L],[pvS3P1,pvS3P2]]
            if bump_option==1 or bump_option==2:
                bump_dim=2
            else:
                bump_dim=3
            print 'dimension of bump matrix is :',bump_dim
            F2_rlab[1].config(text='d'+sexts_combination[bump_option-1][0]+' /A')
            F2_rlab[2].config(text='d'+sexts_combination[bump_option-1][1]+' /A')
            if bump_dim==3 :
                F2_rlab[3].config(text='d'+sexts_combination[bump_option-1][2]+' /A')
            else:
                F2_rlab[3].config(text=' ')
            A=np.zeros([bump_dim,bump_dim])
            for i in range(bump_dim):
                if runD and mea_bump_status:
                    if bump_option==1 or bump_option==3:
                        nsext=nsextS
                    else:
                        nsext=nsextP2
                    print nsext[i][0].get()
                    for sv in nsext[i]:
                        sv.put(sv.get()-1)
                    Xi_mea=MeaChrom(obj,obj2,self.fig_obj,self.fig,self.F1_entry_names,self.cor_wgt)
                    time.sleep(2)
                    if mea_bump_status and runD:
                        Xibuf1=Xi_mea
                        print Xibuf1
                        for sv in nsext[i]:
                            sv.put(sv.get()+1)
                        Xi_mea=MeaChrom(obj,obj2,self.fig_obj,self.fig,self.F1_entry_names,self.cor_wgt)
                        time.sleep(2)
                    if mea_bump_status  and runD:
                        Xibuf2=Xi_mea
                        print Xibuf2
                        A[i,:]=(np.array(Xibuf2)-np.array(Xibuf1))[0:bump_dim]
                        print A[i,:]
                        time.sleep(2)
                else:
                    break
            if runD and mea_bump_status:
                print A
                B=np.linalg.inv(A.T)
                print B
                for r in range(bump_dim):
                    self.cor_wgt[0][r].config(state='normal')
                    self.cor_wgt[0][r].update()
                    self.cor_wgt[1][r].config(state='normal')
                    self.cor_wgt[1][r].update()
                    for c in range(bump_dim):
                        F2_matrix_texts[r][c].delete("1.0",END)
                        F2_matrix_texts[r][c].insert(END,'%5.3f' % B[r,c] )
                        F2_matrix_texts[r][c].tag_config('a', justify='center')
                self.save_button.config(state='normal')
                self.save_button.update()
                mea_bump_status=False
                mea_end =True
                mat_status=bump_option
                self.load_button.config(state='normal')
                self.load_button.update()
                self.save_button.config(state='normal')
                self.save_button.update()
                self.cor_radiobt[0].config(state='normal')
                self.cor_radiobt[0].update()
                if bump_option>2:
                    self.cor_radiobt[1].config(state='normal')
                    self.cor_radiobt[1].update()
                v1.set(bump_dim-2)

            else:
                A=np.NAN
                print A
                B=A
                for r in range(3):
                    for c in range(3):
                        F2_matrix_texts[r][c].delete("1.0",END)
                        F2_matrix_texts[r][c].insert(END,'    ')
                self.cor_wgt=self.cor_wgt
                if not mea_end   :
                    for i in range(bump_dim):
                        self.cor_wgt[0][i].config(state='disable')
                        self.cor_wgt[0][i].update()
                        self.cor_wgt[1][i].config(state='disable')
                        self.cor_wgt[1][i].update()
                for i in range(2):
                    self.cor_radiobt[i].config(state='disable')
                    self.cor_radiobt[i].update()
            self.load_button.config(state='normal')
            self.load_button.update()
            obj.config(state= 'normal')
            obj.update()
            obj2.config(state= 'normal')
            obj2.update()

        def change_sext_cur(Nth):
            # Manual correction buttons. The GUI updates the requested
            # chromaticity readout first, then applies the inverse matrix.
            #
            # MACHINE WRITE PATH: calls `set_all_sexts`.
            bt_M=self.cor_wgt
            rdvar=cor_readout
            print bt_M
            print bt_M[2][0].get(),bt_M[2][1].get(),bt_M[2][2].get()
            if Nth==0:
                print 'decrease xi_x'
                dchrom=np.matrix([[-float(bt_M[2][0].get())],[0],[0]])
                xx=float(rdvar[0].get("1.0",END))-float(bt_M[2][0].get())
                rdvar[0].delete("1.0",END)
                rdvar[0].insert(END,'%5.3f' % xx )
                print dchrom
                print bt_M[2][0].get()
            elif Nth==1:
                print 'increase xi_x'
                dchrom=np.matrix([[float(bt_M[2][0].get())],[0],[0]])
                xx=float(rdvar[0].get("1.0",END))+float(bt_M[2][0].get())
                rdvar[0].delete("1.0",END)
                rdvar[0].insert(END,'%5.3f' % xx )
                print bt_M[2][0].get()
            elif Nth==2:
                print 'decrease xi_y'
                dchrom=np.matrix([[0],[-float(bt_M[2][1].get())],[0]])
                xx=float(rdvar[1].get("1.0",END))-float(bt_M[2][1].get())
                rdvar[1].delete("1.0",END)
                rdvar[1].insert(END,'%5.3f' % xx )
                print bt_M[2][1].get()
            elif Nth==3:
                print 'increase xi_y'
                dchrom=np.matrix([[0],[float(bt_M[2][1].get())],[0]])
                xx=float(rdvar[1].get("1.0",END))+float(bt_M[2][1].get())
                rdvar[1].delete("1.0",END)
                rdvar[1].insert(END,'%5.3f' % xx )
                print bt_M[2][1].get()
            elif Nth==4:
                print 'decrease xi_s'
                dchrom=np.matrix([[0],[0],[-float(bt_M[2][2].get())]])
                xx=float(rdvar[2].get("1.0",END))-float(bt_M[2][2].get())
                rdvar[2].delete("1.0",END)
                rdvar[2].insert(END,'%5.4f' % xx )
                print bt_M[2][2].get()
            elif Nth==5:
                print 'increase xi_s'
                dchrom=np.matrix([[0],[0],[float(bt_M[2][2].get())]])
                xx= float(rdvar[2].get("1.0",END))+float(bt_M[2][2].get())
                rdvar[2].delete("1.0",END)
                rdvar[2].insert(END,'%5.4f' % xx )
                print bt_M[2][2].get()
            set_all_sexts(dchrom)

        # Side buttons: save current settings, reset, open sextupole scan, stop.
        self.quit_button=Button(master=Frame3, text='Save',fg = 'red',font=('bold'),width=10,command=lambda: save_setting()).grid(row =2, column = 0, padx = 10, pady = 10)
        self.quit_button=Button(master=Frame3, text='Quit',fg = 'red',font=('bold'),width=10,command=lambda: self.closeall(self.master)).grid(row =4, column = 0, padx = 10, pady = 10)
        reset_bump=Button(master=Frame3, text='reset',fg = 'blue',font=('bold'),width=10,command=lambda: set_all2ini(cor_readout,self.mea_button,self.mea_bump)).grid(row =3, column = 0, padx = 10, pady = 10)
        self.sext_scan=Button(master=Frame3, text='sext scan',font=('bold'),width=10,command=lambda: self.OK(self.master))
        self.sext_scan.grid(row =1, column = 0, padx = 10, pady = 10)
        self.stop_w1mea=Button(master=Frame3, text='Stop',fg = '#F5785A',font=('bold'),width=10,command=lambda: self.stop_mea())
        self.stop_w1mea.grid(row =0, column = 0, padx = 10, pady = 10)

    def stop_mea(self):
            global runD,mea_bump_status
            mea_bump_status=False
            runD=False
            print 'stop................'
##    def close_all(self):
##        self.quit()
    def closeall(self, root):
        root.quit()
    def OK(self, root):
        # Opens the secondary sextupole-scan window and disables some controls
        # in the main window until the child window is closed.
        self.mea_button.config(state='disable')
        self.mea_button.update()
        self.mea_bump.config(state='disable')
        self.mea_bump.update()
        self.stop_w1mea.config(state='disable')
        self.stop_w1mea.update()
        for i in range(3):
            self.cor_wgt[0][i].config(state='disable')
            self.cor_wgt[0][i].update()
            self.cor_wgt[1][i].config(state='disable')
            self.cor_wgt[1][i].update()
        self.sext_scan.config(state='disable')
        self.sext_scan.update()
        new = self.newWindow()
##        root.wait_window(new)
##        root.destroy()

    def newWindow(self):
        # Secondary window for polynomial sextupole scans and offline scan-table
        # generation. This is a mixture of measurement control and file output.
        def done(newWindow):
            self.sext_scan.config(state='normal')
            self.sext_scan.update()
            self.mea_button.config(state='normal')
            self.mea_button.update()
            self.mea_bump.config(state='normal')
            self.mea_bump.update()
            self.stop_w1mea.config(state='normal')
            self.stop_w1mea.update()
            newWindow.destroy()

        newWindow = Toplevel()
##        newWindow.tkraise()
        Frame20 = Frame(newWindow, bg="#B6AFA9",width=150, height=100)
        Frame20.grid(row = 0, column = 0, rowspan = 1, columnspan = 5, sticky = W+E+N+S)
        Frame20.pack_propagate(0)
        stopw2_button=Button(Frame20 , text='Stop ',width=10,command=lambda: stop_w2()).grid(row =0, column = 0,columnspan=2, padx = 5, pady = 5)
        bb = Button(Frame20 , text = "Close window", command = lambda: done(newWindow))
        bb.grid(row =0, column = 2, columnspan=2,padx = 5, pady = 5,sticky=E+W)
        Frame21 = Frame(newWindow, bg="#A2B5CD",width=150, height=100)
        Frame21.grid(row = 1, column = 0, rowspan = 3, columnspan = 5, sticky = W+E+N+S)
        Frame21.pack_propagate(0)
        Frame22 = Frame(newWindow, bg="#A4DCD1",width=200, height=150)
        Frame22.grid(row =8, column = 0, rowspan = 9, columnspan = 5, sticky = W+E+N+S)
        Frame22.pack_propagate(0)

        tableheight = 4
        tablewidth = 2
        Label(Frame21, text='Poly Matrix').grid(row=1,column=1,columnspan=1,padx = 5, pady = 5)

        entries =[[ [] for i in range(tablewidth)] for j in range(tableheight) ]
        entries_num=[[-2,2],[-4,0],[-2,2],[-2,2]]
        labs_names =[['S1','S2P1','S2P2','S3'],['dImin /A','dImax /A']]
        labs =[[[],[],[],[]],[[],[]]]
        for row in range(tableheight):
            for column in range(tablewidth):
                entries[row][column]=StringVar()
                Entry(Frame21, textvariable=entries[row][column],justify='center',width=8).grid(row=row+2,column=column+1,padx = 5, pady = 5,sticky=E+W)
                entries[row][column].set(entries_num[row][column])
        for row in range(tableheight):
                labs[0][row] = Label(Frame21 ,text=labs_names[0][row],width=6)
                labs[0][row].grid(row=row+2, column=0,padx = 5, pady = 5)
        for column in range(tablewidth):
                labs[1][column] = Label(Frame21,text=labs_names[1][column],width=8)
                labs[1][column].grid(row=1, column=column+1,padx = 5, pady = 5)
        poly_bump=Button(Frame21, text='Measure',command=lambda: start_thread3(self.mea_button,self.mea_bump))
        poly_bump.grid(row =3, column = 3, columnspan=2,rowspan=2,padx = 20, pady = 5,sticky=E+W)

        def start_thread3(var1,var2):
            global runD,mea_bump_status, mea_poly_status
            runD = True
            mea_bump_status=False
            t3 = threading.Thread(target=start_poly,args=(var1,var2))
            t3.start()

        def stop_w2():
            global runD,mea_bump_status,mea_poly_status, scan4D_status
            mea_poly_status=False
            scan4D_status = False
            runD=False
            print 'stop................'

        def start_poly(obj,obj2):
            # Polynomial response measurement for selected sextupoles.
            #
            # MACHINE WRITE PATH: intended to change sextupole currents, but the
            # helper `setcur` referenced below is missing from this file.
            #
            # FILE WRITE PATH: saves raw bump data and polynomial coefficient
            # matrices into the chosen directory.
            global runD,fine_bump_status
            mea_poly_status=True
            folder_dir=askdirectory(title='choose a directory for the fine bump data')
            if not folder_dir:
                return
            print folder_dir
            paras=entries
            Sextlist=[[pvS1P1,pvS1P2],[pvS2P1],[pvS2P2],[pvS3P1,pvS3P2]]
            M=np.zeros([3,len(Sextlist)*2])
            print '\n Chromaticity bump setting : 3D bump '
            for i in range(len( Sextlist)):
                if mea_poly_status and runD:
                    ini_cur=Sextlist[i][0].get()
                    SI=[ini_sext[0],ini_sext[2],ini_sext[3],ini_sext[5]]
                    fitpoints=int(paras[i][1].get())-int(paras[i][0].get()) +1
                    print fitpoints
                    bumpdataS=np.zeros((fitpoints,len(Sextlist)+3))
                    print 'measuring the response of'+str(i+1)
                    irange=np.linspace(float(paras[i][0].get())+SI[i],float(paras[i][1].get())+SI[i],fitpoints)
                    print irange
                    kk=0
                    for cur in irange:
                        if mea_poly_status and runD:
                            SI[i]=cur
                            if kk==0:
                                setcur(Sextlist[i],cur)
                                ##set_Isextupole_slowly( Sextlist[i],cur)
                                ##setcur(Sextlist[i],cur)
                            else:
                                setcur(Sextlist[i],cur)
                                ##set_Isextupole_slowly( Sextlist[i],Isp)
                            Xi_mea=MeaChrom(obj,obj2,self.fig_obj,self.fig,self.F1_entry_names,self.cor_wgt)
                            if mea_poly_status and runD:
                                bumpdataS[kk,:]=[SI[0],SI[1],SI[2],SI[3],Xi_mea[0],Xi_mea[1],Xi_mea[2]]
                            kk=kk+1
                        else:
                            break
                        print 'break start ***************************'
                        if mea_poly_status and runD:
                            np.savetxt(folder_dir+'/'+'bumpdataS'+str(i+1)+'.txt',bumpdataS)
                            # BUG/RISK: index expression uses a float and is
                            # almost certainly wrong in Python 2 and Python 3.
                            bumpdataS=bumpdataS-bumpdataS[-float(paras[i][1].get())-1,:]
                            Sfit=(curve_fit(bumppolyfit,bumpdataS[:,i],bumpdataS[:,4]),curve_fit(bumppolyfit,bumpdataS[:,i],bumpdataS[:,5]),curve_fit(bumppolyfit,bumpdataS[:,i],bumpdataS[:,6]))
                            (SfitXterms,SfitYterms,SfitSterms)=(np.poly1d(np.append(Sfit[0][0],0)),np.poly1d(np.append(Sfit[1][0],0)),np.poly1d(np.append(Sfit[2][0],0)))
                            print SfitXterms, "\n\n", SfitYterms,"\n\n",SfitSterms,"\n\n"
    ##                        for sn in Sextlist[i]:
    ##                            set_Isextupole_slowly( sn,ini_cur)
                            for jj in range(3):
                                    M[jj,i*2]=Sfit[jj][0][-2]
                                    M[jj,i*2+1]=Sfit[jj][0][-1]
                            print 'coeffecient dXi_X vs dS1 ',Sfit[0][0]
                            print 'coeffecient dXi_Y vs dS1 ',Sfit[1][0]
                            print 'coeffecient dXi_S vs dS1 ',Sfit[2][0]
                            print bumpdataS
                else:
                    print 'buff ***************************'
                    break
            print 'break  end'
##            print M
            np.savetxt(folder_dir+'/'+'ploy_co_mat.txt',M)

        Label(Frame22, text='scan setupoles').grid(row=0,column=3,columnspan=1,padx = 5, pady = 5)
        Scanentries =[[ [] for i in range(tablewidth+1)] for j in range(tableheight) ]
        Scanentries_num=[[-2,2,5],[-4,0,5],[-2,2,5],[-2,2,5]]
        Scanlabs_names =[['S1','S2P1','S2P2','S3'],['dImin /A','dImax /A', 'N']]
        Scanlabs =[[[],[],[],[]],[[],[], []]]
        for row in range(tableheight):
            for column in range(tablewidth+1):
                Scanentries[row][column]=StringVar()
                Entry(Frame22, textvariable=Scanentries[row][column],justify='center',width=8).grid(row=row+4,column=column+2,padx = 5, pady = 5,sticky=E+W)
                Scanentries[row][column].set(Scanentries_num[row][column])
        for row in range(tableheight):
                Scanlabs[0][row] = Label(Frame22,text=labs_names[0][row],width=10)
                Scanlabs[0][row].grid(row=row+4, column=0,padx = 5, pady = 5)
        for column in range(tablewidth):
                Scanlabs[1][column] = Label(Frame22,text=Scanlabs_names[1][column],width=8)
                Scanlabs[1][column].grid(row=3, column=column+2,padx = 5, pady = 5)
        scan_sexts=Button(Frame22 , text='Scan', width=5,command=lambda: start_thread4D())
        scan_sexts.grid(row =1, column = 4, columnspan=1,padx = 5, pady = 5,sticky=E+W)
##        stopscan_sexts=Button(Frame22, text='Stop',width=5,command=lambda: stop_w2()).grid(row =8, column = 3,columnspan=2, padx = 5, pady = 5)
        Label(Frame22,text='d'+u"\N{GREEK SMALL LETTER Xi}"+'x range',width=10).grid(row=1, column=0,padx = 5, pady = 5)
        Label(Frame22,text='d'+u"\N{GREEK SMALL LETTER Xi}"+'y range',width=10).grid(row=2, column=0,padx = 5, pady = 5)
        dxi=[[ [] for i in range(2)] for j in range(2) ]
        dxi_num=[['-2','2'],['-2','2' ]]
        for row in range(2):
            for column in range(2):
                dxi[row][column]=StringVar()
                Entry(Frame22, textvariable=dxi[row][column],justify='center',width=8).grid(row=row+1,column=column+2,padx = 5, pady = 5,sticky=E+W)
                dxi[row][column].set(dxi_num[row][column])

        def start_thread4D():
            global scan4D_status
            scan4D_status = True
            t4 = threading.Thread(target=gen_scan_tab,args=())
            t4.start()
##        def stop4D():
##            global scan4D_status
##            scan4D_status = False

        def gen_scan_tab():
            # Generates a list of candidate sextupole settings from a previously
            # measured polynomial matrix, then logs diagnostics for each entry.
            #
            # In the current source, the actual sextupole write commands are
            # commented out, so this section is read-only with respect to EPICS.
            #
            # FILE WRITE PATH: creates a timestamped output directory and writes
            # candidate settings plus logged diagnostic data.
            naa= int(Scanentries[0][2].get())
            print naa
            nbb=int(Scanentries[1][2].get())
            ncc= int(Scanentries[2][2].get())
            ndd=int(Scanentries[2][2].get())
            print Scanentries[0][0].get()
            Sa=np.linspace(float(Scanentries[0][0].get()),float(Scanentries[0][1].get()),naa)
            print Sa
            Sb=np.linspace(float(Scanentries[1][0].get()),float(Scanentries[1][1].get()),nbb)
            # BUG/RISK: Sc and Sd use the min value twice, so no real scan occurs.
            Sc=np.linspace(float(Scanentries[2][0].get()),float(Scanentries[2][0].get()),ncc)
            Sd=np.linspace(float(Scanentries[3][0].get()),float(Scanentries[3][0].get()),ndd)
            fname=askopenfilename(title='choose the fine bump data')
            if not fname:
                print 'to return'
                return
            M=np.loadtxt(fname)
            sext_setting=np.array([])
            nrow=0
            for i in range(naa):
                for j in range(nbb):
                    for k in range(ncc):
                        for l in range(ndd):
                            Dxix=Sa[i]**2*M[0,0]+Sa[i]*M[0,1]+Sb[j]**2*M[0,2]+Sb[j]*M[0,3]+Sc[k]**2*M[0,4]+Sc[k]*M[0,5]+Sd[l]**2*M[0,6]+Sd[l]*M[0,7]
                            Dxiy=Sa[i]**2*M[1,0]+Sa[i]*M[1,1]+Sb[j]**2*M[1,2]+Sb[j]*M[1,3]+Sc[k]**2*M[1,4]+Sc[k]*M[1,5]+Sd[l]**2*M[1,6]+Sd[l]*M[1,7]
                            if Dxix>float(dxi[0][0].get()) and Dxix<float(dxi[0][1].get()) and Dxiy>float(dxi[1][0].get()) and Dxiy<float(dxi[1][1].get()) :
                                sext_setting=np.append(sext_setting,np.array([Sa[i]+ini_sext[0],Sa[i]+ini_sext[1],Sb[j]+ini_sext[2],Sc[k]+ini_sext[3],Sd[l]+ini_sext[4],Sd[l]+ini_sext[5]]))
                                nrow+=1
            if nrow>1:

                sext_setting=np.reshape(sext_setting,(nrow,6))
                print sext_setting.shape
                print nrow
                current_time=time.strftime("%H:%M:%S_%d%b%Y")
                script_dir=os.getcwd()

                file_location=script_dir+'/'+current_time
                if not os.path.exists(file_location):
                    os.makedirs(file_location)
                np.savetxt(file_location+'/'+'sext_setting.txt',sext_setting)
                I=sext_setting
                for ii in range(nrow):
            ##        set_Isextupole_slowly('S3P1RP:setCur',I[ii,4],pvS3P1.get())
            ##        set_Isextupole_slowly('S3P2RP:setCur',I[ii,5],pvS3P2.get())
            ##        set_Isextupole_slowly('S2P1RP:setCur',I[ii,2],pvS2P1.get())
            ##        set_Isextupole_slowly('S2P2RP:setCur',I[ii,3],pvS2P2.get())
            ##        set_Isextupole_slowly('S1P1RP:setCur',I[ii,0],pvS1P1.get())
            ##        set_Isextupole_slowly('S1P2RP:setCur',I[ii,1],pvS1P2.get())
                    if scan4D_status:
                        cnt=0
                        ltdata=np.array([[pvS1P1.get(),pvS2P1.get(),pvS2P2.get(),pvS3P1.get(),time.time(),\
                            pvE.get(),pvcur.get(),QPD1HS.get(),QPD1VS.get(),QPD0HS.get(),QPD0VS.get(),\
                            pvfreqX.get(),pvfreqY.get(),pvfreqS.get(),pvorbit.get(),pvwhitenosie.get()]])
                        while cnt< 10:
                            time.sleep(0.5)
                            cnt+=1
                            ltdata=np.append(ltdata,[[pvS1P1.get(),pvS2P1.get(),pvS2P2.get(),pvS3P1.get(),time.time(),\
                            pvE.get(),pvcur.get(),QPD1HS.get(),QPD1VS.get(),QPD0HS.get(),QPD0VS.get(),\
                            pvfreqX.get(),pvfreqY.get(),pvfreqS.get(),pvorbit.get(),pvwhitenosie.get()]],axis=0)
                        fn=file_location+'/'+str(round(pvS1P1.get(),2))+'s'+str(round(pvS2P1.get(),2))+'s'+str(round(pvS2P2.get(),2))+'s'+str(round(pvS3P1.get(),2))+'s.dat'
                        print fn
                        np.savetxt(fn,ltdata)
                    else:
                        print  'stop  scan'
                        break
            else:
                print 'not suitable sextupole setting'

    def close_windows(self):
        self.master.destroy()

# GUI root is constructed at import time. This is another startup blocker for
# headless/offline use and should be moved behind `main()` in the later port.
root = Tk()

def main():
    app = mainwindow(root)
    root.mainloop()

if __name__ == '__main__':
    main()
