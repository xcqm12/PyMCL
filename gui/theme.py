"""主题与通用控件样式（深色精致风格）。"""
import tkinter as tk
from tkinter import ttk

C = {
    "bg": "#14161a",        # 窗口底
    "panel": "#1d2026",     # 卡片
    "panel2": "#262a33",    # 输入框/次级面
    "hover": "#2c313c",
    "sel": "#24403a",       # 选中（绿调）
    "fg": "#e6e9ef",
    "dim": "#8b93a3",
    "accent": "#4cc38a",    # 主色（薄荷绿）
    "accent_dim": "#2c6b4f",
    "accent_hover": "#5cd49a",
    "on_accent": "#0d2418",
    "accent2": "#5b8def",   # 次色（蓝）
    "danger": "#e5534b",
    "warn": "#d9a53f",
    "border": "#2e3340",
    "border_soft": "#262b34",
}

FONT = ("Microsoft YaHei UI", 10)
FONT_S = ("Microsoft YaHei UI", 9)
FONT_XS = ("Microsoft YaHei UI", 8)
FONT_B = ("Microsoft YaHei UI", 11, "bold")
FONT_XB = ("Microsoft YaHei UI", 13, "bold")
FONT_LOG = ("Consolas", 9)


def flat_button(parent, text, command=None, bg=None, fg=None, font=None, padx=12, pady=5,
                **kw):
    bg = bg or C["panel2"]
    fg = fg or C["fg"]
    b = tk.Button(parent, text=text, command=command, bg=bg, fg=fg, font=font or FONT,
                  activebackground=C["hover"], activeforeground=fg,
                  relief="flat", bd=0, cursor="hand2", padx=padx, pady=pady,
                  highlightthickness=0, **kw)
    return b


def primary_button(parent, text, command=None, font=None, padx=18, pady=7):
    return flat_button(parent, text, command, bg=C["accent"], fg=C["on_accent"],
                       font=font or FONT_B, padx=padx, pady=pady)


def ghost_button(parent, text, command=None, padx=12, pady=5, **kw):
    return flat_button(parent, text, command, bg=C["panel"], fg=C["dim"],
                       padx=padx, pady=pady, **kw)


def danger_button(parent, text, command=None, padx=12, pady=5):
    return flat_button(parent, text, command, bg=C["panel2"], fg=C["danger"],
                       padx=padx, pady=pady)


def chip(parent, text, color, text_color=None, font=None):
    """小徽章。"""
    return tk.Label(parent, text=text, bg=color, fg=text_color or C["on_accent"],
                    font=font or FONT_XS, padx=7, pady=1)


def section(parent, title, bg=None):
    """带左侧强调条的分区标题，返回标题行容器。"""
    bg = bg or C["panel"]
    head = tk.Frame(parent, bg=bg)
    tk.Frame(head, bg=C["accent"], width=3).pack(side="left", fill="y", pady=2)
    tk.Label(head, text=title, bg=bg, fg=C["fg"], font=FONT_B).pack(
        side="left", padx=(8, 0), pady=4)
    return head


def card(parent, **kw):
    return tk.Frame(parent, bg=C["panel"], highlightthickness=1,
                    highlightbackground=C["border"], **kw)


def panel(parent, **kw):
    return card(parent, **kw)


def style_ttk(root):
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except Exception:
        pass
    s.configure("TCombobox", fieldbackground=C["panel2"], background=C["panel2"],
                foreground=C["fg"], arrowcolor=C["dim"], bordercolor=C["border"],
                lightcolor=C["panel2"], darkcolor=C["panel2"],
                selectbackground=C["sel"], selectforeground=C["fg"])
    s.map("TCombobox", fieldbackground=[("readonly", C["panel2"])],
          foreground=[("readonly", C["fg"])])
    root.option_add("*TCombobox*Listbox.background", C["panel2"])
    root.option_add("*TCombobox*Listbox.foreground", C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["sel"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["fg"])
    s.configure("Treeview", background=C["panel2"], foreground=C["fg"],
                fieldbackground=C["panel2"], bordercolor=C["border"], rowheight=26,
                font=FONT_S)
    s.configure("Treeview.Heading", background=C["panel"], foreground=C["dim"],
                font=FONT_S, relief="flat")
    s.map("Treeview", background=[("selected", C["sel"])],
          foreground=[("selected", C["fg"])])
    s.configure("TSpinbox", fieldbackground=C["panel2"], background=C["panel2"],
                foreground=C["fg"], arrowcolor=C["dim"], bordercolor=C["border"])
    s.configure("Horizontal.TProgressbar", troughcolor=C["panel2"],
                background=C["accent"], bordercolor=C["panel2"],
                lightcolor=C["accent"], darkcolor=C["accent"], thickness=8)
    s.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=0)
    s.configure("TNotebook.Tab", background=C["panel"], foreground=C["dim"], padding=(14, 6),
                font=FONT_S, borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", C["panel2"])],
          foreground=[("selected", C["fg"])])
    s.configure("TCheckbutton", background=C["panel"], foreground=C["fg"], font=FONT_S,
                focuscolor=C["panel"])
    s.map("TCheckbutton", background=[("active", C["panel"])])


def make_entry(parent, **kw):
    e = tk.Entry(parent, bg=C["panel2"], fg=C["fg"], insertbackground=C["fg"],
                 relief="flat", highlightthickness=1, highlightbackground=C["border"],
                 highlightcolor=C["accent"], font=FONT_S, **kw)
    return e


def make_text(parent, **kw):
    t = tk.Text(parent, bg=C["panel"], fg=C["fg"], relief="flat", font=FONT_LOG,
                insertbackground=C["fg"], selectbackground=C["sel"], **kw)
    return t


def label(parent, text, color=None, font=None, **kw):
    return tk.Label(parent, text=text, bg=kw.pop("bg", C["panel"]),
                    fg=color or C["fg"], font=font or FONT_S, **kw)


class ScrollableFrame(tk.Frame):
    """带鼠标滚轮的纵向滚动容器：内容放 self.inner。"""

    def __init__(self, parent, bg=None, **kw):
        bg = bg or C["bg"]
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self._unit = 2

    def _on_wheel(self, e):
        # 悬停在输入类控件上时不滚页面（避免与控件自身滚轮行为冲突）
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
            if isinstance(w, (ttk.Combobox, ttk.Spinbox, tk.Spinbox, tk.Text, tk.Listbox)):
                return
        except Exception:
            pass
        # 滚轮一格滚 2 个单位，触控板小增量也顺滑
        self.canvas.yview_scroll(int(-1 * (e.delta / 120) * self._unit) or -self._unit, "units")
