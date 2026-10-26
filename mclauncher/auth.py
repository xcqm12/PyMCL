"""账号：微软正版登录（设备代码流 + 本地回环授权码流 PKCE）、XBL/XSTS/MC 授权链、离线账号。"""
import base64
import hashlib
import http.server
import secrets
import socket
import threading
import time
import urllib.parse
from dataclasses import dataclass

from . import config, net

MSA_TENANT = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
SCOPE = "XboxLive.signin offline_access"


class AuthError(Exception):
    pass


@dataclass
class AuthInfo:
    name: str
    uuid: str
    access_token: str
    user_type: str = "msa"
    xuid: str = ""


# Prism Launcher 团队注册的第三方多租户 Azure 公共客户端（开源启动器社区通用），
# 已启用设备代码流且允许用户对 XboxLive.signin 作用域授权；
# 可在「设置」中换成自己注册的 Azure 应用 Client ID。
DEFAULT_CLIENT_ID = "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb"
_OLD_INVALID_IDS = {
    "c36a9fb6-2f2e-41ff-90bd-ae7cc92031eb",   # 早期版本写错的占位 ID
    "04b07795-8ddb-461a-bbee-02f9e1bf7b46",   # Azure CLI（第一方应用，用户无法授权 Xbox Live）
}


def _client_id() -> str:
    cid = config.get("msa_client_id") or ""
    if cid == "" or cid in _OLD_INVALID_IDS:
        return DEFAULT_CLIENT_ID
    return cid


def _client_secret() -> str:
    """可选：机密客户端密钥。应用注册为 Web 平台时令牌端点会强制要求。"""
    return (config.get("msa_client_secret") or "").strip()


# ---------------- MSA OAuth ----------------

def device_code_start(cid: str | None = None) -> dict:
    cid = cid or _client_id()
    code, data = net.post_json(f"{MSA_TENANT}/devicecode", {
        "client_id": cid, "scope": SCOPE}, form=True)
    # 用户自建的 ID 未开启"允许公共客户端流"时自动回退到公共 ID，保证主登录始终可用
    if (code != 200 and cid != DEFAULT_CLIENT_ID
            and (data.get("error") == "invalid_client"
                 or "AADSTS70002" in str(data.get("error_description", ""))
                 or "must be marked" in str(data.get("error_description", "")))):
        cid = DEFAULT_CLIENT_ID
        code, data = net.post_json(f"{MSA_TENANT}/devicecode", {
            "client_id": cid, "scope": SCOPE}, form=True)
    if code != 200 or "device_code" not in data:
        raise AuthError("获取设备代码失败：" + str(data.get("error_description") or data))
    data["_cid"] = cid
    return data


def device_code_poll(device: dict, on_poll=None) -> dict:
    """轮询直到用户完成登录，返回 {access_token, refresh_token}。"""
    cid = device.get("_cid") or _client_id()
    interval = max(1, int(device.get("interval", 5)))
    deadline = time.time() + int(code_expires(device))
    while time.time() < deadline:
        time.sleep(interval)
        if on_poll:
            on_poll()
        status, data = net.post_json(f"{MSA_TENANT}/token", {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": cid, "device_code": device["device_code"]},
            form=True)
        if status == 200 and "access_token" in data:
            return data
        err = data.get("error", "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err == "authorization_declined":
            raise AuthError("你拒绝了授权请求")
        if err == "expired_token":
            raise AuthError("登录超时，请重试")
        raise AuthError("登录失败：" + str(data.get("error_description") or data))
    raise AuthError("登录超时，请重试")


def code_expires(device: dict) -> int:
    return device.get("expires_in", 900)


def msa_refresh(refresh_token: str, cid: str | None = None) -> dict:
    payload = {"grant_type": "refresh_token", "client_id": cid or _client_id(),
               "refresh_token": refresh_token, "scope": SCOPE}
    if (cid or _client_id()) == _client_id() and _client_secret():
        payload["client_secret"] = _client_secret()
    status, data = net.post_json(f"{MSA_TENANT}/token", payload, form=True)
    if status != 200 or "access_token" not in data:
        raise AuthError("刷新登录已过期，请重新添加账号")
    return data


# ---------------- 备用：本地回环授权码流（用户自建 Azure 应用，PKCE） ----------------

def _pkce_pair() -> tuple:
    """生成 PKCE code_verifier 与 S256 code_challenge。"""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def msa_authorize_url(client_id: str, redirect_uri: str, state: str,
                      code_challenge: str | None = None) -> str:
    q = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
        "prompt": "select_account",
    }
    if code_challenge:
        q["code_challenge"] = code_challenge
        q["code_challenge_method"] = "S256"
    return f"{MSA_TENANT}/authorize?{urllib.parse.urlencode(q)}"


def msa_token_from_code(code: str, client_id: str, redirect_uri: str,
                        code_verifier: str | None = None) -> dict:
    payload = {"grant_type": "authorization_code", "client_id": client_id,
               "code": code, "redirect_uri": redirect_uri, "scope": SCOPE}
    if code_verifier:
        payload["code_verifier"] = code_verifier
    secret = _client_secret()
    if secret:
        payload["client_secret"] = secret
    status, data = net.post_json(f"{MSA_TENANT}/token", payload, form=True)
    if status != 200 or "access_token" not in data:
        desc = str(data.get("error_description") or data)
        if "AADSTS70002" in desc and "client_secret" in desc:
            raise AuthError(
                "该 Azure 应用要求提供客户端密钥：请在登录窗口的「Client Secret」栏填入"
                "应用注册里的密钥；或者到应用注册 → 身份验证，把重定向 URI 平台改为"
                "「移动应用程序和桌面应用程序」（公共客户端，无需密钥）。")
        if "Proof Key" in desc or "PKCE" in desc.upper():
            raise AuthError("该应用要求 PKCE，但本次请求未携带——请更新到最新版 PyMCL")
        raise AuthError("换取令牌失败：" + desc[:300])
    return data


class _LoopbackServer:
    """本地回环 HTTP 服务器，等待 Azure 授权回调 ?code=...。"""

    def __init__(self, expected_state: str):
        self.expected_state = expected_state
        self.result: str | None = None
        self.error: str | None = None
        self.done = threading.Event()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    if "error" in qs:
                        outer.error = (qs["error"][0] + ": "
                                       + qs.get("error_description", [""])[0][:250])
                        self._respond("登录失败，可关闭此页面并查看启动器提示。")
                        outer.done.set()
                        return
                    if qs.get("state", [""])[0] != outer.expected_state:
                        self._respond("state 校验失败，请回到启动器重新发起登录。")
                        return  # 不是我们的回调，继续等
                    code = qs.get("code", [""])[0]
                    if not code:
                        self._respond("回调缺少 code 参数，请重试。")
                        return
                    outer.result = code
                    self._respond("授权成功！请回到启动器继续。")
                    outer.done.set()
                except Exception as e:  # 防止异常挂死
                    outer.error = f"回调处理出错: {e}"
                    outer.done.set()

            def _respond(self, text: str):
                body = ("<!doctype html><meta charset='utf-8'><body style='font-family:"
                        "sans-serif;padding:40px'><h2>PyMCL 授权回调</h2><p>" + text
                        + "</p></body>").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.httpd = http.server.HTTPServer(("127.0.0.1", self.port), Handler)
        self.httpd.timeout = 1

    def wait_code(self, timeout: float) -> str:
        deadline = time.time() + timeout
        while not self.done.is_set() and time.time() < deadline:
            self.httpd.handle_request()
        self.httpd.server_close()
        if self.error:
            raise AuthError(self.error)
        if not self.result:
            raise AuthError("等待浏览器授权超时，请重试")
        return self.result

    def stop(self):
        self.done.set()


def local_browser_login(client_id: str, on_url, timeout: float = 300) -> dict:
    """备用登录：自建 Azure 应用的授权码流（PKCE）+ 本地回环回调。返回 MSA 令牌。"""
    state = secrets.token_urlsafe(16)
    server = _LoopbackServer(state)
    redirect_uri = f"http://localhost:{server.port}"
    verifier, challenge = _pkce_pair()
    url = msa_authorize_url(client_id, redirect_uri, state, code_challenge=challenge)
    on_url(url, redirect_uri)
    code = server.wait_code(timeout)
    return msa_token_from_code(code, client_id, redirect_uri, code_verifier=verifier)


# ---------------- XBox / Minecraft 链 ----------------

def xbl_authenticate(msa_token: str) -> str:
    """XBL 用户令牌。对照 HMCL（带 RelyingParty auth.xboxlive.com）与
    PCL CE（不带 RelyingParty）两种写法，依次尝试。"""
    variants = [
        {"Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                        "RpsTicket": f"d={msa_token}"},
         "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"},
        {"Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                        "RpsTicket": f"d={msa_token}"},
         "TokenType": "JWT"},
    ]
    last = {}
    for payload in variants:
        code, data = net.post_json("https://user.auth.xboxlive.com/user/authenticate",
                                   payload, headers={"Accept": "application/json"})
        if code == 200 and "Token" in data:
            return data["Token"]
        last = data
    raise AuthError("Xbox Live 认证失败：" + str(last.get("XErr", last))[:200])


def xsts_authenticate(xbl_token: str):
    """XSTS 授权（对照 PCL CE 与 HMCL 的实现）：
    - HMCL:  SandboxId "RETAIL" + RelyingParty "rp://api.minecraftservices.com/"
    - PCL CE: 不带 SandboxId   + RelyingParty "rp://api.minecraftservices.com/"
    Minecraft 登录只接受受众为 rp://api.minecraftservices.com/ 的令牌，两种写法受众一致，
    依次尝试；绝不回退到其他 RelyingParty（否则 MC 授权会报 Invalid app registration）。"""
    variants = [
        {"Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
         "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"},
        {"Properties": {"UserTokens": [xbl_token]},
         "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"},
    ]
    last = {}
    for payload in variants:
        code, data = net.post_json("https://xsts.auth.xboxlive.com/xsts/authorize",
                                   payload, headers={"Accept": "application/json"})
        if code == 200 and "Token" in data:
            uhs = ""
            try:
                uhs = data["DisplayClaims"]["xui"][0]["uhs"]
            except Exception:
                pass
            return uhs, data["Token"]
        last = data
    xerr = last.get("XErr")
    if xerr == 2148916233:
        raise AuthError("该微软账号还没有 Xbox 档案：请到 https://www.xbox.com "
                        "用此账号登录并按提示创建 Xbox 档案后重试")
    if xerr == 2148916242:
        raise AuthError(
            "Xbox Live 拒绝了此账号（错误码 2148916242）。你的账号地区正常且已购买游戏的"
            "情况下仍出现此错误时，请依次检查：1) 到 https://www.xbox.com 登录并确认 "
            "Xbox 档案已创建、服务协议已接受；2) 用官方 Minecraft 启动器登录一次"
            "（若官方也失败则是账号侧限制，与启动器无关）。或改用离线账号。")
    if xerr == 2148916238:
        raise AuthError("该账号是儿童账号，需家长同意后才能登录")
    if xerr in (2148916235, 2148916236):
        raise AuthError("该账号的年龄或地区信息不符合 Xbox Live 要求，"
                        "请到 account.microsoft.com 个人信息中核对出生日期与国家/地区")
    raise AuthError("XSTS 认证失败：" + str(xerr or last)[:200])


def mc_login_with_xbox(uhs: str, xsts_token: str) -> dict:
    code, data = net.post_json(
        "https://api.minecraftservices.com/authentication/login_with_xbox",
        {"identityToken": f"XBL3.0 x={uhs};{xsts_token}"})
    if code != 200 or "access_token" not in data:
        msg = str(data.get("errorMessage") or data)
        if "Invalid app registration" in msg:
            raise AuthError(
                "Invalid app registration：Minecraft 服务校验发起登录的 Azure 应用，"
                "自建应用需要通过 Mojang 的应用注册审核（企业认证，个人无法申请）。"
                "启动器将自动改用公共 Client ID 重新登录。原始信息：" + msg[:160])
        raise AuthError("Minecraft 授权失败：" + msg[:200])
    return data


def mc_profile(mc_token: str):
    import requests
    r = net.session.get("https://api.minecraftservices.com/minecraft/profile",
                        headers={"Authorization": f"Bearer {mc_token}"}, timeout=20)
    if r.status_code == 404:
        raise AuthError("该账号未购买 Minecraft Java 版，无法获取档案")
    if r.status_code != 200:
        raise AuthError(f"获取档案失败: HTTP {r.status_code}")
    d = r.json()
    return d.get("name", "Player"), d.get("id", "").replace("-", "")


def full_login_from_msa(msa_token: str, refresh_token: str = "", cid: str | None = None) -> dict:
    """MSA access_token -> 完整账号记录。"""
    xbl = xbl_authenticate(msa_token)
    uhs, xsts = xsts_authenticate(xbl)
    mc = mc_login_with_xbox(uhs, xsts)
    name, uuid = mc_profile(mc["access_token"])
    return {"type": "msa", "name": name, "uuid": uuid,
            "refresh_token": refresh_token,
            "cid": cid or _client_id(),
            "xuid": uhs, "mc_token": mc["access_token"],
            "mc_token_expire": time.time() + int(mc.get("expires_in", 86400)) - 120}


def _msa_chain(cid: str, on_code) -> dict:
    """完整的 MSA→Xbox→Minecraft 登录链（设备代码流）。"""
    device = device_code_start(cid)
    on_code(device.get("verification_uri", "https://www.microsoft.com/link"),
            device.get("user_code", ""))
    tokens = device_code_poll(device)
    return full_login_from_msa(tokens["access_token"], tokens.get("refresh_token", ""),
                               device.get("_cid"))


def _is_app_registration_error(err: Exception) -> bool:
    return "Invalid app registration" in str(err)


def begin_microsoft_login(on_code, on_done):
    """线程入口：on_code(url, user_code) 展示给用户；on_done(account|None, error|None)。
    自建 Azure 应用未通过 Mojang 应用注册审核时（Invalid app registration），
    自动改用公共 Client ID 重走一遍登录。"""
    try:
        account = _msa_chain(_client_id(), on_code)
        on_done(account, None)
    except AuthError as e:
        if _is_app_registration_error(e) and _client_id() != DEFAULT_CLIENT_ID:
            try:
                account = _msa_chain(DEFAULT_CLIENT_ID, on_code)
                on_done(account, None)
            except Exception as e2:
                on_done(None, str(e2))
        else:
            on_done(None, str(e))
    except Exception as e:
        on_done(None, str(e))


def ensure_auth_info(account: dict) -> AuthInfo:
    """启动游戏前获取可用的 MC 令牌（自动刷新）。"""
    if account.get("type") != "msa":
        return AuthInfo(account.get("name", "Player"), account.get("uuid", ""),
                        "0", user_type="legacy")
    # 缓存的 MC 令牌仍有效则直接用
    if account.get("mc_token") and time.time() < account.get("mc_token_expire", 0):
        return AuthInfo(account["name"], account["uuid"], account["mc_token"],
                        "msa", account.get("xuid", ""))
    try:
        tokens = msa_refresh(account["refresh_token"], account.get("cid"))
    except AuthError:
        raise
    new = full_login_from_msa(tokens["access_token"],
                              tokens.get("refresh_token") or account["refresh_token"],
                              account.get("cid"))
    new["type"] = "msa"
    # 合并进现有账号并保存
    accounts = config.load_accounts()
    for i, a in enumerate(accounts):
        if a.get("type") == "msa" and a.get("uuid") == new["uuid"]:
            accounts[i].update(new)
            break
    else:
        accounts.append(new)
    config.save_accounts(accounts)
    return AuthInfo(new["name"], new["uuid"], new["mc_token"], "msa", new.get("xuid", ""))


# ---------------- 离线账号 ----------------

def offline_uuid(name: str) -> str:
    """与官方服务端一致的离线 UUID（MD5("OfflinePlayer:"+name)）。"""
    h = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    h[6] = (h[6] & 0x0F) | 0x30  # version 3
    h[8] = (h[8] & 0x3F) | 0x80  # IETF variant
    s = h.hex()
    return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"
