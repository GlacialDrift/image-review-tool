import getpass, os, tkinter as tk
from tkinter import messagebox
from PIL import ImageTk
from pathlib import Path

from .config import load_config
from .db import connect, ensure_schema, assign_batch, record_decision
from .io_image import load_image, downscale_for_screen

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Image Review")
        self.state("zoomed")

        self.cfg = load_config()
        self.con = connect(self.cfg["DB_PATH"])
        ensure_schema(self.con, str(Path(__file__).resolve().parents[1] / "schema.sql"))

        self.user = getpass.getuser()
        self.batch_id = None
        self.items = []
        self.index = 0

        self.label = tk.Label(self, text="Press Y / N", font=("Segoe UI", 12))
        self.label.pack()
        self.img_label = tk.Label(self)
        self.img_label.pack(expand=True)

        self.status = tk.Label(self, anchor="w")
        self.status.pack(fill="x")

        # Accept upper/lowercase, and make sure we get focus
        self.bind("<y>", lambda e: self.mark("yes"))
        self.bind("<Y>", lambda e: self.mark("yes"))
        self.bind("<n>", lambda e: self.mark("no"))
        self.bind("<N>", lambda e: self.mark("no"))
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(50, self.focus_force)  # grab focus

        self.new_batch()

    def new_batch(self):
        self.batch_id, self.items = assign_batch(self.con, self.user, self.cfg["BATCH_SIZE"])
        self.index = 0
        if not self.items:
            messagebox.showinfo("Done", "No unassigned images remain.")
            self.destroy(); return
        self.refresh()

    def refresh(self):
        if self.index >= len(self.items):
            if messagebox.askyesno("Batch complete", "Request another set?"):
                self.new_batch()
            else:
                self.destroy()
            return

        review_id, image_id, path, device_id, qc_flag = self.items[self.index]

        try:
            img = load_image(path)
            ds = downscale_for_screen(img)
            tkimg = ImageTk.PhotoImage(ds)
            self.img_label.configure(image=tkimg)
            self.img_label.image = tkimg

            # ONE status line: includes batch, device, QC tag
            self.status.configure(
                text=f"User: {self.user} | Batch: {self.batch_id[:8]} | "
                     f"Device: {device_id} | {self.index+1}/{len(self.items)} | "
                     f"{os.path.basename(path)}{' | QC' if qc_flag else ''}"
            )
        except Exception as e:
            messagebox.showerror("Load error", f"{path}\n{e}")
            self.index += 1
            self.refresh()

    def mark(self, result: str):
        review_id, image_id, _, _, _ = self.items[self.index]
        record_decision(self.con, review_id, self.user, self.batch_id, result, self.cfg["STANDARD_VERSION"])
        self.index += 1
        self.refresh()

if __name__ == "__main__":
    App().mainloop()
