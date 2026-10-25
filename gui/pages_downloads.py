"""下载页：原版版本安装 + 各类加载器安装。"""
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from mclauncher import config, installers, versions
from .theme import C, FONT, FONT_S, flat_button, label, panel

CATEGORY = {"正式版": ("release",), "快照": ("snapshot",),
            "Beta / Alpha": ("old_beta", "old_alpha")}

LOADERS = [
    ("Forge", "forge"), ("NeoForge", "neoforge"), ("Fabric", "fabric"),
    ("Quilt", "quilt"), ("LegacyFabric", "legacyfabric"), ("OptiFine", "optifine"),
    ("LiteLoader", "liteloader"), ("Cleanroom", "cleanroom"), ("LabyMod", "labymod"),
]


class PickDialog(tk.Toplevel):
    """通用列表选择对话框。entries: [(显示文本, 值)]"""
    def __init__(self, app, title, entries, on_ok, ok_text="安装"):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.configure(bg=C["bg"])
        self.transient(app)
        self.geometry("560x480")
        self.on_ok = on_ok
        self.entries = entries

        top = tk.Frame(self, bg=C["bg"])
        top.pack(fill="x", padx=12, pady=10)
        label(top, f"共 {len(entries)} 项，选择后点击「{ok_text}」", bg=C["bg"],
              color=C["dim"]).pack(side="left")
        from .theme import make_entry
        self.search = make_entry(top, width=20)
        self.search.pack(side="right")
        self.search.bind("<KeyRelease>", lambda e: self._fill())

        cols = ("item",)
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("item", text=title)
        self.tree.column("item", width=520)
        self.tree.pack(fill="both", expand=True, padx=12)
        self.tree.bind("<Double-1>", lambda e: self._ok())

        btns = tk.Frame(self, bg=C["bg"])
        btns.pack(fill="x", padx=12, pady=10)
        flat_button(btns, ok_text, command=self._ok, bg=C["accent"]).pack(side="right")
        flat_button(btns, "取消", command=self.destroy).pack(side="right", padx=8)
        self._fill()

    def _fill(self):
        q = self.search.get().lower()
        self.tree.delete(*self.tree.get_children())
        for disp, val in self.entries:
            if q and q not in disp.lower():
                continue
            self.tree.insert("", "end", values=(disp,), tags=(val,))

    def _ok(self):
        sel = self.tree.selection()
        if not sel:
            return
        val = self.tree.item(sel[0], "tags")[0]
        disp = self.tree.item(sel[0], "values")[0]
        self.destroy()
        self.on_ok(val, disp)


class DownloadsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._manifest_cache = None

        # ---- 原版 ----
        vp = panel(self)
        vp.pack(fill="both", expand=True, padx=16, pady=(16, 6))
        head = tk.Frame(vp, bg=C["panel"])
        head.pack(fill="x", padx=14, pady=(12, 6))
        label(head, "安装 Minecraft 版本", font=FONT_S).pack(side="left")
        self.cat_var = tk.StringVar(value="正式版")
        cb = ttk.Combobox(head, textvariable=self.cat_var, state="readonly",
                          values=list(CATEGORY.keys()), width=14, font=FONT_S)
        cb.pack(side="left", padx=10)
        cb.bind("<<ComboboxSelected>>", lambda e: self.load_manifest(force=True))
        flat_button(head, "刷新", command=lambda: self.load_manifest(force=True), padx=10,
                    pady=3).pack(side="left")
        flat_button(head, "安装所选版本", command=self.install_selected, bg=C["accent"],
                    padx=10, pady=3).pack(side="right")

        cols = ("id", "type", "time")
        self.tree = ttk.Treeview(vp, columns=cols, show="headings", height=8)
        for col, text, w in (("id", "版本", 220), ("type", "类型", 130), ("time", "发布时间", 160)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor="w")
        self.tree.tag_configure("odd", background="#21252c")
        self.tree.pack(fill="both", expand=True, padx=14, pady=(4, 12))
        self.tree.bind("<Double-1>", lambda e: self.install_selected())

        # ---- 加载器 ----
        lp = panel(self)
        lp.pack(fill="both", expand=True, padx=16, pady=(6, 16))
        head2 = tk.Frame(lp, bg=C["panel"])
        head2.pack(fill="x", padx=14, pady=(12, 6))
        label(head2, "安装加载器（基于指定 MC 版本）", font=FONT_S).pack(side="left")
        label(head2, "MC 版本:", color=C["dim"]).pack(side="left", padx=(24, 4))
        self.mc_var = tk.StringVar()
        self.mc_combo = ttk.Combobox(head2, textvariable=self.mc_var, width=14, font=FONT_S)
        self.mc_combo.pack(side="left")

        grid = tk.Frame(lp, bg=C["panel"])
        grid.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        for idx, (name, kind) in enumerate(LOADERS):
            r, c = divmod(idx, 3)
            b = flat_button(grid, name, command=lambda k=kind: self.pick_loader(k),
                            padx=8, pady=10)
            b.grid(row=r, column=c, sticky="nsew", padx=6, pady=6)

    def on_show(self):
        self.load_manifest()
        self._refresh_mc_values()

    def _refresh_mc_values(self):
        if getattr(self, "_mc_values", None) is None:
            installed = [v["id"] for v in versions.installed_versions()]
            try:
                m = versions.manifest()
                latest = [v["id"] for v in m.get("versions", [])[:40]
                          if v.get("type") == "release"]
            except Exception:
                latest = []
            vals = list(dict.fromkeys(installed + latest))
            self._mc_values = vals
            self.mc_combo.config(values=vals)
            if not self.mc_var.get() and vals:
                self.mc_var.set(vals[0])

    def load_manifest(self, force=False):
        if self._manifest_cache is not None and not force:
            return
        def task():
            try:
                m = versions.manifest(force=force)
                self._manifest_cache = m.get("versions", [])
                self.app.ui(self._fill_tree)
            except Exception as e:
                self.app.set_status(f"获取版本列表失败: {e}", True)
        self.app.run_bg(task, "获取版本列表")

    def _fill_tree(self):
        from .theme import C as _C
        types = CATEGORY.get(self.cat_var.get(), ("release",))
        self.tree.delete(*self.tree.get_children())
        odd = False
        for v in self._manifest_cache or []:
            if v.get("type") in types:
                self.tree.insert("", "end", tags=("odd",) if odd else (),
                                 values=(v.get("id"), v.get("type", ""),
                                         (v.get("releaseTime") or "")[:10]))
                odd = not odd
        self._refresh_mc_values()

    def install_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个版本。")
            return
        vid = self.tree.item(sel[0], "values")[0]
        if self.app.busy:
            messagebox.showwarning("提示", "已有任务在进行中。")
            return
        if versions.load_json(vid) and not messagebox.askyesno("提示", f"{vid} 似乎已安装，重新校验并补全文件？"):
            return

        def task():
            self.app.busy = True
            try:
                on_status, on_update = self.app.job_reporter(f"安装 {vid}: ")
                installers.install_vanilla(vid, self.app.dl, on_status, on_update)
                self.app.log(f"{vid} 安装完成", "ok")
                self.app.set_status(f"{vid} 安装完成")
                self.app.ui(self.app.refresh_versions)
            finally:
                self.app.busy = False
                self.app.progress(None)
        self.app.run_bg(task, f"安装 {vid}")

    # ---------- 加载器 ----------

    def _mc(self) -> str:
        return self.mc_var.get().strip()

    def pick_loader(self, kind: str):
        if self.app.busy:
            messagebox.showwarning("提示", "已有任务在进行中。")
            return
        mc = self._mc()
        if kind not in ("cleanroom", "labymod", "liteloader") and not mc:
            messagebox.showinfo("提示", "请先填写/选择 MC 版本。")
            return

        def fetch():
            entries = []
            try:
                if kind == "forge":
                    entries = [(v, v) for v in installers.list_forge(mc)]
                elif kind == "neoforge":
                    entries = [(v, v) for v in installers.list_neoforge(mc)]
                elif kind in ("fabric", "quilt", "legacyfabric"):
                    entries = [(v, v) for v in installers.list_fabric_like(kind, mc)]
                elif kind == "optifine":
                    entries = [(f"{e['type']} {e['patch']}", json.dumps(e))
                               for e in installers.list_optifine(mc)]
                elif kind == "liteloader":
                    entries = [(v, v) for v in installers.list_liteloader()]
                elif kind == "cleanroom":
                    entries = [(f"{e['tag']}（1.12.2）", e["url"]) for e in installers.list_cleanroom()]
                elif kind == "labymod":
                    self.app.ui(lambda: self._install_loader("labymod", "官方安装器", mc))
                    return
            except Exception as e:
                self.app.ui(lambda: messagebox.showerror(
                    "获取列表失败", f"{e}\n请检查 MC 版本是否支持该加载器。"))
                return
            if not entries:
                self.app.ui(lambda: messagebox.showinfo(
                    "提示", f"没有找到 {mc} 可用的 {kind} 版本。"))
                return

            def open_dlg():
                PickDialog(self.app, f"选择 {kind} 版本（MC {mc}）", entries,
                           lambda val, disp: self._install_loader(kind, val, mc))
            self.app.ui(open_dlg)
        self.app.run_bg(fetch, "获取加载器列表")

    def _install_loader(self, kind, val, mc):
        def task():
            self.app.busy = True
            try:
                java = self.app.detect_and_pick_java(None)
                on_status, on_update = self.app.job_reporter(f"安装 {kind}: ")
                if kind == "labymod":
                    if not java:
                        raise RuntimeError("需要 Java 才能运行 LabyMod 安装器，请先配置 Java。")
                    installers.install_labymod(java, on_status)
                    self.app.log("LabyMod 官方安装器已打开，请在窗口中完成安装（安装目录选择: "
                                 f"{config.mc_root()}）", "warn")
                    return
                if kind in ("fabric", "quilt", "legacyfabric"):
                    vid = installers.install_fabric_like(kind, mc, val, manager=self.app.dl,
                                                         on_status=on_status, on_update=on_update)
                elif kind == "forge":
                    vid = installers.install_forge(mc, val, java, on_status)
                elif kind == "neoforge":
                    vid = installers.install_neoforge(mc, val, java, on_status)
                elif kind == "optifine":
                    e = json.loads(val)
                    vid = installers.install_optifine(mc, e["type"], e["patch"], java,
                                                      manager=self.app.dl,
                                                      on_status=on_status, on_update=on_update)
                elif kind == "liteloader":
                    vid = installers.install_liteloader(mc, self.app.dl, on_status, on_update)
                elif kind == "cleanroom":
                    from mclauncher.installers import run_installer
                    vid = run_installer(val, f"cleanroom-{val.split('/')[-1]}", java, on_status)
                else:
                    return
                self.app.log(f"{kind} 安装完成：{vid}", "ok")
                self.app.set_status(f"{kind} 安装完成：{vid}")
                self.app.ui(self.app.refresh_versions)
            finally:
                self.app.busy = False
                self.app.progress(None)
        self.app.run_bg(task, f"安装 {kind}")
