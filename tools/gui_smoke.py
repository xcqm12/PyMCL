"""GUI 冒烟测试：创建窗口、遍历页面、无报错退出。"""
import faulthandler
import sys
import traceback
from pathlib import Path

faulthandler.dump_traceback_later(60, exit=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 把阻塞的对话框替换为打印，避免测试挂起
import tkinter.messagebox as _mb
for name in ("showerror", "showwarning", "showinfo", "askyesno", "askokcancel"):
    setattr(_mb, name, lambda *a, **k: print(f"[msgbox:{name}]", *a[:2]) or False)
import tkinter.simpledialog as _sd
_sd.askstring = lambda *a, **k: None
_sd.askopenfilename = lambda *a, **k: None

from gui.app import App

errors = []

app = App()
app.update_idletasks()
app.update()
print("App created:", app.title(), flush=True)

import time
for key in ("home", "downloads", "market", "accounts", "settings", "home"):
    try:
        app.show(key)
        for _ in range(10):
            app.update()
            time.sleep(0.03)
        print(f"page ok: {key}", flush=True)
    except Exception as e:
        errors.append(f"{key}: {e}")
        traceback.print_exc()

# 下载页刷新清单
try:
    app.pages["downloads"].load_manifest(force=True)
    for _ in range(60):
        app.update()
        time.sleep(0.05)
    n = len(app.pages["downloads"].tree.get_children())
    print(f"downloads manifest rows: {n}", flush=True)
    assert n > 50
except Exception as e:
    errors.append(f"downloads manifest: {e}")
    traceback.print_exc()

try:
    app.on_close()
except Exception:
    pass
print("GUI smoke:", "FAIL " + "; ".join(errors) if errors else "ALL PASS")
sys.exit(1 if errors else 0)
