# -*- coding: utf-8 -*-

import MirrorControlCalculate
import tkinter as tk
from tkinter import messagebox

calc = MirrorControlCalculate.MCcalc()

window = tk.Tk()
window.title('Mirror Movement Calculator')

OffsetX = tk.DoubleVar(window)
AngleX = tk.DoubleVar(window)
Mirror1X = tk.DoubleVar(window)
Mirror2X = tk.DoubleVar(window)
Steps1X = tk.DoubleVar(window)
Steps2X = tk.DoubleVar(window)

OffsetY = tk.DoubleVar(window)
AngleY = tk.DoubleVar(window)
Mirror1Y = tk.DoubleVar(window)
Mirror2Y = tk.DoubleVar(window)
Steps1Y = tk.DoubleVar(window)
Steps2Y = tk.DoubleVar(window)

def calculateX():
    try:
        m1, m2 = calc.to_mirror_angles(OffsetX.get(), AngleX.get(), axis=0)
        Mirror1X.set(round(m1,2))
        Mirror2X.set(round(m2,2))
        s1, s2 = calc.angle_to_steps(m1, m2, axis=0)
        Steps1X.set(round(s1,2))
        Steps2X.set(round(s2,1))
    except tk.TclError:
        messagebox.showerror('Calculation Error', 'Please enter numbers only!')

def calculateY():
    try:
        m1, m2 = calc.to_mirror_angles(OffsetY.get(), AngleY.get(), axis=1)
        Mirror1Y.set(round(m1,2))
        Mirror2Y.set(round(m2,2))
        s1, s2 = calc.angle_to_steps(m1, m2, axis=1)
        Steps1Y.set(round(s1,2))
        Steps2Y.set(round(s2,2))
    except tk.TclError:
        messagebox.showerror('Calculation Error', 'Please enter numbers only!')

def calculate_all():
    calculateX()
    calculateY()

def callbackX(event):
    calculateX()
    
def callbackY(event):
    calculateY()


OffsetXLbl = tk.Label(window, text='Vertical offset (mm)')
OffsetXLbl.grid(column=0, row=0)

OffsetXEtr = tk.Entry(window, width=20, justify = tk.RIGHT, textvariable = OffsetX)
OffsetXEtr.bind('<Return>', callbackX)
OffsetXEtr.grid(column=0, row=1, padx=10)

OffsetYLbl = tk.Label(window, text='Horizontal offset (mm)')
OffsetYLbl.grid(column=3, row=0)

OffsetYEtr = tk.Entry(window, width=20, justify = tk.RIGHT, textvariable = OffsetY)
OffsetYEtr.bind('<Return>', callbackY)
OffsetYEtr.grid(column=3, row=1, padx=50)

AngleXLbl = tk.Label(window, text='Vertical Angle (µrad)\nat undulator centre')
AngleXLbl.grid(column=1, row=0)

AngleXEtr = tk.Entry(window, width=20, justify = tk.RIGHT, textvariable = AngleX)
AngleXEtr.bind('<Return>', callbackX)
AngleXEtr.grid(column=1, row=1, padx=50)

AngleYLbl = tk.Label(window, text='Horizontal Angle (µrad)\nat undulator centre')
AngleYLbl.grid(column=4, row=0)

AngleYEtr = tk.Entry(window, width=20, justify = tk.RIGHT, textvariable = AngleY)
AngleYEtr.bind('<Return>', callbackY)
AngleYEtr.grid(column=4, row=1, padx=10)


Mirror1XLbl = tk.Label(window, text='Vertical Angle (µrad)\nof mirror 1')
Mirror1XLbl.grid(column=0, row=3)

Mirror1XEtr = tk.Label(window, width=17, anchor='e', textvariable = Mirror1X, bg='white', fg='black', relief = tk.SUNKEN, bd=1)
Mirror1XEtr.grid(column=0, row=4)

Mirror1YLbl = tk.Label(window, text='Horizontal Angle (µrad)\nof mirror 1')
Mirror1YLbl.grid(column=3, row=3)

Mirror1YEtr = tk.Label(window, width=17, anchor='e', textvariable = Mirror1Y, bg='white', fg='black', relief = tk.SUNKEN, bd=1)
Mirror1YEtr.grid(column=3, row=4)

Mirror2XLbl = tk.Label(window, text='Vertical Angle (µrad)\nof mirror 2')
Mirror2XLbl.grid(column=1, row=3)

Mirror2XEtr = tk.Label(window, width=17, anchor='e', textvariable = Mirror2X, bg='white', fg='black', relief = tk.SUNKEN, bd=1)
Mirror2XEtr.grid(column=1, row=4)

Mirror2YLbl = tk.Label(window, text='Horizontal Angle (µrad)\nof mirror 2')
Mirror2YLbl.grid(column=4, row=3)

Mirror2YEtr = tk.Label(window, width=17, anchor='e', textvariable = Mirror2Y, bg='white', fg='black', relief = tk.SUNKEN, bd=1)
Mirror2YEtr.grid(column=4, row=4)


Steps1XLbl = tk.Label(window, text='Steps to move\n(mirror 1, vertical)')
Steps1XLbl.grid(column=0, row=5)

Steps1XEtr = tk.Label(window, width=17, anchor='e', textvariable = Steps1X, bg='white', fg='black', relief = tk.SUNKEN, bd=1)
Steps1XEtr.grid(column=0, row=6)

Steps1YLbl = tk.Label(window, text='Steps to move\n(mirror 1, horizontal)')
Steps1YLbl.grid(column=3, row=5)

Steps1YEtr = tk.Label(window, width=17, anchor='e', textvariable = Steps1Y, bg='white', fg='black', relief = tk.SUNKEN, bd=1)
Steps1YEtr.grid(column=3, row=6)

Steps2XLbl = tk.Label(window, text='Steps to move\n(mirror 2, vertical)')
Steps2XLbl.grid(column=1, row=5)

Steps2XEtr = tk.Label(window, width=17, anchor='e', textvariable = Steps2X, bg='white', fg='black', relief = tk.SUNKEN, bd=1)
Steps2XEtr.grid(column=1, row=6)

Steps2YLbl = tk.Label(window, text='Steps to move\n(mirror 2, horizontal)')
Steps2YLbl.grid(column=4, row=5)

Steps2YEtr = tk.Label(window, width=17, anchor='e', textvariable = Steps2Y, bg='white', fg='black', relief = tk.SUNKEN, bd=1)
Steps2YEtr.grid(column=4, row=6)

XBtn = tk.Button(window, width = 20, text='calculate!', command=calculateX)
XBtn.grid(column=0, row=2, columnspan=2, pady=5)

YBtn = tk.Button(window, width = 20, text='calculate!', command=calculateY)
YBtn.grid(column=3, row=2, columnspan=2, pady=5)


spaceLbl = tk.Label(window)
spaceLbl.grid(column=0, row=7)

reloadBtn = tk.Button(window, text='Reload calibration from file', command=calc.load_calibration)
reloadBtn.grid(column=4, row=8, pady=10, padx=5)

calcAllBtn = tk.Button(window, text='Recalculate all', command=calculate_all)
calcAllBtn.grid(column=4, row=9, pady=10, padx=5)

XBtn.lower()
AngleXEtr.lower()
OffsetXEtr.lower()

window.mainloop()
