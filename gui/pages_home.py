"""主页：英雄区（版本+启动）、快捷操作、运行日志。"""
import os
import time
import tkinter as tk
from tkinter import ttk, messagebox

from mclauncher import auth, config, launch, versions
from .theme import (C, FONT, FONT_S, FONT_XS, FONT_B, FONT_XB,
                    flat_button, primary_button, ghost_button, label, make_text, card)


class HomePage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app

        # ---- 英雄区 ----
        hero = card(self)
        hero.pack(fill="x", padx=16, pady=(16, 8))
        hero.columnconfigure(1, weight=1)

        left = tk.Frame(hero, bg=C["panel"])
        left.grid(row=0, column=0, sticky="nsew", padx=18, pady=16)

        label(left, "开始游戏", font=FONT_XB).pack(anchor="w")
        self.acc_chip = tk.Label(left, text="未登录", bg=C["panel2"], fg=C["dim"],
                                 font=FONT_XS, padx=8, pady=3)
        self.acc_chip.pack(anchor="w", pady=(8, 0))

        verrow = tk.Frame(left, bg=C["panel"])
        verrow.pack(fill="x", pady=(12, 0))
        label(verrow, "版本", color=C["dim"]).pack(side="left")
        self.ver_var = tk.StringVar()
        self.ver_combo = ttk.Combobox(verrow, textvariable=self.ver_var, state="readonly",
                                      font=FONT_S, width=36)
        self.ver_combo.pack(side="left", padx=8)
        self.ver_combo.bind("<<ComboboxSelected>>", lambda e: self._update_dir())
        ghost_button(verrow, "刷新", command=self.app.refresh_versions, padx=8, pady=2).pack(side="left")

        self.dir_label = label(left, "", color=C["dim"], font=FONT_XS)
        self.dir_label.pack(anchor="w", pady=(8, 0))

        right = tk.Frame(hero, bg=C["panel"])
        right.grid(row=0, column=2, sticky="nse", padx=18, pady=16)
        self.launch_btn = primary_button(right, "▶  启 动 游 戏", command=self.do_launch,
                                         font=("Microsoft YaHei UI", 14, "bold"),
                                         padx=34, pady=12)
        self.launch_btn.pack()
        label(right, "启动前会自动校验并补全游戏文件", color=C["dim"],
              font=FONT_XS).pack(pady=(8, 0))

        # ---- 快捷操作 ----
        quick = tk.Frame(self, bg=C["bg"])
        quick.pack(fill="x", padx=16, pady=(0, 8))
        for text, cmd in (("打开游戏目录", self._open_dir),
                          ("打开存档", lambda: self._open_sub("saves")),
                          ("打开截图", lambda: self._open_sub("screenshots")),
                          ("打开资源包", lambda: self._open_sub("resourcepacks"))):
            ghost_button(quick, text, cmd, padx=12).pack(side="left", padx=(0, 8))

        # ---- 日志 ----
        cpanel = card(self)
        cpanel.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        bar = tk.Frame(cpanel, bg=C["panel"])
        bar.pack(fill="x", padx=10, pady=(8, 0))
        label(bar, "运行日志", font=FONT_B).pack(side="left")
        ghost_button(bar, "清空", command=self._clear_log, padx=8, pady=2).pack(side="right")
        self.log_text = make_text(cpanel, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=8)
        for tag, color in [("info", C["fg"]), ("dim", C["dim"]), ("ok", C["accent"]),
                           ("warn", C["warn"]), ("err", C["danger"])]:
            self.log_text.tag_configure(tag, foreground=color)

    # ---------- 数据 ----------

    def on_show(self):
        self.reload()

    def reload(self):
        vs = versions.installed_versions()
        display = [f"{'★ ' if v['custom_dir'] else ''}{v['id']}" for v in vs]
        self._versions = vs
        self.ver_combo.config(values=display)
        if display and (not self.ver_var.get() or self.ver_var.get() not in display):
            self.ver_var.set(display[0])
        account = config.active_account()
        if account:
            t = "微软正版" if account.get("type") == "msa" else "离线"
            self.acc_chip.config(text=f"{account.get('name')}（{t}）", fg=C["fg"])
        else:
            self.acc_chip.config(text="未登录 - 请到「账户」添加", fg=C["dim"])
        self._update_dir()

    def _update_dir(self):
        vid = self.selected_version()
        if vid:
            try:
                d = config.game_dir_for(vid)
                self.dir_label.config(text=f"游戏目录：{d}")
            except Exception:
                self.dir_label.config(text="")

    def selected_version(self):
        raw = self.ver_var.get()
        return raw[2:] if raw.startswith("★ ") else raw or None

    def _open_dir(self):
        vid = self.selected_version()
        try:
            d = config.game_dir_for(vid or "1.20.1")
        except Exception:
            d = config.mc_root()
        os.startfile(d)

    def _open_sub(self, sub):
        vid = self.selected_version()
        d = config.game_dir_for(vid or "1.20.1") / sub
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(d)

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    # ---------- 启动 ----------

    def do_launch(self):
        if self.app.busy:
            messagebox.showwarning("提示", "已有任务在进行中，请稍候。")
            return
        vid = self.selected_version()
        if not vid:
            messagebox.showwarning("提示", "请先在「下载」页安装游戏版本。")
            return
        account = config.active_account()
        if not account:
            messagebox.showwarning("提示", "请先到「账户」页添加账号。")
            return

        def task():
            self.app.busy = True
            self.app.ui(lambda: self.launch_btn.config(state="disabled"))
            try:
                base = self.app.base_mc_of(vid) or vid
                java = self.app.detect_and_pick_java(base)
                if not java:
                    raise RuntimeError(
                        "未找到 Java，请到「设置」选择 Java 或使用自动下载。")
                self.app.log(f"使用 Java: {java}", "dim")
                info = auth.ensure_auth_info(account)
                self.app.set_status("登录完成，准备游戏文件…")
                on_status, on_update = self.app.job_reporter("启动: ")
                proc, game_dir, argv = launch.launch(
                    vid, info, self.app.dl, java,
                    on_status=on_status, on_update=on_update)
                self.app.log(f"游戏已启动 (PID {proc.pid})，游戏目录 {game_dir}", "ok")
                self.app.set_status("游戏运行中")
                self.app.progress(None)
            except Exception as e:
                self.app.log(f"启动失败: {e}", "err")
                self.app.set_status(f"启动失败: {e}", True)
                self.app.ui(lambda: messagebox.showerror("启动失败", str(e)[:500]))
            finally:
                self.app.busy = False
                self.app.ui(lambda: self.launch_btn.config(state="normal"))

        self.app.run_bg(task, "启动")
