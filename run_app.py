"""Launcher for the Image Review Tool GUI.

This small entry point imports the Tkinter application class (`App`) and starts
its main event loop. Keeping the launcher separate from the application module
has a few benefits:

  * Packaging: Tools like PyInstaller can target this file as the console/GUI
    entry script without pulling in development-only code.
  * Clarity: `app.main` focuses on application logic; this file focuses on
    "how to start it."

Typical usages:
  - Development: `python run_app.py`
  - Module invocation: `python -m app.main` (equivalent behavior)
  - Packaged executable: The PyInstaller build can point at this file.
"""

from app.main import App

def main() -> None:
    """Create the Tkinter application and run its event loop."""
    App().mainloop()

if __name__ == "__main__":
    main()
