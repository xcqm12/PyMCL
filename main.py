"""PyMCL 启动入口。"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    try:
        from tools.gen_logo import ensure_logo
        from mclauncher import config
        ensure_logo(config.LAUNCHER_DIR / "assets")
    except Exception:
        traceback.print_exc()

    try:
        from gui.app import App
        app = App()
        app.protocol("WM_DELETE_WINDOW", app.on_close)
        app.mainloop()
    except Exception:
        traceback.print_exc()
        try:
            import tkinter.messagebox as mb
            mb.showerror("PyMCL 启动失败", traceback.format_exc()[-1500:])
        except Exception:
            pass


if __name__ == "__main__":
    main()
