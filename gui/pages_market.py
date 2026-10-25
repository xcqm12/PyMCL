"""资源市场页：打开自动加载热门列表（PCL 风格），标签/排序/版本/加载器筛选，
左侧项目卡片带标签徽章，下方文件列表，整合包导出/导入与世界导入。"""
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from mclauncher import config, market, net, packexport, versions
from .pages_downloads import PickDialog
from .theme import (C, FONT, FONT_S, FONT_XS, FONT_B,
                    flat_button, primary_button, ghost_button, label, make_entry, panel)

TABS = [("mod", "模组"), ("modpack", "整合包"), ("datapack", "数据包"),
        ("shader", "光影"), ("resourcepack", "材质包")]
LOADERS = [("任何加载器", None), ("Fabric", "fabric"), ("Forge", "forge"),
           ("NeoForge", "neoforge"), ("Quilt", "quilt")]
KNOWN_LOADERS = {"fabric", "forge", "neoforge", "quilt", "liteloader", "rift", "optifine", "iris"}
TYPE_COLORS = {"release": C["accent"], "beta": C["warn"], "alpha": C["dim"]}
TYPE_NAMES = {"release": "正式", "beta": "Beta", "alpha": "Alpha"}
CHIP_COLORS = ["#3a6ea5", "#7a5ba6", "#a5683a", "#3a7a5c", "#a53a5c", "#5c6b3a"]


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def rel_time(iso: str) -> str:
    """ISO 时间 -> 'x 小时/天/周/月/年 前'。"""
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        sec = time.time() - dt.timestamp()
    except Exception:
        return "-"
    if sec < 3600:
        return f"{max(1, int(sec // 60))} 分钟前"
    if sec < 86400:
        return f"{int(sec // 3600)} 小时前"
    if sec < 86400 * 7:
        return f"{int(sec // 86400)} 天前"
    if sec < 86400 * 30:
        return f"{int(sec // 604800)} 周前"
    if sec < 86400 * 365:
        return f"{int(sec // 2592000)} 个月前"
    return f"{int(sec // 31536000)} 年前"


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
        self._last_clicked_pid = None
        self._searched = False
        self._search_gen = 0
        self._files = []
        self._rows = {}
        self._file_rows = {}
        self._selected_file = None
        self._icon_refs = {}

        # ---- 顶栏 ----
        bar = panel(self)
        bar.pack(fill="x", padx=16, pady=(16, 6))
        row_tabs = tk.Frame(bar, bg=C["panel"])
        row_tabs.pack(fill="x", padx=12, pady=(10, 2))
        self.search_entry = make_entry(row_tabs)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=4)
        self.search_entry.bind("<Return>", lambda e: self.do_search())
        flat_button(row_tabs, "搜索", command=self.do_search, bg=C["accent"],
                    padx=18).pack(side="left")

        row1 = tk.Frame(bar, bg=C["panel"])
        row1.pack(fill="x", padx=12, pady=(2, 2))
        self._tab_btns = {}
        for key, text in TABS:
            b = flat_button(row1, text, command=lambda k=key: self.set_tab(k), padx=13, pady=4,
                            font=FONT_S)
            b.pack(side="left", padx=(0, 6))
            self._tab_btns[key] = b
        label(row1, "标签:", color=C["dim"]).pack(side="left", padx=(14, 2))
        self.tag_var = tk.StringVar(value="全部")
        self.tag_combo = ttk.Combobox(row1, textvariable=self.tag_var, state="readonly",
                                      width=10, font=FONT_S)
        self.tag_combo.pack(side="left", padx=(0, 14))
        self.tag_combo.bind("<<ComboboxSelected>>", lambda e: self.do_search())
        label(row1, "排序:", color=C["dim"]).pack(side="left", padx=(0, 2))
        self.sort_var = tk.StringVar(value="默认")
        self.sort_combo = ttk.Combobox(row1, textvariable=self.sort_var, state="readonly",
                                       width=9, font=FONT_S,
                                       values=[n for n, _ in market.SORTS])
        self.sort_combo.pack(side="left")
        self.sort_combo.bind("<<ComboboxSelected>>", lambda e: self.do_search())

        row2 = tk.Frame(bar, bg=C["panel"])
        row2.pack(fill="x", padx=12, pady=(2, 10))
        label(row2, "MC 版本:", color=C["dim"]).pack(side="left")
        self.ver_var = tk.StringVar(value="任何版本")
        self.ver_combo = ttk.Combobox(row2, textvariable=self.ver_var, state="readonly",
                                      width=15, font=FONT_S)
        self.ver_combo.pack(side="left", padx=(4, 14))
        self.ver_combo.bind("<<ComboboxSelected>>", lambda e: self.do_search())
        label(row2, "加载器:", color=C["dim"]).pack(side="left")
        self.loader_var = tk.StringVar(value="任何加载器")
        self.loader_combo = ttk.Combobox(row2, textvariable=self.loader_var, state="readonly",
                                         width=11, font=FONT_S,
                                         values=[n for n, _ in LOADERS])
        self.loader_combo.pack(side="left", padx=4)
        self.loader_combo.bind("<<ComboboxSelected>>", lambda e: self.do_search())
        ghost_button(row2, "↻ 刷新", command=lambda: self.do_search(), padx=8, pady=2
                     ).pack(side="right")
        self.hint = label(row2, "", color=C["dim"])
        self.hint.pack(side="right", padx=(0, 10))

        # ---- 主体：左项目卡片 / 右文件列表 ----
        main = tk.Frame(self, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=16, pady=6)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = panel(main)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        left.configure(width=400)
        left.grid_propagate(False)
        self.pcanvas = tk.Canvas(left, bg=C["bg"], highlightthickness=0, bd=0)
        self.pvsb = ttk.Scrollbar(left, orient="vertical", command=self.pcanvas.yview)
        self.pcanvas.configure(yscrollcommand=self.pvsb.set)
        self.pvsb.pack(side="right", fill="y")
        self.pcanvas.pack(fill="both", expand=True, padx=2, pady=2)
        self.list_frame = tk.Frame(self.pcanvas, bg=C["bg"])
        self._list_win = self.pcanvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.list_frame.bind(
            "<Configure>", lambda e: self.pcanvas.configure(scrollregion=self.pcanvas.bbox("all")))
        self.pcanvas.bind(
            "<Configure>", lambda e: self.pcanvas.itemconfigure(self._list_win, width=e.width))
        self._bind_wheel(self.pcanvas)

        right = panel(main)
        right.grid(row=0, column=1, sticky="nsew")
        self.file_header = label(right, "在左侧选择一个项目查看文件", color=C["dim"],
                                 anchor="w", justify="left")
        self.file_header.pack(fill="x", padx=10, pady=(8, 4))
        fwrap = tk.Frame(right, bg=C["bg"])
        fwrap.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        self.fcanvas = tk.Canvas(fwrap, bg=C["bg"], highlightthickness=0, bd=0)
        self.fvsb = ttk.Scrollbar(fwrap, orient="vertical", command=self.fcanvas.yview)
        self.fcanvas.configure(yscrollcommand=self.fvsb.set)
        self.fvsb.pack(side="right", fill="y")
        self.fcanvas.pack(fill="both", expand=True)
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
        if self.tab in ("shader", "resourcepack", "datapack"):
            self.loader_combo.config(state="disabled")
            self.loader_var.set("任何加载器")
        else:
            self.loader_combo.config(state="readonly")
        self.tag_combo.config(values=[n for n, _ in market.TAGS[self.tab]])
        self.tag_var.set("全部")
        hints = {"mod": "安装到所选版本的 mods 目录",
                 "modpack": "整合包安装为独立版本与独立游戏目录",
                 "datapack": "安装到所选世界存档的 datapacks 目录",
                 "shader": "安装到 shaderpacks 目录",
                 "resourcepack": "安装到 resourcepacks 目录"}
        self.hint.config(text=hints[key])
        self.do_search()  # 切分类自动加载热门列表

    def filter_base(self) -> str | None:
        v = self.ver_var.get()
        return None if v in ("任何版本", "") else v

    def filter_loader(self) -> str | None:
        if self.tab in ("shader", "resourcepack", "datapack"):
            return None
        for name, val in LOADERS:
            if name == self.loader_var.get():
                return val
        return None

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
        tag = dict(market.TAGS[self.tab]).get(self.tag_var.get())
        sort = dict(market.SORTS).get(self.sort_var.get())
        pid = self.selected_pid if refetch_files else None
        gen = self._search_gen = self._search_gen + 1  # 丢弃过期结果

        def task():
            try:
                hits = market.search(q, self.tab, game_version=base, loader=loader,
                                     category=tag, sort=sort)
                if gen != self._search_gen:
                    return
                self.hits = hits
                self._searched = True
                self.app.ui(self._fill_rows)
                if pid:
                    files = market.project_versions(pid)
                    self.app.ui(lambda: self._show_files(pid, files))
            except Exception as e:
                if gen != self._search_gen:
                    return
                self.hits = []
                self.app.ui(lambda: self._show_error(str(e)[:120]))
                self.app.set_status(f"搜索失败: {e}", True)
        self.app.run_bg(task, "搜索")

    def _show_error(self, msg):
        for w in self.list_frame.winfo_children():
            w.destroy()
        label(self.list_frame, f"列表加载失败：{msg}\n点右上角「↻ 刷新」重试",
              color=C["dim"], bg=C["bg"], wraplength=460, justify="center").pack(pady=60)

    # ---------- 左侧项目列表（全宽行） ----------

    def _fill_rows(self):
        keep = self.selected_pid if self.selected_pid in self._rows else None
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._rows.clear()
        self._icon_refs.clear()
        # 刷新结果时保留选中（避免自动加载迟到把用户刚点的项目清掉）
        self.selected_pid = keep
        self._selected_file = None
        if not self.hits:
            if self._searched:
                label(self.list_frame, "没有找到相关资源，换个筛选或关键词试试",
                      color=C["dim"], bg=C["bg"], wraplength=460, justify="center").pack(pady=60)
            self.file_header.config(text="在上方选择一个项目查看文件")
            self._render_files()
            return
        for h in self.hits:
            self._make_row(h)
        if self.selected_pid:
            r = self._rows.get(self.selected_pid)
            if r:
                r.config(highlightbackground=C["accent"])

    def _make_row(self, hit):
        pid = hit.get("project_id")
        row = tk.Frame(self.list_frame, bg=C["panel"], highlightthickness=1,
                       highlightbackground=C["border"], cursor="hand2")
        row.pack(fill="x", padx=4, pady=3)
        self._rows[pid] = row

        icon_box = tk.Frame(row, width=46, height=46, bg=C["panel2"])
        icon_box.pack(side="left", padx=(10, 8), pady=8)
        icon_box.pack_propagate(False)
        icon_label = tk.Label(icon_box, bg=C["panel2"], text="")
        icon_label.pack(fill="both", expand=True)

        info = tk.Frame(row, bg=C["panel"])
        info.pack(side="left", fill="x", expand=True, pady=7)
        head = tk.Frame(info, bg=C["panel"])
        head.pack(fill="x")
        label(head, hit.get("title") or "?", bg=C["panel"],
              font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        # 标签徽章（最多 2 个）
        cats = [c for c in (hit.get("display_categories") or hit.get("categories") or [])
                if c not in KNOWN_LOADERS][:2]
        for i, cat in enumerate(cats):
            tk.Label(head, text=cat, bg=CHIP_COLORS[i % len(CHIP_COLORS)],
                     fg="#eef2f7", font=FONT_XS, padx=6).pack(side="left", padx=(8, 0), pady=1)
        desc = label(info, (hit.get("description") or "")[:56], bg=C["panel"], color=C["dim"],
                     wraplength=300, justify="left")
        desc.pack(anchor="w")
        loaders = " / ".join(c for c in (hit.get("categories") or [])
                             if c in KNOWN_LOADERS)
        meta_parts = []
        if loaders:
            meta_parts.append(loaders)
        meta_parts.append(f"↓ {hit.get('downloads', 0):,}")
        meta_parts.append(rel_time(hit.get("date_modified")))
        meta = label(info, "  ·  ".join(meta_parts), bg=C["panel"], color=C["dim"],
                     font=FONT_XS, wraplength=300, justify="left")
        meta.pack(anchor="w")

        widgets = [row, icon_box, icon_label, info, head, desc, meta]
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
        self._last_clicked_pid = pid
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

    # ---------- 文件列表 ----------

    def _show_files(self, pid, files):
        # 迟到的响应：只要该 pid 仍是用户最后点击的项目就落地
        if pid not in (self.selected_pid, self._last_clicked_pid):
            return
        self.selected_pid = pid
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
        self._selected_file = None
        if not self.selected_pid:
            label(self.file_frame, "在上方选择一个项目后，这里会列出它的全部版本文件"
                  "（单击选中、双击安装）",
                  color=C["dim"], bg=C["bg"], justify="center").pack(pady=40)
            return
        if not self._files:
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
                        fg=C["on_accent"], font=FONT_XS, padx=6)
        chip.pack(side="left", padx=8)
        meta = label(head, f"{date}   {fmt_size(size) if size else '-'}",
                     bg=C["panel"], color=C["dim"])
        meta.pack(side="right")
        meta2 = label(row, f"加载器: {lds}    适用: {gv_text or '-'}",
                      bg=C["panel"], color=C["dim"])
        meta2.pack(anchor="w", padx=8, pady=(0, 6))

        widgets = [row, head, name, meta, meta2]
        for w in widgets:
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
            messagebox.showinfo("提示", "请先在文件列表中选择一个文件。")
            return
        self._install_file(pv)

    def _install_file(self, pv):
        if self.app.busy:
            messagebox.showwarning("提示", "已有任务在进行中。")
            return
        vid, base, target_loader = self.selected_target()
        if not vid:
            messagebox.showinfo("提示", "请先把「MC 版本」筛选选为一个已安装的版本作为安装目标。")
            return
        if self.tab == "datapack":
            # 数据包：选择目标世界存档
            worlds = market.list_worlds(config.game_dir_for(vid))
            if not worlds:
                if messagebox.askyesno(
                        "未找到存档",
                        f"在 {config.game_dir_for(vid) / 'saves'} 下没有找到世界存档。\n"
                        "是否手动选择一个世界文件夹（内含 level.dat）？"):
                    d = filedialog.askdirectory(title="选择世界文件夹", parent=self.app)
                    if not d:
                        return
                    self._run_install(pv, vid, base, Path(d) / "datapacks")
                return
            entries = [(n, str(p)) for n, p in worlds]
            PickDialog(self.app, "选择要安装数据包的世界", entries,
                       lambda wpath, disp: self._run_install(
                           pv, vid, base, Path(wpath) / "datapacks"))
            return
        if self.tab == "mod" and target_loader:
            lds = [str(l).lower() for l in (pv.get("loaders") or [])]
            if lds and target_loader not in lds:
                if not messagebox.askyesno(
                        "加载器不匹配",
                        f"该文件需要 {'/'.join(lds)}，但所选版本 {vid} 是 {target_loader}。\n"
                        f"仍要安装吗？（可能导致游戏无法启动）"):
                    return
        self._run_install(pv, vid, base, None)

    def _run_install(self, pv, vid, base, datapacks_dir):
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
                elif self.tab == "datapack":
                    dest = market.install_asset({"id": self.selected_pid}, pv, datapacks_dir)
                    self.app.log(f"数据包已安装到 {dest}（游戏内对该世界 "
                                 f"/reload 或重进生效）", "ok")
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

    # ---------- 导出 / 导入 ----------

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

        self.src_var = tk.StringVar()
        installed = [v["id"] for v in versions.installed_versions()]
        self.src_combo = ttk.Combobox(body, textvariable=self.src_var, state="readonly",
                                      values=installed, width=32, font=FONT_S)
        if installed:
            self.src_var.set(installed[0])
        add("源版本", self.src_combo)

        self.fmt_var = tk.StringVar(
            value=config.get("export_fmt") or self.FORMATS[0][0])
        if self.fmt_var.get() not in [n for n, _ in self.FORMATS]:
            self.fmt_var.set(self.FORMATS[0][0])
        self.fmt_combo = ttk.Combobox(body, textvariable=self.fmt_var, state="readonly",
                                      values=[n for n, _ in self.FORMATS], width=36,
                                      font=FONT_S)
        add("导出格式", self.fmt_combo)

        self.name_var = tk.StringVar(value="My Modpack")
        add("整合包名称", make_entry(body, textvariable=self.name_var, width=32))
        _acc = config.active_account()
        self.author_var = tk.StringVar(value=(_acc or {}).get("name") or "PyMCL")
        add("作者", make_entry(body, textvariable=self.author_var, width=32))
        self.ver_var2 = tk.StringVar(value="1.0.0")
        add("版本号", make_entry(body, textvariable=self.ver_var2, width=14))
        self.desc_var = tk.StringVar(value="")
        add("简介", make_entry(body, textvariable=self.desc_var, width=42))

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
