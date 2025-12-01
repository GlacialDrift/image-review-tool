"""Main Tkinter application for the Image Review Tool.

This module implements the GUI workflow for multi-user image review. It handles:
  * Database connectivity and schema migration on startup.
  * Keyboard and mouse bindings for marking results.
  * Batch management (assigning new images, releasing unfinished ones).
  * Optional click-based annotations mapped to normalized coordinates.
  * Dynamic UI hints generated from the loaded configuration.

Typical startup sequence:
  1. Load configuration via `app.config.load_config()`.
  2. Connect to SQLite database (`app.db.connect`).
  3. Ensure schema and run any migrations.
  4. Assign a batch of unreviewed images.
  5. Display images and handle user input until batch complete or exit.

Keyboard flow:
  - Result keys (yes/no/skip/other) → record decision + advance.
  - Escape or window close → release all undecided items and exit.

Mouse flow (configurable in [mouse] section):
  - Left/right click → map display coordinates to normalized image space,
    optionally record an annotation, then mark result and advance.

Author: Mike Harris
Version: 0.3.0
"""

import getpass, os, tkinter as tk
import sys
from tkinter import messagebox
from PIL import ImageTk
from pathlib import Path

from app.config import load_config
from app.db import (
    connect,
    ensure_schema,
    assign_batch,
    record_decision,
    _set_user_version,
    add_annotation,
    get_device_review_results,
    finalize_device_yes,
    finalize_device_no_by_pattern,
    finalize_exhausted_devices
)
from app.io_image import load_image, prepare_for_display


class App(tk.Tk):
    """Main Tkinter window for image review.

    Handles lifecycle of a review session, including:
      - Key and mouse event bindings.
      - Loading and displaying images.
      - Recording decisions and annotations.
      - Managing batch transitions.
    """

    def __init__(self):
        """Initialize the GUI and connect to the database."""
        super().__init__()
        self.title("Image Review")
        self.state("zoomed")

        # ------------------------------------------------------------------
        # Configuration and key bindings
        # ------------------------------------------------------------------
        self.cfg = load_config()
        bindings = self.cfg["RESULT_BINDINGS"]

        # Dynamically bind all configured key shortcuts (e.g., yes/no/skip)
        for result, keys in bindings.items():
            for k in keys:
                self._bind_result_key(k, result)

        self.bind("<Escape>", lambda e: self._abort_and_close())
        self.protocol("WM_DELETE_WINDOW", self._abort_and_close)  # handle window close
        self.after(50, self.focus_force)

        # ------------------------------------------------------------------
        # Database initialization
        # ------------------------------------------------------------------
        self.con = connect(self.cfg["DB_PATH"])
        from sys import executable
        bundle_dir = (
            Path(executable).parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[1]
        )
        ensure_schema(self.con, str(bundle_dir / "schema.sql"))
        _set_user_version(self.con, 2)

        self.user = getpass.getuser()
        self.batch_id = None
        self.items = []
        self.index = 0

        # ------------------------------------------------------------------
        # UI Layout
        # ------------------------------------------------------------------
        self.label = tk.Label(self, text=self._instruction_text(), font=("Segoe UI", 12))
        self.label.pack()

        self.img_label = tk.Label(self)
        self.img_label.pack(expand=True)

        # Mouse bindings for click-to-annotate or click-to-classify
        self.img_label.bind("<Button-1>", self._on_left_click)
        self.img_label.bind("<Button-3>", self._on_right_click)

        # Control row (currently only Skip button)
        btn_row = tk.Frame(self)
        btn_row.pack(pady=6)
        tk.Button(btn_row, text="Skip", command=lambda: self.mark("skip")).pack(side="left")

        # Status bar
        self.status = tk.Label(self, anchor="w")
        self.status.pack(fill="x")

        # Internal state for current display transform (used for click mapping)
        self._current_transform = None  # holds transform info for current image
        self._current_image_size = None  # displayed size for offset calc

        # Fetch the first batch
        self.new_batch()

    # ----------------------------------------------------------------------
    # UI text helpers
    # ----------------------------------------------------------------------
    def _instruction_text(self):
        """Generate dynamic instruction text from configuration."""
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

    # ----------------------------------------------------------------------
    # Core workflow
    # ----------------------------------------------------------------------
    def refresh(self):
        """Display the current image or advance to the next batch if finished."""
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

    # ----------------------------------------------------------------------
    # Coordinate mapping for click annotations
    # ----------------------------------------------------------------------
    def _map_click_to_original(self, cx: int, cy: int):
        """Convert a click at display coordinates to normalized (x,y) in original image space.

        Args:
            cx: X coordinate of the mouse click within the label widget.
            cy: Y coordinate of the mouse click within the label widget.

        Returns:
            tuple[float, float] or None:
                (x_norm, y_norm) in [0,1] relative to the original image,
                or None if the click lies outside the image area.
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

    # ----------------------------------------------------------------------
    # Mouse event handlers
    # ----------------------------------------------------------------------
    def _on_left_click(self, event):
        """Handle left mouse button click (primary action)."""
        self._handle_click(event, button="left")

    def _on_right_click(self, event):
        """Handle right mouse button click (secondary action)."""
        self._handle_click(event, button="right")

    def _handle_click(self, event, button: str):
        """Handle click events for left/right buttons per configuration."""
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

    # ----------------------------------------------------------------------
    # Batch control
    # ----------------------------------------------------------------------
    def _abort_and_close(self):
        """Release any in-progress items back to the pool and close the app."""
        if self.batch_id:
            try:
                from app.db import release_batch
                release_batch(self.con, self.user, self.batch_id)
            except Exception as e:
                messagebox.showwarning("Release Warning", f"Could not find release batch: {e}")
        self.destroy()

    def _bind_result_key(self, key: str, result: str):
        """Bind a keyboard key (and optionally uppercase variant) to a result label."""
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
        """Fetch a new set of unassigned reviews and reset progress."""
        self.batch_id, self.items = assign_batch(
            self.con, self.user, self.cfg["BATCH_SIZE"]
        )
        self.index = 0
        if not self.items:
            messagebox.showinfo("Done", "No unassigned images remain.")
            try:
                finalize_exhausted_devices(self.con)
            except Exception as e:
                messagebox.showwarning("Cleanup", f"Device cleanup failed: {e}")
            self.destroy()
            return
        self.refresh()

    # ----------------------------------------------------------------------
    # Decision recording
    # ----------------------------------------------------------------------
    def mark(self, result: str):
        """Record a decision for the current image and advance the session.

        Persists the reviewer’s decision for the currently displayed image,
        then applies device-level rules:

          * YES rule:
              If the current decision is 'yes', the device is marked YES and all
              remaining reviews for that device are auto-skipped.

          * NO–SKIP–SKIP rule:
              If, after this decision, the last three completed results for this
              device are ['no', 'skip', 'skip'] (in variant order), the device is
              marked NO and all remaining reviews for that device are auto-skipped.

        Finally, the method advances the internal cursor to the next item and
        refreshes the display. If the batch is exhausted, the normal end-of-batch
        flow in `refresh()` applies.

        Args:
            result: The decision label to record (e.g., 'yes', 'no', 'skip', or any
                custom label configured via RESULT_BINDINGS). This value is written
                verbatim to the `reviews.result` column.

        Side Effects:
            - Writes to the `reviews` table via `record_decision(...)`.
            - May trigger device-level auto-skip via YES rule or NO–SKIP–SKIP rule.
            - Mutates `self.index` and triggers a UI redraw with `self.refresh()`.

        Returns:
            None
        """
        if not self.items:
            return

        # Current item layout: (review_id, image_id, path, device_id, qc_flag)
        review_id, image_id, path, device_id, _ = self.items[self.index]

        # 1) Record the decision for this specific review row
        record_decision(
            self.con,
            review_id,
            self.user,
            self.batch_id,
            result,
            self.cfg["STANDARD_VERSION"],
        )

        # 2) Device-level auto-skip rules
        try:
            # YES rule: highest priority
            if result == "yes":
                finalize_device_yes(
                    self.con,
                    device_id=device_id,
                    image_id=image_id,
                    user=self.user,
                    batch_id=self.batch_id,
                    standard_version=self.cfg["STANDARD_VERSION"],
                )

            else:
                # NO–SKIP–SKIP rule: check last three completed results for this device
                history = get_device_review_results(self.con, device_id)
                # history is list of (variant, result), e.g. [('000','no'), ('001','skip'), ('002','skip')]
                if len(history) >= 3:
                    last_three = [r for (_, r) in history[-3:]]
                    if last_three == ["no", "skip", "skip"]:
                        finalize_device_no_by_pattern(
                            self.con,
                            device_id=device_id,
                            user=self.user,
                            batch_id=self.batch_id,
                            standard_version=self.cfg["STANDARD_VERSION"],
                        )
        except Exception as e:
            # Non-fatal: the primary decision has been saved; warn but continue
            messagebox.showwarning("Auto-skip", f"Device-level auto-skip failed: {e}")

        # 3) Advance to the next item in the batch
        self.index += 1
        self.refresh()


if __name__ == "__main__":
    App().mainloop()
