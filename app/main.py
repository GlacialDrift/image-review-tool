import getpass, io, os, tkinter as tk
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

        self.bind("<y>", lambda e: self.mark("yes"))
        self.bind("<n>", lambda e: self.mark("no"))
        self.bind("<Escape>", lambda e: self.destroy())

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

        image_id, path = self.items[self.index]
        row = self.con.execute("SELECT device_id FROM images WHERE image_id=?", (image_id,)).fetchone()
        device_id = row[0] if row else "unknown"

        self.status.configure(
            text=f"User: {self.user} | Device: {device_id} | "
                 f"{self.index + 1}/{len(self.items)} | {os.path.basename(path)}"
        )

        try:
            img = load_image(path)
            ds = downscale_for_screen(img)
            tkimg = ImageTk.PhotoImage(ds)
            self.img_label.configure(image=tkimg)
            self.img_label.image = tkimg
            self.status.configure(text=f"User: {self.user} | Batch: {self.batch_id[:8]} | "
                                       f"{self.index+1}/{len(self.items)} | {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Load error", f"{path}\n{e}")
            # Skip problematic image
            self.index += 1
            self.refresh()

    def mark(self, result: str):
        image_id, _ = self.items[self.index]
        record_decision(self.con, image_id, self.user, self.batch_id, result, self.cfg["STANDARD_VERSION"])
        self.index += 1
        self.refresh()

if __name__ == "__main__":
    App().mainloop()
