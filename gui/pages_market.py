"""资源市场页：Modrinth 搜索（带图标）+ 文件列表 + MC版本/加载器筛选 + 整合包/世界导入。"""
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from mclauncher import config, market, net, packexport, versions
from .theme import (C, FONT, FONT_S, FONT_XS, FONT_B,
                    flat_button, primary_button, ghost_button, label, make_entry, panel,
                    section)

TABS = [("mod", "模组"), ("shader", "光影"), ("resourcepack", "材质包"), ("modpack", "整合包")]
LOADERS = [("任何加载器", None), ("Fabric", "fabric"), ("Forge", "forge"),
           ("NeoForge", "neoforge"), ("Quilt", "quilt")]
TYPE_COLORS = {"release": C["accent"], "beta": C["warn"], "alpha": C["dim"]}
TYPE_NAMES = {"release": "正式", "beta": "Beta", "alpha": "Alpha"}


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def detect_loader(vid: str):
    """返回 (基版 MC id, loader 或 None)。"""
    try:
        chain = versions.load_chain(vid)
    except Exception:
        return vid, None
    base = chain[-1].get("id", vid)
    merged = versions.merge_chain(chain)
    joined = " ".join(l.get("name", "") for l in merged.get("libraries", []))
    main = str(merged.get("mainClass", ""))
    if "neoforged" in joined or "neoforged" in main:
        return base, "neoforge"
    if "minecraftforge" in joined:
        return base, "forge"
    if "quiltmc" in joined:
        return base, "quilt"
    if "fabricmc" in joined:
        return base, "fabric"
    return base, None


class MarketPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.tab = "mod"
        self.hits = []
        self.selected_pid = None
        self._files = []          # 当前项目的全部文件
        self._rows = {}
        self._file_rows = {}
        self._selected_file = None
        self._icon_refs = {}
        self._file_refs = set()

        # ---- 顶栏：分类 + 搜索 ----
        bar = panel(self)
        bar.pack(fill="x", padx=16, pady=(16, 6))
        row = tk.Frame(bar, bg=C["panel"])
        row.pack(fill="x", padx=12, pady=(10, 4))
        self._tab_btns = {}
        for key, text in TABS:
            b = flat_button(row, text, command=lambda k=key: self.set_tab(k), padx=14, pady=4,
                            font=FONT_S)
            b.pack(side="left", padx=(0, 6))
            self._tab_btns[key] = b
        self.search_entry = make_entry(row, width=24)
        self.search_entry.pack(side="left", padx=(14, 6))
        self.search_entry.bind("<Return>", lambda e: self.do_search())
        flat_button(row, "搜索", command=self.do_search, bg=C["accent"], padx=14).pack(side="left")

        # ---- 筛选行：MC 版本 + 加载器 ----
        frow = tk.Frame(bar, bg=C["panel"])
        frow.pack(fill="x", padx=12, pady=(0, 10))
        label(frow, "MC 版本:", color=C["dim"]).pack(side="left")
        self.ver_var = tk.StringVar(value="任何版本")
        self.ver_combo = ttk.Combobox(frow, textvariable=self.ver_var, state="readonly",
                                      width=16, font=FONT_S)
        self.ver_combo.pack(side="left", padx=(4, 16))
        self.ver_combo.bind("<<ComboboxSelected>>", lambda e: self._on_filter_change())
        label(frow, "加载器:", color=C["dim"]).pack(side="left")
        self.loader_var = tk.StringVar(value="任何加载器")
        self.loader_combo = ttk.Combobox(frow, textvariable=self.loader_var, state="readonly",
                                         width=12, font=FONT_S,
                                         values=[n for n, _ in LOADERS])
        self.loader_combo.pack(side="left", padx=4)
        self.loader_combo.bind("<<ComboboxSelected>>", lambda e: self._on_filter_change())
        self.hint = label(frow, "", color=C["dim"])
        self.hint.pack(side="left", padx=16)

        # ---- 主体：左项目卡片 / 右文件列表 ----
        main = tk.Frame(self, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=16, pady=6)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = panel(main)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        left.configure(width=330)
        left.grid_propagate(False)
        self.canvas = tk.Canvas(left, bg=C["bg"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=2, pady=2)
        self.list_frame = tk.Frame(self.canvas, bg=C["bg"])
        self._list_win = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.list_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(self._list_win, width=e.width))
        self._bind_wheel(self.canvas)

        right = panel(main)
        right.grid(row=0, column=1, sticky="nsew")
        self.file_header = label(right, "← 在左侧选择一个项目查看文件", color=C["dim"],
                                 anchor="w", justify="left")
        self.file_header.pack(fill="x", padx=10, pady=(8, 4))
        self.fcanvas = tk.Canvas(right, bg=C["bg"], highlightthickness=0, bd=0)
        self.fvsb = ttk.Scrollbar(right, orient="vertical", command=self.fcanvas.yview)
        self.fcanvas.configure(yscrollcommand=self.fvsb.set)
        self.fvsb.pack(side="right", fill="y")
        self.fcanvas.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        self.file_frame = tk.Frame(self.fcanvas, bg=C["bg"])
        self._file_win = self.fcanvas.create_window((0, 0), window=self.file_frame, anchor="nw")
        self.file_frame.bind(
            "<Configure>", lambda e: self.fcanvas.configure(scrollregion=self.fcanvas.bbox("all")))
        self.fcanvas.bind(
            "<Configure>", lambda e: self.fcanvas.itemconfigure(self._file_win, width=e.width))
        self._bind_wheel(self.fcanvas)

        # ---- 底部按钮 ----
        bottom = tk.Frame(self, bg=C["bg"])
        bottom.pack(fill="x", padx=16, pady=(0, 14))
        flat_button(bottom, "安装所选文件", command=self.install_selected_file,
                    bg=C["accent"], fg=C["on_accent"], padx=14).pack(side="left")
        flat_button(bottom, "导出当前版本为整合包…", command=self.open_export_dialog,
                    padx=12).pack(side="left", padx=8)
        flat_button(bottom, "导入整合包文件 (.mrpack / .zip)",
                    command=self.import_pack_file, padx=10).pack(side="left", padx=8)
        flat_button(bottom, "导入世界 (.zip / .mcworld 或 URL)",
                    command=self.import_world, padx=10).pack(side="left")

    # ---------- 滚动 ----------

    def _bind_wheel(self, canvas):
        canvas.bind("<Enter>", lambda e, c=canvas: c.bind_all("<MouseWheel>",
                   lambda ev, cc=c: cc.yview_scroll(-1 if ev.delta > 0 else 1, "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # ---------- 页面与筛选 ----------

    def on_show(self):
        self.reload_targets()

    def reload_targets(self):
        vals = ["任何版本"]
        vals += [v["id"] for v in versions.installed_versions()]
        try:
            m = versions.manifest()
            vals += [v["id"] for v in m.get("versions", [])
                     if v.get("type") == "release"][:40]
        except Exception:
            pass
        seen = set()
        self.ver_combo.config(values=[v for v in vals if not (v in seen or seen.add(v))])
        self.set_tab(self.tab)

    def set_tab(self, key):
        self.tab = key
        for k, b in self._tab_btns.items():
            b.config(bg=C["sel"] if k == key else C["panel2"])
        if self.tab in ("shader", "resourcepack"):
            self.loader_combo.config(state="disabled")
            self.loader_var.set("任何加载器")
        else:
            self.loader_combo.config(state="readonly")
        hints = {"mod": "文件列表按下方筛选显示；安装到所选版本的 mods 目录",
                 "shader": "安装到 shaderpacks 目录，建议搭配 OptiFine/Iris",
                 "resourcepack": "安装到 resourcepacks 目录",
                 "modpack": "整合包安装为独立版本与独立游戏目录"}
        self.hint.config(text=hints[key])
        self._render_files()

    def filter_base(self) -> str | None:
        v = self.ver_var.get()
        return None if v in ("任何版本", "") else v

    def filter_loader(self) -> str | None:
        if self.tab in ("shader", "resourcepack"):
            return None
        for name, val in LOADERS:
            if name == self.loader_var.get():
                return val
        return None

    def _on_filter_change(self):
        if self.hits:
            self.do_search(refetch_files=bool(self.selected_pid))
        else:
            self._render_files()

    def selected_target(self):
        vid = self.filter_base()
        if not vid:
            return None, None, None
        base, loader = detect_loader(vid)
        return vid, base, loader

    # ---------- 搜索 ----------

    def do_search(self, refetch_files: bool = False):
        if self.app.busy:
            return
        q = self.search_entry.get().strip()
        base = self.filter_base()
        loader = self.filter_loader()
        pid = self.selected_pid if refetch_files else None

        def task():
            try:
                hits = market.search(q, self.tab, game_version=base, loader=loader)
                self.hits = hits
                self.app.ui(self._fill_rows)
                if pid:
                    files = market.project_versions(pid)
                    self.app.ui(lambda: self._show_files(pid, files))
            except Exception as e:
                self.app.set_status(f"搜索失败: {e}", True)
        self.app.run_bg(task, "搜索")

    # ---------- 左侧项目卡片 ----------

    def _clear_rows(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._rows.clear()
        self._icon_refs.clear()
        self.selected_pid = None
        self._files = []
        self._selected_file = None
        self.file_header.config(text="← 在左侧选择一个项目查看文件")

    def _fill_rows(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._rows.clear()
        self._icon_refs.clear()
        self.selected_pid = None
        self._files = []
        self._selected_file = None
        if not self.hits:
            label(self.list_frame, "没有结果", color=C["dim"], bg=C["bg"]).pack(
                anchor="w", padx=8, pady=10)
            self.file_header.config(text="")
            return
        for h in self.hits:
            self._make_row(h)

    def _make_row(self, hit):
        pid = hit.get("project_id")
        row = tk.Frame(self.list_frame, bg=C["panel"], highlightthickness=1,
                       highlightbackground=C["border"], cursor="hand2")
        row.pack(fill="x", padx=4, pady=3)
        self._rows[pid] = row

        body = tk.Frame(row, bg=C["panel"])
        body.pack(fill="x", padx=6, pady=6)
        icon_box = tk.Frame(body, width=44, height=44, bg=C["panel2"])
        icon_box.pack(side="left", padx=(0, 8))
        icon_box.pack_propagate(False)
        icon_label = tk.Label(icon_box, bg=C["panel2"], text="")
        icon_label.pack(fill="both", expand=True)

        info = tk.Frame(body, bg=C["panel"])
        info.pack(side="left", fill="x", expand=True)
        title = label(info, (hit.get("title") or "?")[:22], bg=C["panel"],
                      font=("Microsoft YaHei UI", 10, "bold"))
        title.pack(anchor="w")
        meta = label(info, f"{(hit.get('author') or '?')[:14]}  ↓ {hit.get('downloads', 0):,}",
                     bg=C["panel"], color=C["dim"])
        meta.pack(anchor="w")
        desc = label(info, (hit.get("description") or "")[:30], bg=C["panel"],
                     color=C["dim"])
        desc.pack(anchor="w")

        widgets = [row, body, icon_box, icon_label, info, title, meta, desc]
        for w in widgets:
            w.bind("<Button-1>", lambda e, p=pid: self._select(p))
        row.bind("<Enter>", lambda e, p=pid: self._hover(p, True))
        row.bind("<Leave>", lambda e, p=pid: self._hover(p, False))

        url = hit.get("icon_url")
        if url:
            threading.Thread(target=self._load_icon, args=(url, pid, icon_label),
                             daemon=True).start()

    def _hover(self, pid, entered):
        if self.selected_pid == pid:
            return
        self._rows[pid].config(
            highlightbackground=C["hover"] if entered else C["border"])

    def _select(self, pid):
        self.selected_pid = pid
        for p, r in self._rows.items():
            r.config(highlightbackground=C["accent"] if p == pid else C["border"])
        hit = next((h for h in self.hits if h.get("project_id") == pid), None)
        if hit:
            self.file_header.config(text=f"加载文件列表中…  {hit.get('title')}")
        self._render_files()

        def task():
            try:
                files = market.project_versions(pid)
                self.app.ui(lambda: self._show_files(pid, files))
            except Exception as e:
                self.app.ui(lambda: self.file_header.config(text=f"获取文件失败: {str(e)[:80]}"))
        self.app.run_bg(task, "获取文件")

    def _load_icon(self, url, pid, icon_label):
        path = market.icon_file(url)
        if not path:
            return

        def f():
            try:
                img = tk.PhotoImage(file=str(path))
                self._icon_refs[pid] = img
                if icon_label.winfo_exists():
                    icon_label.config(image=img)
            except Exception:
                pass
        self.app.ui(f)

    # ---------- 右侧文件列表 ----------

    def _show_files(self, pid, files):
        if self.selected_pid != pid:
            return
        self._files = files
        hit = next((h for h in self.hits if h.get("project_id") == pid), {})
        self.file_header.config(
            text=f"{hit.get('title')}  -  {hit.get('author')}  -  ↓ {hit.get('downloads', 0):,}"
                 f"    （{len(files)} 个文件，双击安装）")
        self._render_files()

    def _render_files(self):
        for w in self.file_frame.winfo_children():
            w.destroy()
        self._file_rows.clear()
        self._file_refs.clear()
        self._selected_file = None
        if not self._files or not self.selected_pid:
            if self.selected_pid:
                label(self.file_frame, "加载中…", color=C["dim"], bg=C["bg"]).pack(
                    anchor="w", padx=8, pady=6)
            return
        base = self.filter_base()
        loader = self.filter_loader()
        shown = 0
        for pv in self._files:
            gvs = pv.get("game_versions") or []
            lds = [str(l).lower() for l in (pv.get("loaders") or [])]
            if base and base not in gvs:
                continue
            if loader and loader not in lds:
                continue
            self._make_file_row(pv)
            shown += 1
        if shown == 0:
            label(self.file_frame, "没有符合当前筛选的文件（可把筛选改回「任何版本/任何加载器」）",
                  color=C["dim"], bg=C["bg"], wraplength=520, justify="left").pack(
                anchor="w", padx=8, pady=6)

    def _make_file_row(self, pv):
        f = market.pick_version_file(pv) or {}
        vtype = pv.get("version_type", "release")
        gvs = pv.get("game_versions") or []
        gv_text = ", ".join(gvs[:3]) + (f" 等{len(gvs)}个" if len(gvs) > 3 else "")
        lds = ", ".join(pv.get("loaders") or []) or "-"
        size = f.get("size") or 0
        date = (pv.get("date_published") or "")[:10]

        row = tk.Frame(self.file_frame, bg=C["panel"], highlightthickness=1,
                       highlightbackground=C["border"], cursor="hand2")
        row.pack(fill="x", padx=4, pady=3)
        head = tk.Frame(row, bg=C["panel"])
        head.pack(fill="x", padx=8, pady=(6, 0))
        name = label(head, pv.get("version_number") or pv.get("name") or "?",
                     bg=C["panel"], font=("Microsoft YaHei UI", 10, "bold"))
        name.pack(side="left")
        chip_bg = TYPE_COLORS.get(vtype, C["dim"])
        chip = tk.Label(head, text=TYPE_NAMES.get(vtype, vtype), bg=chip_bg,
                        fg="#10131a", font=FONT_S, padx=6)
        chip.pack(side="left", padx=8)
        meta = label(head, f"{date}   {fmt_size(size) if size else '-'}",
                     bg=C["panel"], color=C["dim"])
        meta.pack(side="right")
        meta2 = label(row, f"加载器: {lds}    适用: {gv_text or '-'}",
                      bg=C["panel"], color=C["dim"])
        meta2.pack(anchor="w", padx=8, pady=(0, 6))

        widgets = [row, head, name, chip, meta, meta2]
        for w in widgets:
            if w is chip:
                continue
            w.bind("<Button-1>", lambda e, p=pv: self._select_file(p, row))
            w.bind("<Double-1>", lambda e, p=pv: self._install_file(p))
        self._file_rows[id(pv)] = row

    def _select_file(self, pv, row):
        self._selected_file = pv
        for r in self._file_rows.values():
            r.config(highlightbackground=C["border"])
        row.config(highlightbackground=C["accent"])

    # ---------- 安装 ----------

    def install_selected_file(self):
        pv = self._selected_file
        if not pv:
            messagebox.showinfo("提示", "请先在右侧文件列表中选择一个文件。")
            return
        self._install_file(pv)

    def _install_file(self, pv):
        if self.app.busy:
            messagebox.showwarning("提示", "已有任务在进行中。")
            return
        vid, base, target_loader = self.selected_target()
        if not vid:
            messagebox.showinfo("提示", "请先把上方「MC 版本」筛选选为一个已安装的版本作为安装目标。")
            return
        if self.tab == "mod" and target_loader:
            lds = [str(l).lower() for l in (pv.get("loaders") or [])]
            if lds and target_loader not in lds:
                if not messagebox.askyesno(
                        "加载器不匹配",
                        f"该文件需要 {'/'.join(lds)}，但所选版本 {vid} 是 {target_loader}。\n"
                        f"仍要安装吗？（可能导致游戏无法启动）"):
                    return

        def task():
            self.app.busy = True
            try:
                game_dir = config.game_dir_for(vid)
                if self.tab == "modpack":
                    f = market.pick_version_file(pv)
                    cache = config.mc_root() / "modpacks" / f["filename"]
                    on_status, on_update = self.app.job_reporter("下载整合包: ")
                    total = f.get("size") or 0
                    net.download_stream(
                        f["url"], cache, sha1=(f.get("hashes") or {}).get("sha1"),
                        progress=(lambda n: self.app.progress(n / total) if total else None))
                    new_vid, gdir = market.install_mrpack(
                        cache, self.app.dl, self.app.detect_and_pick_java(base),
                        on_status, on_update)
                    self.app.log(f"整合包安装完成：{new_vid}", "ok")
                else:
                    sub = {"mod": "mods", "shader": "shaderpacks",
                           "resourcepack": "resourcepacks"}[self.tab]
                    dest = market.install_asset({"id": self.selected_pid}, pv, game_dir / sub)
                    self.app.log(f"已安装到 {dest}", "ok")
                self.app.set_status("安装完成")
                self.app.ui(self.app.refresh_versions)
            except Exception as e:
                self.app.log(f"安装失败: {e}", "err")
                self.app.set_status(f"安装失败: {e}", True)
                self.app.ui(lambda: messagebox.showerror("安装失败", str(e)[:400]))
            finally:
                self.app.busy = False
                self.app.progress(None)
        self.app.run_bg(task, "安装文件")

    # ---------- 导出 ----------

    def open_export_dialog(self):
        from gui.pages_market import ExportDialog
        ExportDialog(self.app)

    def import_pack_file(self):
        path = filedialog.askopenfilename(title="选择整合包文件",
                                          filetypes=[("整合包", "*.mrpack *.zip"), ("所有文件", "*.*")])
        if not path:
            return
        if self.app.busy:
            messagebox.showwarning("提示", "已有任务在进行中。")
            return

        def task():
            self.app.busy = True
            try:
                p = Path(path)
                java = self.app.detect_and_pick_java(None)
                on_status, on_update = self.app.job_reporter("导入整合包: ")
                if p.suffix.lower() == ".mrpack":
                    vid, gdir = market.install_mrpack(p, self.app.dl, java, on_status, on_update)
                else:
                    vid, gdir = market.import_curseforge_zip(p, self.app.dl, java,
                                                             on_status, on_update)
                self.app.log(f"整合包导入完成：{vid}，游戏目录 {gdir}", "ok")
                self.app.set_status(f"整合包导入完成：{vid}")
                self.app.ui(self.app.refresh_versions)
            finally:
                self.app.busy = False
                self.app.progress(None)
        self.app.run_bg(task, "导入整合包")

    def import_world(self):
        url = simpledialog.askstring(
            "导入世界",
            "输入世界压缩包 URL（留空则从本地文件选择）：", parent=self.app)
        if url is None:
            return
        path = url.strip()
        if not path:
            path = filedialog.askopenfilename(
                title="选择世界文件", filetypes=[("世界", "*.zip *.mcworld"), ("所有文件", "*.*")])
            if not path:
                return
        if self.app.busy:
            messagebox.showwarning("提示", "已有任务在进行中。")
            return

        def task():
            self.app.busy = True
            try:
                vid = self.filter_base() or "1.20.1"
                saves = config.game_dir_for(vid) / "saves"
                dest = market.import_world(path, saves)
                self.app.log(f"世界已导入到 {dest}", "ok")
                self.app.set_status(f"世界导入完成：{dest.name}")
            finally:
                self.app.busy = False
                self.app.progress(None)
        self.app.run_bg(task, "导入世界")


class ExportDialog(tk.Toplevel):
    """导出当前版本为整合包：Modrinth .mrpack / CurseForge .zip / 纯备份 .zip。"""

    FORMATS = [("Modrinth (.mrpack) - 推荐，可分享到社区", "mrpack"),
               ("CurseForge (.zip) - 兼容 CF 启动器", "curseforge"),
               ("纯备份 (.zip) - 原样打包，最快", "backup")]

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("导出整合包")
        self.configure(bg=C["panel"])
        self.transient(app)
        self.resizable(False, False)
        self.grab_set()

        label(self, "导出整合包", font=FONT_B).pack(anchor="w", padx=20, pady=(16, 2))
        label(self, "把所选版本的 mods / config 等打包分享。mrpack 格式会自动把能识别的"
                    "Modrinth 模组解析为下载地址（其余放入 overrides）。",
              color=C["dim"], wraplength=560, justify="left").pack(anchor="w", padx=20)

        body = tk.Frame(self, bg=C["panel"])
        body.pack(fill="x", padx=20, pady=(10, 4))
        r = 0

        def add(name, widget):
            nonlocal r
            label(body, name, color=C["dim"]).grid(row=r, column=0, sticky="ne", padx=(0, 10),
                                                   pady=4)
            widget.grid(row=r, column=1, sticky="w", pady=4)
            r += 1

        # 源版本
        self.src_var = tk.StringVar()
        installed = [v["id"] for v in versions.installed_versions()]
        self.src_combo = ttk.Combobox(body, textvariable=self.src_var, state="readonly",
                                      values=installed, width=32, font=FONT_S)
        if installed:
            self.src_var.set(installed[0])
        add("源版本", self.src_combo)

        # 格式
        self.fmt_var = tk.StringVar(
            value=config.get("export_fmt") or self.FORMATS[0][0])
        if self.fmt_var.get() not in [n for n, _ in self.FORMATS]:
            self.fmt_var.set(self.FORMATS[0][0])
        self.fmt_combo = ttk.Combobox(body, textvariable=self.fmt_var, state="readonly",
                                      values=[n for n, _ in self.FORMATS], width=36,
                                      font=FONT_S)
        add("导出格式", self.fmt_combo)

        # 元数据
        self.name_var = tk.StringVar(value="My Modpack")
        add("整合包名称", make_entry(body, textvariable=self.name_var, width=32))
        _acc = config.active_account()
        self.author_var = tk.StringVar(value=(_acc or {}).get("name") or "PyMCL")
        add("作者", make_entry(body, textvariable=self.author_var, width=32))
        self.ver_var2 = tk.StringVar(value="1.0.0")
        add("版本号", make_entry(body, textvariable=self.ver_var2, width=14))
        self.desc_var = tk.StringVar(value="")
        add("简介", make_entry(body, textvariable=self.desc_var, width=42))

        # 包含内容
        inc_frame = tk.Frame(body, bg=C["panel"])
        self._inc_vars = {}
        for key in packexport.INCLUDE_DIRS + ["options.txt"]:
            v = tk.BooleanVar(value=True)
            self._inc_vars[key] = v
            ttk.Checkbutton(inc_frame, text=key, variable=v).pack(side="left", padx=(0, 10))
        add("包含内容", inc_frame)

        btns = tk.Frame(self, bg=C["panel"])
        btns.pack(fill="x", padx=20, pady=(8, 14))
        primary_button(btns, "选择位置并导出", command=self.do_export, padx=16).pack(side="left")
        ghost_button(btns, "取消", command=self.destroy, padx=12).pack(side="left", padx=8)
        self.status = label(self, "", color=C["dim"], wraplength=560, justify="left")
        self.status.pack(anchor="w", padx=20, pady=(0, 12))

        self._fit()

    def _fit(self):
        self.update_idletasks()
        h = min(self.winfo_reqheight(), self.winfo_screenheight() - 80)
        self.geometry(f"{max(self.winfo_reqwidth(), 460)}x{h + 4}")

    def _fmt(self):
        name = self.fmt_var.get()
        for n, v in self.FORMATS:
            if n == name:
                return v
        return "mrpack"

    def do_export(self):
        vid = self.src_var.get()
        if not vid:
            messagebox.showwarning("提示", "请选择要导出的源版本。", parent=self)
            return
        fmt = self._fmt()
        ext = {"mrpack": ".mrpack", "curseforge": ".zip", "backup": ".zip"}[fmt]
        default = f"{self.name_var.get().strip() or 'modpack'}{ext}"
        out = filedialog.asksaveasfilename(
            title="保存整合包", initialfile=default,
            filetypes=[("整合包", f"*{ext}"), ("所有文件", "*.*")], parent=self)
        if not out:
            return
        config.set("export_fmt", self.fmt_var.get())
        includes = {k: v.get() for k, v in self._inc_vars.items()}
        includes["servers.dat"] = includes.get("options.txt", True)
        name = self.name_var.get().strip() or "My Modpack"

        def on_status(s):
            self.app.ui(lambda: self.status.config(text=s))

        def task():
            self.app.busy = True
            try:
                stats = packexport.export_modpack(
                    vid, Path(out), fmt, name,
                    self.author_var.get().strip(), self.ver_var2.get().strip(),
                    self.desc_var.get().strip(), includes,
                    on_status=on_status)
                msg = (f"导出完成：{Path(out).name}（{fmt_size(stats.get('size', 0))}，"
                       f"{stats['total']} 个文件")
                if fmt == "mrpack":
                    msg += f"，{stats['resolved']} 个已解析为在线下载，{stats['overrides']} 个放入 overrides"
                msg += "）"
                self.app.log(msg, "ok")
                self.app.set_status("整合包导出完成")
                self.app.ui(self.destroy)
            except Exception as e:
                self.app.ui(lambda: self.status.config(text=f"导出失败: {str(e)[:200]}",
                                                       fg=C["danger"]))
                self.app.set_status(f"导出失败: {e}", True)
            finally:
                self.app.busy = False
                self.app.progress(None)
        self.app.run_bg(task, "导出整合包")
