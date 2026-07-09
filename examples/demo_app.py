"""
demo_app.py - Example: protecting an existing Tkinter app with 2 lines.
"""
import tkinter as tk
from license_dialog import gui_require_license

# --- the only licensing code your app needs ---
lm, info = gui_require_license(app_name="DemoApp")
# ----------------------------------------------

root = tk.Tk()
root.title("DemoApp (Licensed)")
root.geometry("400x200")
days = info.get("days_remaining")
status = "Lifetime license" if days is None else f"{days} days remaining"
tk.Label(root, text=f"App is running.\n{status}", font=("Segoe UI", 12)).pack(expand=True)
root.mainloop()
