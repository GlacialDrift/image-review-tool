import getpass, os, tkinter as tk
import sys
from tkinter import messagebox
from PIL import ImageTk
from pathlib import Path

from app.config import load_config
from app.db import connect, ensure_schema, assign_batch, record_decision
from app.io_image import load_image, prepare_for_display


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Image Review")
        self.state("zoomed")

        self.cfg = load_config()
        yes_keys = self.cfg["KEYBINDS"]["yes"]
        no_keys = self.cfg["KEYBINDS"]["no"]

        # Bind "yes" keys (both cases)
        for k in yes_keys:
            self.bind(f"<{k}>", lambda e, r="yes": self.mark(r))
            self.bind(f"<{k.upper()}>", lambda e, r="yes": self.mark(r))

        # Bind "no" keys (both cases)
        for k in no_keys:
            self.bind(f"<{k}>", lambda e, r="no": self.mark(r))
            self.bind(f"<{k.upper()}>", lambda e, r="no": self.mark(r))

        self.bind("<Escape>", lambda e: self.destroy())
        self.after(50, self.focus_force)

        self.con = connect(self.cfg["DB_PATH"])
        from sys import executable

        bundle_dir = (
            Path(executable).parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[1]
        )
        ensure_schema(self.con, str(bundle_dir / "schema.sql"))

        self.user = getpass.getuser()
        self.batch_id = None
        self.items = []
        self.index = 0

        self.label = tk.Label(
            self,
            text="If loss of coating is observed, press 'y', 'b', or 's' (for \"yes, observed\", \"bad\", or \"scrap\"), otherwise press 'n' or 'g' (for \"not observed\" or \"good\")",
            font=("Segoe UI", 12),
        )
        self.label.pack()
        self.img_label = tk.Label(self)
        self.img_label.pack(expand=True)

        self.status = tk.Label(self, anchor="w")
        self.status.pack(fill="x")

        self.new_batch()

    def new_batch(self):
        self.batch_id, self.items = assign_batch(
            self.con, self.user, self.cfg["BATCH_SIZE"]
        )
        self.index = 0
        if not self.items:
            messagebox.showinfo("Done", "No unassigned images remain.")
            self.destroy()
            return
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
            ds = prepare_for_display(img, self.cfg.get("IMAGE"))
            tkimg = ImageTk.PhotoImage(ds)
            self.img_label.configure(image=tkimg)
            self.img_label.image = tkimg

            # ONE status line: includes batch, device, QC tag
            self.status.configure(
                text=f"User: {self.user} | Batch: {self.batch_id[:8]} | "
                f"Device: {device_id} | {self.index + 1}/{len(self.items)} | "
                f"{os.path.basename(path)}{' | QC' if qc_flag else ''}"
            )
        except Exception as e:
            messagebox.showerror("Load error", f"{path}\n{e}")
            self.index += 1
            self.refresh()

    def mark(self, result: str):
        review_id, image_id, _, _, _ = self.items[self.index]
        record_decision(
            self.con,
            review_id,
            self.user,
            self.batch_id,
            result,
            self.cfg["STANDARD_VERSION"],
        )
        self.index += 1
        self.refresh()


if __name__ == "__main__":
    App().mainloop()
