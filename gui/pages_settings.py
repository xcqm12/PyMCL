"""设置页：游戏目录、Java、内存、下载、镜像等。"""
import os
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from mclauncher import config, javafind
from gui import theme_bg
from .theme import (C, FONT, FONT_S, flat_button, ghost_button, label, make_entry, panel,
                    ScrollableFrame)


class SettingsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._javas = []

        self.scroll = ScrollableFrame(self, C["bg"])
        self.scroll.pack(fill="both", expand=True)

        p = panel(self.scroll.inner)
        p.pack(fill="x", padx=16, pady=16)
        inner = tk.Frame(p, bg=C["panel"])
        inner.pack(fill="x", padx=14, pady=12)
        inner.columnconfigure(1, weight=1)

        r = 0
        def add_title(text):
            nonlocal r
            label(inner, text, font=FONT_S, color=C["accent"]).grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(10, 2))
            r += 1

        def add_row(name, widget, note=""):
            nonlocal r
            label(inner, name, color=C["dim"]).grid(row=r, column=0, sticky="ne", padx=(0, 10),
                                                    pady=4)
            widget.grid(row=r, column=1, columnspan=2, sticky="w", pady=4)
            r += 1

        # 游戏目录
        add_title("游戏")
        dirrow = tk.Frame(inner, bg=C["panel"])
        self.dir_var = tk.StringVar(value=config.get("mc_root"))
        make_entry(dirrow, textvariable=self.dir_var, width=52).pack(side="left")
        flat_button(dirrow, "浏览", command=self._browse_dir, padx=8, pady=2).pack(side="left", padx=6)
        flat_button(dirrow, "打开", command=self._open_dir, padx=8, pady=2).pack(side="left")
        add_row("游戏根目录", dirrow, )

        self.iso_all_var = tk.BooleanVar(value=bool(config.get("isolate_all", False)))
        ttk.Checkbutton(inner, text="新安装的版本默认启用版本隔离（每个版本独立存档/模组/配置）",
                        variable=self.iso_all_var).grid(row=r, column=1, columnspan=2,
                                                        sticky="w", pady=4)
        r += 1
        label(inner, "说明：单版本的隔离开关在「主页」版本选择旁；整合包始终使用独立目录。",
              color=C["dim"], bg=C["panel"], wraplength=560, justify="left").grid(
            row=r, column=1, columnspan=2, sticky="w", pady=(0, 6))
        r += 1

        # Java
        add_title("Java")
        jrow = tk.Frame(inner, bg=C["panel"])
        self.java_var = tk.StringVar()
        self.java_combo = ttk.Combobox(jrow, textvariable=self.java_var, width=48,
                                       state="readonly", font=FONT_S)
        self.java_combo.pack(side="left")
        flat_button(jrow, "刷新检测", command=self._detect_java, padx=8, pady=2).pack(side="left", padx=6)
        flat_button(jrow, "浏览…", command=self._browse_java, padx=8, pady=2).pack(side="left")
        add_row("Java 路径", jrow)
        jrow2 = tk.Frame(inner, bg=C["panel"])
        flat_button(jrow2, "自动下载 Java 8", command=lambda: self._dl_java(8), padx=10, pady=2).pack(side="left")
        flat_button(jrow2, "自动下载 Java 17", command=lambda: self._dl_java(17), padx=10, pady=2).pack(side="left", padx=8)
        flat_button(jrow2, "自动下载 Java 21", command=lambda: self._dl_java(21), padx=10, pady=2).pack(side="left")
        add_row("未安装 Java？", jrow2)

        # 内存
        add_title("性能")
        mrow = tk.Frame(inner, bg=C["panel"])
        self.xms_var = tk.IntVar(value=int(config.get("jvm_xms_mb", 512)))
        self.xmx_var = tk.IntVar(value=int(config.get("jvm_xmx_mb", 2048)))
        label(mrow, "最小内存", bg=C["panel"], color=C["dim"]).pack(side="left")
        ttk.Spinbox(mrow, from_=128, to=32768, increment=128, textvariable=self.xms_var,
                    width=8).pack(side="left", padx=(4, 14))
        label(mrow, "最大内存 (MB)", bg=C["panel"], color=C["dim"]).pack(side="left")
        ttk.Spinbox(mrow, from_=512, to=32768, increment=256, textvariable=self.xmx_var,
                    width=8).pack(side="left", padx=4)
        add_row("内存分配", mrow)

        self.jvm_var = tk.StringVar(value=config.get("extra_jvm_args", ""))
        add_row("额外 JVM 参数", make_entry(inner, textvariable=self.jvm_var, width=46))

        # 网络
        add_title("下载")
        self.mirror_var = tk.BooleanVar(value=bool(config.get("use_mirror", True)))
        ttk.Checkbutton(inner, text="使用国内镜像 (BMCLAPI) 加速下载", variable=self.mirror_var,
                        style="TCheckbutton").grid(row=r, column=1, columnspan=2, sticky="w", pady=4)
        r += 1
        self.threads_var = tk.IntVar(value=int(config.get("download_threads", 16)))
        trow = tk.Frame(inner, bg=C["panel"])
        ttk.Spinbox(trow, from_=1, to=64, textvariable=self.threads_var, width=6).pack(side="left")
        label(trow, "（同时下载的文件数）", bg=C["panel"], color=C["dim"]).pack(side="left", padx=6)
        add_row("下载线程数", trow)

        # 正版登录
        add_title("正版登录")
        self.cid_var = tk.StringVar(value=config.get("msa_client_id", ""))
        self.secret_var = tk.StringVar(value=config.get("msa_client_secret", ""))
        if config.get("show_backup_auth"):
            add_row("Azure Client ID", make_entry(inner, textvariable=self.cid_var, width=46))
            add_row("Azure 密钥(可选)", make_entry(inner, textvariable=self.secret_var, width=46,
                                                  show="•"))
            label(inner, "默认使用 Prism Launcher 的公共 Client ID（第三方应用，用户可直接授权）。"
                         "如遇到限流或想独立管理，可在 Azure 门户注册「公共客户端」应用"
                         "（启用设备代码流、添加 XboxLive.signin 委托权限）后填入自己的 Client ID；"
                         "若应用的重定向 URI 在「Web」平台（机密客户端），需同时填入密钥。",
                  color=C["dim"], bg=C["panel"], wraplength=560, justify="left").grid(
                row=r, column=1, columnspan=2, sticky="w", pady=(0, 6))
        else:
            label(inner, "备用授权（自建 Azure 应用）设置已隐藏——正式版默认不显示，"
                         "需要时到「账户」页右下角点「显示备用登录选项」开启。",
                  color=C["dim"], bg=C["panel"], wraplength=560, justify="left").grid(
                row=r, column=1, columnspan=2, sticky="w", pady=(0, 6))
        r += 1

        # 主题
        add_title("主题")
        self.anime_var = tk.BooleanVar(value=bool(config.get("anime_bg")))
        ttk.Checkbutton(inner, text="樱花二次元随机背景（主页横幅与市场底图）",
                        variable=self.anime_var,
                        command=self._theme_toggled).grid(row=r, column=1, columnspan=2,
                                                          sticky="w", pady=4)
        r += 1
        self.bg_url_var = tk.StringVar(value=config.get("bg_url", theme_bg.DEFAULT_URL))
        trow = tk.Frame(inner, bg=C["panel"])
        make_entry(trow, textvariable=self.bg_url_var, width=46).pack(side="left")
        ghost_button(trow, "换一张", command=self._new_bg, padx=10, pady=2).pack(side="left", padx=6)
        add_row("背景图地址", trow)

        # 保存
        btns = tk.Frame(inner, bg=C["panel"])
        btns.grid(row=r, column=0, columnspan=3, sticky="w", pady=(14, 0))
        flat_button(btns, "保存设置", command=self.save, bg=C["accent"], padx=16).pack(side="left")
        flat_button(btns, "打开安装器缓存目录", command=self._open_cache, padx=10).pack(side="left", padx=8)
        r += 1
        label(inner, "PyMCL v1.0.0 - 用 Python 编写的 Minecraft 启动器（仅用于学习交流；"
                     "正版登录与游戏文件下载分别使用 Microsoft 官方接口与 Mojang/BMCLAPI 公共资源）",
              color=C["dim"], bg=C["panel"], wraplength=640, justify="left").grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(12, 0))

        self._detect_java()

    def on_show(self):
        self.dir_var.set(config.get("mc_root"))
        self.anime_var.set(bool(config.get("anime_bg")))

    def _browse_dir(self):
        d = filedialog.askdirectory(title="选择游戏根目录")
        if d:
            self.dir_var.set(os.path.normpath(d))

    def _open_dir(self):
        p = self.dir_var.get()
        if p:
            os.startfile(p)

    def _detect_java(self):
        def task():
            javas = javafind.detect_javas()
            self.app.ui(lambda: self._fill_java(javas))
        self.app.run_bg(task, "检测 Java")

    def _fill_java(self, javas):
        self._javas = javas
        vals = [f"Java {j['major']} ({j['version']}) - {j['path']}" for j in javas]
        self.java_combo.config(values=vals)
        custom = config.get("java_path")
        cur = next((v for v in vals if v.endswith(custom)), None) if custom else None
        self.java_var.set(cur or (vals[0] if vals else ""))

    def _browse_java(self):
        f = filedialog.askopenfilename(title="选择 java.exe",
                                       filetypes=[("java.exe", "*.exe"), ("所有文件", "*.*")])
        if f:
            self.java_var.set(f"自定义 - {f}")

    def _picked_java_path(self):
        raw = self.java_var.get()
        if not raw:
            return ""
        if raw.startswith("自定义 - "):
            return raw[len("自定义 - "):]
        if " - " in raw:
            return raw.split(" - ", 1)[1]
        return ""

    def _dl_java(self, major):
        if self.app.busy:
            messagebox.showwarning("提示", "已有任务在进行中。")
            return

        def task():
            self.app.busy = True
            try:
                on_status, on_update = self.app.job_reporter(f"Java{major}: ")
                def prog(n):
                    self.app.progress(None)  # 字节进度大小未知，仅状态
                path = javafind.download_jre(major, on_status)
                self.app.log(f"Java {major} 安装完成：{path}", "ok")
                config.set("java_path", "")
                self.app.ui(self._detect_java)
                self.app.set_status(f"Java {major} 安装完成")
            finally:
                self.app.busy = False
                self.app.progress(None)
        self.app.run_bg(task, f"下载 Java {major}")

    def _open_cache(self):
        d = config.LAUNCHER_DIR / "cache"
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(d)

    def _theme_toggled(self):
        config.set("anime_bg", bool(self.anime_var.get()))
        self.app.apply_theme()

    def _new_bg(self):
        config.set("bg_url", self.bg_url_var.get().strip())
        def task():
            ok = theme_bg.ensure_source(force=True, on_status=self.app.set_status)
            if not ok:
                self.app.set_status("背景图下载失败，请检查地址或网络", True)
                return
            self.app.ui(self.app.apply_theme)
            self.app.set_status("已更换主题背景")
        self.app.run_bg(task, "更换背景")

    def save(self):
        updates = {
            "mc_root": self.dir_var.get().strip(),
            "java_path": self._picked_java_path(),
            "jvm_xms_mb": max(128, int(self.xms_var.get())),
            "jvm_xmx_mb": max(512, int(self.xmx_var.get())),
            "extra_jvm_args": self.jvm_var.get().strip(),
            "use_mirror": bool(self.mirror_var.get()),
            "download_threads": max(1, int(self.threads_var.get())),
            "msa_client_id": self.cid_var.get().strip(),
            "msa_client_secret": self.secret_var.get().strip(),
            "bg_url": self.bg_url_var.get().strip(),
            "isolate_all": bool(self.iso_all_var.get()),
        }
        if not updates["java_path"]:
            updates["java_path"] = ""
        config.set_many(updates)
        self.app.log("设置已保存", "ok")
        self.app.set_status("设置已保存")
