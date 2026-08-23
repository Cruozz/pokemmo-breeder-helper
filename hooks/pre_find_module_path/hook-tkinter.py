"""Keep tkinter's pure-Python modules discoverable in the bundled runtime.

The workspace Python runtime contains Tcl/Tk, but its Tcl probe is not usable
in the build sandbox. PyInstaller's stock pre-find hook therefore clears the
search path for tkinter. The build script supplies the native Tcl/Tk files
explicitly; this hook only restores the standard-library package path.
"""

from pathlib import Path
import sys


def pre_find_module_path(hook_api):
    library = Path(sys.base_prefix) / "Lib"
    if library.is_dir():
        hook_api.search_dirs = [str(library)]
