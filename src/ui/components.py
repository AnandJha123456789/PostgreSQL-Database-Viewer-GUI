import tkinter as tk
from tkinter import ttk


class FlowFrame(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event=None):
        self.reorganize()

    def reorganize(self):
        x_pos, y_pos, row_height = 0, 0, 0
        for widget in self.winfo_children():
            widget.update_idletasks()
            width, height = widget.winfo_reqwidth(), widget.winfo_reqheight()
            if x_pos + width > self.winfo_width():
                x_pos = 0
                y_pos += row_height
                row_height = 0
            widget.place(x=x_pos, y=y_pos)
            x_pos += width + 4
            if height > row_height:
                row_height = height

        required_height = y_pos + row_height
        if self.winfo_reqheight() != required_height:
            self.config(height=required_height)
