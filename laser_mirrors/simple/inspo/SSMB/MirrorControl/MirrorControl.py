# -*- coding: utf-8 -*-

import tkinter as tk
import MirrorControlWindow

root = tk.Tk()

app = MirrorControlWindow.Window(root)

root.after(100, app.startup)
root.mainloop()
