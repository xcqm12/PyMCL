"""主界面：侧边栏导航 + 主页/下载/资源市场/账户/设置。"""
import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from mclauncher import APP_NAME, __version__, auth, config, installers, javafind, launch, market, net, versions
from mclauncher.downloads import DownloadManager
from . import theme
from .theme import C, FONT, FONT_S, FONT_XS, FONT_B, FONT_LOG, flat_button, label, make_entry, make_text, panel

NAV_ITEMS = [
    ("home", "主页", "⌂"),
    ("downloads", "下载", "↓"),
    ("market", "资源市场", "◧"),
    ("accounts", "账户", "☰"),
    ("settings", "设置", "⚙"),
]


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PyMCL - Minecraft 启动器")
        w, h = int(config.get("window_width", 1020)), int(config.get("window_height", 660))
        self.geometry(f"{w}x{h}")
        self.minsize(880, 560)
        self.configure(bg=C["bg"])
        theme.style_ttk(self)
        self._set_logo()

        self.ui_queue = queue.Queue()
        self.after(80, self._poll)
        self.dl = DownloadManager()
        self.busy = False
        self.pages = {}

        # ---- 侧边栏 ----
        self.nav = tk.Frame(self, bg=C["panel"], width=172)
        self.nav.pack(side="left", fill="y")
        self.nav.pack_propagate(False)
        self._build_nav()
        self.content = tk.Frame(self, bg=C["bg"])
        self.content.pack(side="left", fill="both", expand=True)

        # ---- 底部状态栏 ----
        self.status = tk.Frame(self, bg=C["panel"], height=36)
        self.status.pack(side="bottom", fill="x")
        self._build_status()

        from gui.pages_home import HomePage
        from gui.pages_downloads import DownloadsPage
        from gui.pages_market import MarketPage
        from gui.pages_accounts import AccountsPage
        from gui.pages_settings import SettingsPage
        for key, cls in [("home", HomePage), ("downloads", DownloadsPage),
                         ("market", MarketPage), ("accounts", AccountsPage),
                         ("settings", SettingsPage)]:
            page = cls(self.content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.show("home")
        self.refresh_versions()
        self.log("欢迎使用 PyMCL！首次使用请先到「下载」安装游戏版本。", "info")

    # ---------- 基础设施 ----------

    def _set_logo(self):
        import sys
        self._logo_img = None
        try:
            candidates = [config.LAUNCHER_DIR / "assets" / "logo.png"]
            if getattr(sys, "frozen", False):
                candidates.insert(0, Path(sys._MEIPASS) / "assets" / "logo.png")
            for p in candidates:
                if p.exists():
                    img = tk.PhotoImage(file=str(p))
                    self.iconphoto(True, img)
                    self._logo_img = img.subsample(3, 3)
                    break
        except Exception:
            pass

    def _build_nav(self):
        head = tk.Frame(self.nav, bg=C["panel"])
        head.pack(fill="x", padx=16, pady=(18, 14))
        if getattr(self, "_logo_img", None):
            tk.Label(head, image=self._logo_img, bg=C["panel"]).pack()
        label(head, "PyMCL", font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(8, 0))
        label(head, "Minecraft 启动器", color=C["dim"], font=FONT_XS).pack()

        self._nav_btns = {}
        for key, text, icon in NAV_ITEMS:
            item = tk.Frame(self.nav, bg=C["panel"], cursor="hand2")
            item.pack(fill="x", padx=10, pady=2)
            stripe = tk.Frame(item, bg=C["panel"], width=3, height=30)
            stripe.pack(side="left", fill="y", padx=(2, 0))
            inner = tk.Frame(item, bg=C["panel"])
            inner.pack(side="left", fill="x", expand=True)
            lbl = tk.Label(inner, text=f"{icon}  {text}", bg=C["panel"], fg=C["dim"],
                           font=FONT, anchor="w", padx=12, pady=9)
            lbl.pack(fill="x")
            for w in (item, inner, lbl, stripe):
                w.bind("<Button-1>", lambda e, k=key: self.show(k))
            item.bind("<Enter>", lambda e, it=item, st=stripe, lb=lbl, k=key:
                      self._nav_hover(it, st, lb, k, True))
            item.bind("<Leave>", lambda e, it=item, st=stripe, lb=lbl, k=key:
                      self._nav_hover(it, st, lb, k, False))
            self._nav_btns[key] = (item, stripe, lbl)

        # 侧边栏底部：账号信息 + 版本
        bottom = tk.Frame(self.nav, bg=C["panel"])
        bottom.pack(side="bottom", fill="x", padx=12, pady=12)
        self.nav_account = tk.Frame(bottom, bg=C["panel2"])
        self.nav_account.pack(fill="x")
        self.nav_acc_text = tk.Label(self.nav_account, text="未登录", bg=C["panel2"],
                                     fg=C["dim"], font=FONT_XS, anchor="w", padx=10, pady=8)
        self.nav_acc_text.pack(fill="x")
        label(bottom, f"{APP_NAME} v{__version__}", color=C["dim"], font=FONT_XS).pack(pady=(10, 0))
        self.refresh_nav_account()

    def _nav_hover(self, item, stripe, lbl, key, entered):
        if self._current_page == key:
            return
        bg = C["hover"] if entered else C["panel"]
        item.config(bg=bg)
        lbl.config(bg=bg)

    def _build_status(self):
        self.status_dot = tk.Label(self.status, text="●", bg=C["panel"], fg=C["accent"],
                                   font=("Segoe UI Symbol", 9))
        self.status_dot.pack(side="left", padx=(14, 2))
        self.status_label = label(self.status, "就绪", bg=C["panel"], color=C["dim"])
        self.status_label.pack(side="left")
        self.prog = ttk.Progressbar(self.status, mode="determinate", length=260,
                                    style="Horizontal.TProgressbar")
        self.prog.pack(side="right", padx=12, pady=8)
        self.prog.pack_forget()

    def refresh_nav_account(self):
        acc = config.active_account()
        if acc:
            t = "微软正版" if acc.get("type") == "msa" else "离线"
            self.nav_acc_text.config(text=f"●  {acc.get('name', '?')}\n    {t}",
                                     fg=C["fg"])
        else:
            self.nav_acc_text.config(text="●  未登录\n    添加账号后可启动", fg=C["dim"])

    def show(self, key):
        self._current_page = key
        for k, (item, stripe, lbl) in self._nav_btns.items():
            cur = k == key
            bg = C["sel"] if cur else C["panel"]
            item.config(bg=bg)
            lbl.config(bg=bg, fg=C["fg"] if cur else C["dim"])
            stripe.config(bg=C["accent"] if cur else C["panel"])
        self.pages[key].tkraise()
        self.pages[key].on_show()

    def ui(self, fn):
        self.ui_queue.put(fn)

    def _poll(self):
        try:
            while True:
                fn = self.ui_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    import traceback
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def run_bg(self, fn, name="任务"):
        def wrapper():
            try:
                fn()
            except Exception as e:
                import traceback
                traceback.print_exc()
                msg = str(e)[:400]
                self.ui(lambda: messagebox.showerror("错误", f"{name}失败：\n{msg}"))
                self.set_status(f"{name}失败: {msg}", True)
                self.ui(lambda: self.progress(None))
        threading.Thread(target=wrapper, daemon=True).start()

    def set_status(self, text, error=False):
        def f():
            self.status_label.config(text=text[:120],
                                     fg=C["danger"] if error else C["fg"])
            self.status_dot.config(fg=C["danger"] if error else C["accent"])
            if error:
                self.prog.pack_forget()
        if threading.current_thread() is not threading.main_thread():
            self.ui(f)
        else:
            f()

    def progress(self, frac):
        def f():
            if frac is None:
                self.prog.pack_forget()
            else:
                self.prog.config(value=max(0, min(100, frac * 100)))
                if not self.prog.winfo_ismapped():
                    self.prog.pack(side="right", padx=12, pady=8)
        if threading.current_thread() is not threading.main_thread():
            self.ui(f)
        else:
            f()

    def job_reporter(self, prefix=""):
        """返回 (on_status, on_update) 用于 ensure_version 等的进度回调。"""
        def on_status(s):
            self.set_status(prefix + s)
            self.log(s, "dim")

        def on_update(job):
            total = job.total_bytes or 0
            frac = (job.done_bytes / total) if total else None
            if frac is None:
                text = f"{prefix}{job.done_files}/{len(job.tasks)} 个文件"
            else:
                text = (f"{prefix}{fmt_size(job.done_bytes)}/{fmt_size(total)} "
                        f"({job.done_files}/{len(job.tasks)} 文件)")
            self.set_status(text)
            self.progress(frac if total else None)
        return on_status, on_update

    def log(self, msg, level="info"):
        def f():
            page = self.pages.get("home")
            if not page:
                return
            t = page.log_text
            t.config(state="normal")
            t.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n", level)
            t.see("end")
            t.config(state="disabled")
        try:
            if threading.current_thread() is not threading.main_thread():
                self.ui(f)
            else:
                f()
        except Exception:
            pass

    # ---------- 公共数据 ----------

    def refresh_versions(self):
        page = self.pages.get("home")
        if page:
            page.reload()
        mk = self.pages.get("market")
        if mk:
            mk.reload_targets()
        self.refresh_nav_account()

    def base_mc_of(self, vid: str):
        try:
            chain = versions.load_chain(vid)
            return chain[-1].get("id")
        except Exception:
            return None

    def detect_and_pick_java(self, mc_version: str | None = None) -> str | None:
        custom = config.get("java_path")
        if custom and Path(custom).exists():
            return custom
        javas = javafind.detect_javas()
        if not javas:
            return None
        if mc_version:
            picked = javafind.pick_java(javas, mc_version)
            return picked["path"] if picked else None
        return javas[0]["path"]

    def on_close(self):
        config.set_many({"window_width": self.winfo_width(),
                         "window_height": self.winfo_height()})
        self.destroy()
