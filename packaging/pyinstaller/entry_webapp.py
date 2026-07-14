"""PyInstaller entry point -- see entry_receiver.py for why this indirection
through a normal import (rather than freezing sylo/webapp/winservice.py
directly) is needed.
"""
from sylo.webapp.winservice import main

if __name__ == "__main__":
    main()
