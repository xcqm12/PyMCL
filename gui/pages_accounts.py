"""账户页：微软正版登录（设备代码流）与离线账号管理。"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from mclauncher import auth, config
from .theme import (C, FONT, FONT_S, FONT_B, FONT_XS,
                    flat_button, ghost_button, label, make_entry, make_text, panel)
import webbrowser


class MsaLoginDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("登录微软账号")
        self.configure(bg=C["panel"])
        self.transient(app)
        self.resizable(False, False)
        self.grab_set()

        label(self, "登录 Minecraft 正版账号", font=FONT_B).pack(pady=(16, 6))
        self.tip = label(self, "正在获取设备代码…", color=C["dim"], wraplength=400)
        self.tip.pack(padx=24)

        box = tk.Frame(self, bg=C["panel"])
        box.pack(pady=8)
        label(box, "访问：", bg=C["panel"]).grid(row=0, column=0, sticky="e")
        self.url_label = label(box, "-", bg=C["panel"], color=C["accent2"])
        self.url_label.grid(row=0, column=1, sticky="w")
        label(box, "代码：", bg=C["panel"]).grid(row=1, column=0, sticky="e")
        self.code_label = label(box, "-", bg=C["panel"],
                                font=("Consolas", 16, "bold"))
        self.code_label.grid(row=1, column=1, sticky="w")

        btns = tk.Frame(self, bg=C["panel"])
        btns.pack(pady=6)
        self.open_btn = flat_button(btns, "打开授权页面", command=self._open, padx=14)
        self.open_btn.pack(side="left")
        flat_button(btns, "取消", command=self._cancel, padx=14).pack(side="left", padx=8)
        self.url = None
        self.done = False
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._fit()

    def _fit(self):
        """按内容自适应窗口大小（避免 DPI 缩放/字体差异导致内容被裁掉）。"""
        self.update_idletasks()
        h = min(self.winfo_reqheight(), self.winfo_screenheight() - 80)
        self.geometry(f"{max(self.winfo_reqwidth(), 460)}x{h + 4}")

    def _open(self):
        if self.url:
            webbrowser.open(self.url)

    def _cancel(self):
        self.done = True
        self.grab_release()
        self.destroy()

    def on_code(self, url, code):
        self.url = url
        def f():
            self.url_label.config(text=url)
            self.code_label.config(text=code)
            self.tip.config(text="请在浏览器中打开下方链接并输入代码完成登录…")
        self.app.ui(f)
        if url:
            webbrowser.open(url)

    def on_done(self, account, err):
        self.done = True
        self.app.ui(lambda: (self.grab_release(), self.destroy()))
        finish_msa_login(self.app, account, err)


def finish_msa_login(app, account, err):
    """两个登录对话框共用的收尾：报错或保存账号。"""
    if err:
        app.ui(lambda: messagebox.showerror("登录失败", err, parent=app))
        app.set_status(f"微软登录失败: {err}", True)
        return
    if not account:
        return

    def save():
        accounts = [a for a in config.load_accounts()
                    if not (a.get("type") == "msa" and a.get("uuid") == account["uuid"])]
        accounts.append(account)
        config.save_accounts(accounts)
        config.set("active_account", len(accounts) - 1)
        app.log(f"微软账号 {account['name']} 登录成功", "ok")
        app.set_status("账号登录成功")
        page = app.pages.get("accounts")
        if page:
            page.reload()
    app.ui(save)


class MsaLocalDialog(tk.Toplevel):
    """备用登录：用户自建 Azure 应用，授权码流 + 本地回环回调。"""

    GUIDE = ("此方式使用你自己注册的 Azure 应用登录（公共 Client ID 被限流/拒绝时的备用方案）。\n\n"
             "注册步骤（免费，约 2 分钟）：\n"
             "1. 打开 portal.azure.com → 搜索「应用注册」→ 新注册\n"
             "2. 受支持的账户类型：选「任何组织目录中的账户和个人 Microsoft 账户」\n"
             "3. 重定向 URI：平台选「移动应用程序和桌面应用程序」，填 http://localhost\n"
             "4. 「身份验证」页底部：开启「允许公共客户端流」（设备代码也靠它）\n"
             "5. 复制「应用程序(客户端) ID」填到下面")

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("自建 Azure 应用授权登录（备用）")
        self.configure(bg=C["panel"])
        self.transient(app)
        self.resizable(False, False)
        self.grab_set()
        self.server = None

        label(self, "使用自己的 Azure 应用授权", font=FONT_B).pack(anchor="w", padx=20,
                                                                 pady=(16, 4))
        guide = label(self, self.GUIDE, color=C["dim"], wraplength=570, justify="left")
        guide.pack(anchor="w", padx=20)

        row = tk.Frame(self, bg=C["panel"])
        row.pack(fill="x", padx=20, pady=(10, 4))
        label(row, "Client ID:", bg=C["panel"]).pack(side="left")
        self.cid_entry = make_entry(row, width=42)
        self.cid_entry.pack(side="left", padx=8)
        self.cid_entry.insert(0, auth._client_id())  # 实际生效的 ID（含旧值迁移）

        row2 = tk.Frame(self, bg=C["panel"])
        row2.pack(fill="x", padx=20, pady=(0, 4))
        label(row2, "密钥(可选):", bg=C["panel"]).pack(side="left")
        self.secret_entry = make_entry(row2, width=42, show="•")
        self.secret_entry.pack(side="left", padx=8)
        self.secret_entry.insert(0, config.get("msa_client_secret", ""))
        label(self, "密钥说明：若你的应用把重定向 URI 注册在「Web」平台，令牌端点会要求密钥，"
                    "请把应用注册 → 证书和密码 里创建的密钥填到这里；"
                    "若注册在「移动应用程序和桌面应用程序」平台则留空即可。",
              color=C["dim"], wraplength=570, justify="left").pack(anchor="w", padx=20)

        flat_button(self, "开始授权", command=self.start, bg=C["accent"],
                    padx=16).pack(anchor="w", padx=20, pady=6)
        self.status = label(self, "状态：等待填写 Client ID", color=C["dim"],
                            wraplength=570, justify="left")
        self.status.pack(anchor="w", padx=20, pady=4)

        btns = tk.Frame(self, bg=C["panel"])
        btns.pack(anchor="w", padx=20, pady=(2, 12))
        flat_button(btns, "取消", command=self.cancel, padx=14).pack(side="left")
        flat_button(btns, "打开应用注册页面", command=lambda: webbrowser.open(
            "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/"
            "ApplicationsListBlade"), padx=14).pack(side="left", padx=8)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self._fit()

    def _fit(self):
        """按内容自适应窗口大小（避免 DPI 缩放/字体差异导致内容被裁掉）。"""
        self.update_idletasks()
        h = min(self.winfo_reqheight(), self.winfo_screenheight() - 80)
        self.geometry(f"{max(self.winfo_reqwidth(), 460)}x{h + 4}")

    def start(self):
        cid = self.cid_entry.get().strip()
        if not cid:
            messagebox.showwarning("提示", "请先填写 Azure 应用的 Client ID。", parent=self)
            return
        config.set("msa_client_id", cid)
        config.set("msa_client_secret", self.secret_entry.get().strip())
        self.cid_entry.config(state="disabled")
        self.secret_entry.config(state="disabled")
        self.status.config(text="状态：正在启动本地回调服务并打开浏览器…")

        def on_url(url, redirect_uri):
            def f():
                self.status.config(text=(
                    f"状态：请在浏览器中完成登录与授权\n回调地址（确认 Azure 应用里有此重定向 URI）: "
                    f"{redirect_uri}"))
            self.app.ui(f)
            webbrowser.open(url)

        def task():
            try:
                tokens = auth.local_browser_login(cid, on_url, timeout=300)
                account = auth.full_login_from_msa(tokens["access_token"],
                                                   tokens.get("refresh_token", ""), cid)
            except Exception as e:
                self.app.ui(lambda: self.status.config(
                    text=f"状态：失败 - {str(e)[:160]}",
                    fg=C["danger"]))
                self.app.ui(lambda: self.cid_entry.config(state="normal"))
                self.app.ui(lambda: self.secret_entry.config(state="normal"))
                finish_msa_login(self.app, None, str(e))
                return
            self.app.ui(lambda: (self.grab_release(), self.destroy()))
            finish_msa_login(self.app, account, None)

        self.app.run_bg(task, "Azure 授权登录")

    def cancel(self):
        if self.server:
            self.server.stop()
        self.grab_release()
        self.destroy()


class AccountsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app

        p = panel(self)
        p.pack(fill="both", expand=True, padx=16, pady=16)
        head = tk.Frame(p, bg=C["panel"])
        head.pack(fill="x", padx=12, pady=(12, 6))
        label(head, "已保存的账号", font=FONT_S).pack(side="left")

        self.listbox = tk.Listbox(p, bg=C["panel2"], fg=C["fg"], relief="flat",
                                  highlightthickness=1, highlightbackground=C["border"],
                                  font=FONT_S, selectbackground=C["sel"],
                                  activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=12, pady=8)

        self.btns = tk.Frame(p, bg=C["panel"])
        self.btns.pack(fill="x", padx=12, pady=(4, 12))
        self.btn_msa = flat_button(self.btns, "添加微软正版账号", command=self.add_microsoft,
                                   bg=C["accent"], padx=12)
        self.btn_msa.pack(side="left")
        self.btn_backup = flat_button(self.btns, "自建 Azure 授权登录（备用）",
                                      command=self.add_microsoft_local, padx=12)
        flat_button(self.btns, "添加离线账号", command=self.add_offline,
                    padx=12).pack(side="left", padx=8)
        flat_button(self.btns, "设为当前账号", command=self.set_active, padx=12).pack(side="left", padx=8)
        flat_button(self.btns, "删除", command=self.remove, padx=12).pack(side="left", padx=8)

        self.backup_tip = label(
            p, "「自建 Azure 授权登录」使用你自己注册的 Azure 应用（授权码流 + 本地回调），"
               "公共授权被限流/拒绝时使用；Client ID 与密钥在窗口内填写。",
            color=C["dim"], wraplength=820, justify="left")
        self.main_tip = label(
            p, "「添加微软正版账号」使用设备代码流程（推荐）：点击后打开浏览器，"
               "登录你的 Microsoft 账号并输入代码即可，需要已购买 Minecraft Java 版。",
            color=C["dim"], wraplength=820, justify="left")

        bottom = tk.Frame(p, bg=C["panel"])
        bottom.pack(fill="x", side="bottom", padx=12, pady=(0, 10))
        self.adv_toggle = ghost_button(bottom, "", command=self.toggle_backup, padx=8, pady=2,
                                       font=FONT_XS)
        self.adv_toggle.pack(side="right")

        self._apply_backup_visibility()

    def on_show(self):
        self.reload()
        self._apply_backup_visibility()

    def _backup_visible(self) -> bool:
        return bool(config.get("show_backup_auth"))

    def _apply_backup_visibility(self):
        """按配置显示/隐藏备用授权入口（正式打包版默认隐藏）。"""
        if self._backup_visible():
            self.btn_backup.pack(side="left", after=self.btn_msa, padx=8)
            self.main_tip.pack_forget()
            self.backup_tip.pack(fill="x", padx=12, pady=(8, 0), after=self.btns)
            self.adv_toggle.config(text="隐藏备用登录选项")
        else:
            self.btn_backup.pack_forget()
            self.backup_tip.pack_forget()
            self.main_tip.pack(fill="x", padx=12, pady=(8, 0), after=self.btns)
            self.adv_toggle.config(text="显示备用登录选项（自建 Azure 授权）")

    def toggle_backup(self):
        config.set("show_backup_auth", not self._backup_visible())
        self._apply_backup_visibility()

    def reload(self):
        self.listbox.delete(0, "end")
        active = int(config.get("active_account", 0))
        for i, a in enumerate(config.load_accounts()):
            t = "微软正版" if a.get("type") == "msa" else "离线"
            mark = "  ★ 当前" if i == active else ""
            self.listbox.insert("end", f"{a.get('name', '?')}（{t}）{mark}")

    def add_microsoft(self):
        dlg = MsaLoginDialog(self.app)
        self.app.run_bg(lambda: auth.begin_microsoft_login(dlg.on_code, dlg.on_done),
                        "微软登录")

    def add_microsoft_local(self):
        MsaLocalDialog(self.app)

    def add_offline(self):
        name = simpledialog.askstring("离线账号", "输入游戏内用户名：", parent=self.app)
        if not name or not name.strip():
            return
        name = name.strip()
        accounts = config.load_accounts()
        accounts.append({"type": "offline", "name": name, "uuid": auth.offline_uuid(name)})
        config.save_accounts(accounts)
        config.set("active_account", len(accounts) - 1)
        self.reload()
        self.app.log(f"已添加离线账号 {name}", "ok")

    def set_active(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        config.set("active_account", sel[0])
        self.reload()

    def remove(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        accounts = config.load_accounts()
        idx = sel[0]
        if not messagebox.askyesno("删除", f"确定删除账号 {accounts[idx].get('name')}？"):
            return
        accounts.pop(idx)
        config.save_accounts(accounts)
        if int(config.get("active_account", 0)) >= len(accounts):
            config.set("active_account", max(0, len(accounts) - 1))
        self.reload()
