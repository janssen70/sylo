"""PyInstaller entry point.

Freezing sylo/receiver/winservice.py directly as the Analysis script fails
with "attempted relative import with no known parent package": PyInstaller,
like `python winservice.py`, executes the target script as a standalone
module with no parent package, but winservice.py uses relative imports
(`.config`, `.main`), consistent with the rest of the codebase. Importing it
normally here instead makes it load as the real `sylo.receiver.winservice`
package submodule, so those relative imports resolve.
"""
from sylo.receiver.winservice import main

if __name__ == "__main__":
    main()
