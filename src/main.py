#!/usr/bin/env python3
import tkinter as tk
from src.config import DatabaseConfig
from src.database import DatabaseConnection
from src.ui.app import DatabaseQueryGUI
from src.utils import setup_logging


def main():
    setup_logging()

    # Use demo config or load from .env / environment variables
    # db_config = DatabaseConfig.from_env_file()
    db_config = DatabaseConfig.get_demo_config()

    db = DatabaseConnection(db_config)

    root = tk.Tk()
    app = DatabaseQueryGUI(root, db)

    def on_closing():
        db.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
