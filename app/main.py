import getpass, os, tkinter as tk
import sys
from tkinter import messagebox
from PIL import ImageTk
from pathlib import Path

from app.config import load_config
from app.db import connect, ensure_schema, assign_batch, record_decision
from app.db import run_migrations, add_annotation
from app.io_image import load_image, prepare_for_display


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Image Review")
        self.state("zoomed")

        self.cfg = load_config()
        bindings = self.cfg["RESULT_BINDINGS"]

        # Bind all key shortcuts
        for result, keys in bindings.items():
            for k in keys:
                self._bind_result_key(k, result)

        self.bind("<Escape>", lambda e: self._abort_and_close())
        self.protocol("WM_DELETE_WINDOW", self._abort_and_close)  # handle window close
        self.after(50, self.focus_force)

        # Database connection
        self.con = connect(self.cfg["DB_PATH"])
        from sys import executable
        bundle_dir = (
            Path(executable).parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[1]
        )
        ensure_schema(self.con, str(bundle_dir / "schema.sql"))
        run_migrations(self.con)

        self.user = getpass.getuser()
        self.batch_id = None
        self.items = []
        self.index = 0

        # UI
        self.label = tk.Label(self, text=self._instruction_text(), font=("Segoe UI", 12))
        self.label.pack()

        self.img_label = tk.Label(self)
        self.img_label.pack(expand=True)

        # Mouse bindings on the image widget
        self.img_label.bind("<Button-1>", self._on_left_click)
        self.img_label.bind("<Button-3>", self._on_right_click)

        # Buttons row
        btn_row = tk.Frame(self)
        btn_row.pack(pady=6)
        tk.Button(btn_row, text="Skip", command=lambda: self.mark("skip")).pack(side="left")

        self.status = tk.Label(self, anchor="w")
        self.status.pack(fill="x")

        self._current_transform = None  # holds transform info for current image
        self._current_image_size = None  # displayed size for offset calc
        self.new_batch()

    def _instruction_text(self):
        def pretty(binds):
            parts = []
            for res, keys in binds.items():
                if keys:
                    parts.append(f"{res}: {', '.join(keys)}")
            return " | ".join(parts)

        mouse = self.cfg["MOUSE"]
        mparts = []
        if mouse["left"]["action"]:
            mparts.append(f"L-click→{mouse['left']['action']}{' (point)' if mouse['left']['point'] else ''}")
        if mouse["right"]["action"]:
            mparts.append(f"R-click→{mouse['right']['action']}{' (point)' if mouse['right']['point'] else ''}")
        hint = " | ".join(mparts) if mparts else "mouse: (not configured)"
        return f"Keys — {pretty(self.cfg['RESULT_BINDINGS'])}  ||  {hint}  ||  Esc: release & exit"

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
            ds, info = prepare_for_display(img, self.cfg.get("IMAGE"))

            # render
            tkimg = ImageTk.PhotoImage(ds)
            self.img_label.configure(image=tkimg)
            self.img_label.image = tkimg

            # lock the label size to the image to keep (0,0) aligned
            dw, dh = info["displayed_size"]
            self.img_label.config(width=dw, height=dh)

            self._current_transform = info
            self._current_image_size = (dw, dh)

            self.status.configure(
                text=f"User: {self.user} | Batch: {self.batch_id[:8]} | "
                     f"Device: {device_id} | {self.index + 1}/{len(self.items)} | "
                     f"{os.path.basename(path)}{' | QC' if qc_flag else ''}"
            )
        except Exception as e:
            messagebox.showerror("Load error", f"{path}\n{e}")
            self.index += 1
            self.refresh()

    def _map_click_to_original(self, cx: int, cy: int):
        """
        Convert a click at display coords (cx,cy) to normalized (x,y) in original image space.
        Handles crop + scale and centers if label > image (we pin label size to image, but keep this robust).
        """
        if not self._current_transform:
            return None

        info = self._current_transform
        (W, H) = info["original_size"]
        (x0, y0, cw, ch) = info["crop"]
        scale = info["scale"]
        (dw, dh) = info["displayed_size"]

        # If label larger than image, center offset (we set width/height so this should be 0)
        ox = max((self.img_label.winfo_width() - dw) // 2, 0)
        oy = max((self.img_label.winfo_height() - dh) // 2, 0)
        ux = cx - ox
        uy = cy - oy
        if ux < 0 or uy < 0 or ux > dw or uy > dh:
            return None  # outside image

        # back to cropped coordinates, then to original
        x_in_cropped = ux / scale
        y_in_cropped = uy / scale
        x_orig = x0 + x_in_cropped
        y_orig = y0 + y_in_cropped
        # normalize 0..1 in original image
        return max(0.0, min(1.0, x_orig / W)), max(0.0, min(1.0, y_orig / H))

    def _on_left_click(self, event):
        self._handle_click(event, button="left")

    def _on_right_click(self, event):
        self._handle_click(event, button="right")

    def _handle_click(self, event, button: str):
        cfg = self.cfg["MOUSE"].get(button, {})
        action = cfg.get("action")
        want_point = cfg.get("point", False)

        if not action:
            return  # button not configured

        # optional annotation
        if want_point:
            pt = self._map_click_to_original(event.x, event.y)
            if pt is not None:
                review_id, *_ = self.items[self.index]
                try:
                    add_annotation(self.con, review_id, pt[0], pt[1], button)
                except Exception as e:
                    # don't block the flow if annotation fails
                    messagebox.showwarning("Annotation", f"Failed to save click: {e}")

        # mark decision and advance
        self.mark(action)

    def _abort_and_close(self):
        if self.batch_id:
            try:
                from app.db import release_batch
                release_batch(self.con, self.user, self.batch_id)
            except Exception as e:
                messagebox.showwarning("Release Warning", f"Could not find release batch: {e}")
        self.destroy()

    def _bind_result_key(self, key: str, result: str):
        k = key.strip()
        if k == " ":
            k = "space"      # normalize literal space to Tk keysym
        # For single-letter keys, bind lower + UPPER
        if len(k) == 1 and k.isalpha():
            seqs = [f"<{k}>", f"<{k.upper()}>"]
        else:
            seqs = [f"<{k}>"]  # multi-char keysyms (space, Return, Escape, etc.)
        for seq in seqs:
            self.bind(seq, lambda e, r=result: self.mark(r))

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
