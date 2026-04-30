# -*- coding: utf-8 -*-

import tkinter as tk
import MirrorControlCalculate
from time import sleep

calc = MirrorControlCalculate.MCcalc()

window = tk.Tk()
window.title('Mirror Control')

l = tk.Label(window, bg='white', fg='black', width=20, text='empty')
l.grid(row=0, column=0)
 
def print_selection(v):
    l.config(text='you have selected ' + v)

OffsetX = tk.DoubleVar(window)
OffsetXScl = tk.Scale(window, label='Vertical offset (mm)', from_=-10, to=10,
                      orient=tk.HORIZONTAL, length=400, showvalue=1 ,tickinterval=2,
                      resolution=0.01, variable=OffsetX, command=print_selection)
OffsetXScl.grid(row=1, column = 1)

#OffsetXActualEtr = tk.Entry()

#def validate(action, value_if_allowed,
#                      ):
#        if value_if_allowed:
#            try:
#                float(value_if_allowed)
#                return True
#            except ValueError:
#                return False
#        else:
#            return False
#
#vcmd = (window.register(validate), '%P')

#OffsetXEtr = tk.Entry(textvariable=OffsetX, validate='key', validatecommand=vcmd)
#OffsetXEtr.grid(row=1, column=2)

def toggle_resolution():
    if OffsetXScl['resolution'] < 0.05:
        OffsetXScl.configure(resolution=0.1)
    else:
        OffsetXScl.configure(resolution=0.01)
    print_selection(str(OffsetXScl.get()))

toggleResOXBtn = tk.Button(window, text='Toggle resolution', command=toggle_resolution)
toggleResOXBtn.grid(row=1, column = 0)

OffsetY = tk.DoubleVar(window)
OffsetYScl = tk.Scale(window, label='Horizontal offset (mm)', from_=-10, to=10,
                      orient=tk.HORIZONTAL, length=400, showvalue=1 ,tickinterval=2,
                      resolution=0.01, variable=OffsetY, command=print_selection)
OffsetYScl.grid(row=4, column = 1)

AngleX = tk.DoubleVar(window)
AngleXScl = tk.Scale(window, label='Vertical angle (µrad)', from_=-2000, to=2000,
                     orient=tk.HORIZONTAL, length=400, showvalue=1 ,tickinterval=500,
                     resolution=10, variable=AngleX, command=print_selection)
AngleXScl.grid(row=2, column = 1)

AngleY = tk.DoubleVar(window)
AngleYScl = tk.Scale(window, label='Horizontal angle (µrad)', from_=-2000, to=2000,
                     orient=tk.HORIZONTAL, length=400, showvalue=1 ,tickinterval=500,
                     resolution=10, variable=AngleY, command=print_selection)
AngleYScl.grid(row=5, column = 1)

inc = tk.IntVar(window)

TestLbl = tk.Label(window, bg='white', fg='black', width=20,textvariable = inc)
TestLbl.grid(row=2, column=0)


def print_test():
    inc.set(inc.get()+1)
    print('test', inc.get())
    sleep(1)
    print('waited 1 sec')
    window.after(1000, print_test)
    
def on_closing():
    print('exit?')
    if tk.messagebox.askokcancel('Quit?', 'Do you really want to quit?'):
        print('exit!')
        window.destroy()
        print('exit.')

window.protocol("WM_DELETE_WINDOW", on_closing)
window.after(1000, print_test)
window.mainloop()

#tk.messagebox.showerror('TEST', 'test')