"""SloppyKeys macro for Anime Expedition.

The entry point `build_exe.py` packages and the one the README and the website tell people
to run, so it has to point at the live UI: `sloppykeys.ui.window` was the PySide6 front end
and was deleted in the pywebview migration, which left `python main.py` — and every built
exe — dying on the import.
"""

from __future__ import annotations

from sloppykeys.ui_web.bridge import main

if __name__ == "__main__":
    main()
