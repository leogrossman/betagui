# -*- coding: utf-8 -*-

import tkinter as tk
import MirrorControlCmdLib

try:
    mv = MirrorControlCmdLib.MCCmdLib()
    
    window = tk.Tk()
    window.title('Mirror Control')
    
    def on_closing():
        mv.Shutdown()
        print('Shutdown completed')
        window.destroy()
    
    window.protocol("WM_DELETE_WINDOW", on_closing)
    window.mainloop()        

except ModuleNotFoundError as e:
    print('catched!', e.args[0])

