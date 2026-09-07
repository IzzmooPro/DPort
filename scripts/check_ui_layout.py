"""Isolated native Tk layout probe. No DPort startup, DNS, hosts or config writes.

Run with the build Python and a scale argument (e.g. 1.25).
Screen fit is calculated; this does not change Windows display settings.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import customtkinter as ctk
from gui.app import DPortApp, BG

scale = float(sys.argv[1])
if scale not in (1.0, 1.25):
    raise SystemExit('Supported test scope: 1.0 or 1.25')
ctk.deactivate_automatic_dpi_awareness()
ctk.set_widget_scaling(scale)
ctk.set_window_scaling(scale)


class LayoutProbe(DPortApp):
    def __init__(self):
        # Deliberately do NOT call DPortApp.__init__: it has system side effects.
        ctk.CTk.__init__(self)
        self.withdraw()
        self.W, self.H = 348, 522
        self.configure(fg_color=BG)
        self.geometry('348x522+0+0')
        self._build()


win = LayoutProbe()
try:
    # Off-screen mapping lets Tk compute actual child coordinates without UI use.
    win.geometry('348x522+10000+10000')
    win.deiconify()
    win.update_idletasks()
    win._fit_height()
    win.geometry('+10000+10000')
    for _ in range(10):
        win.update()
        time.sleep(.02)
    footer_bottom = (win.status_lbl.winfo_rooty() - win.winfo_rooty()
                     + win.status_lbl.winfo_height())
    width, height = win.winfo_width(), win.winfo_height()
    gap = height - footer_bottom
    assert 0 <= gap <= 35 * scale, (scale, height, footer_bottom, gap)
    screens = [(1024,768),(1280,720),(1280,800),(1360,768),(1366,768),
               (1440,900),(1600,900),(1680,1050),(1920,1080),(1920,1200),
               (2560,1080),(2560,1440),(3440,1440),(3840,2160)]
    results = []
    for screen_w, screen_h in screens:
        # Compare native content dimensions, reserve 88px for taskbar/title.
        assert width <= screen_w and height <= screen_h - 88, (scale, screen_w, screen_h, width, height)
        results.append(f'{screen_w}x{screen_h}')
    print(json.dumps(dict(scale=scale, size=[width,height], footer_gap=gap, passed_screens=results)))
finally:
    win.destroy()
