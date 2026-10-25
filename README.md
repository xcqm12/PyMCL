# PyMCL — Python 编写的 Minecraft 启动器

[![Build & Release](https://github.com/xcqm12/PyMCL/actions/workflows/build.yml/badge.svg)](https://github.com/xcqm12/PyMCL/actions/workflows/build.yml)

一个类似 PCL 的 Minecraft Java 版启动器，用 Python + Tkinter 编写，单文件 exe，便携免安装。

![logo](assets/logo.png)

## 下载

- **正式版**：到 [Releases](https://github.com/xcqm12/PyMCL/releases) 下载 `PyMCL.exe`
- **开发版**：[Actions](https://github.com/xcqm12/PyMCL/actions) 每次推送自动构建，Artifact 里可取最新构建

发布流程：推送 `v*` 标签（如 `v1.0.0`）→ GitHub Actions 在 Windows 环境自动安装依赖、
生成 Logo、打包 exe、发布带 Release Notes 的正式版。

## 功能

- **游戏版本下载**：Mojang 官方全部版本（正式版 / 快照 / Beta / Alpha），BMCLAPI 国内镜像加速
- **加载器安装**（9 种）：
  - Forge / NeoForge（官方 headless 安装器自动运行）
  - Fabric / Quilt / LegacyFabric（官方 meta API）
  - OptiFine（官方无头安装器 `optifine.Installer QUIET`，APPDATA 重定向到自定义目录）
  - LiteLoader（versions.json 自动解析）
  - Cleanroom（GitHub Release 安装器）
  - LabyMod（拉起官方安装器）
- **资源市场**（Modrinth API）：模组 / 光影 / 材质包 / 整合包搜索，卡片式列表带图标，双栏布局
  （左侧项目卡片、右侧完整文件列表），支持 **MC 版本筛选** 与 **加载器筛选**
  （Fabric/Forge/NeoForge/Quilt），双击文件即安装
- **整合包导出**：把已安装版本导出为 **Modrinth .mrpack**（自动按 SHA1 反查 Modrinth 下载地址，
  无法识别的文件放入 overrides）/ **CurseForge .zip** / **纯备份 .zip**；可设置名称、作者、
  版本号、简介与包含内容（mods/config/resourcepacks/shaderpacks/options.txt）
- **整合包**：Modrinth `.mrpack` 一键安装（含 overrides、依赖加载器、独立游戏目录）；CurseForge `.zip` 导入（通过 cfwidget API 解析文件）
- **世界导入**：`.zip` / `.mcworld` 文件或 URL，自动识别 level.dat 根目录
- **正版登录**：Microsoft OAuth 设备代码流 → Xbox Live → XSTS → Minecraft 授权链，令牌自动刷新；
  备用方案：**自建 Azure 应用授权登录**（授权码流 + 本地回环回调，公共 Client ID 被限流时使用，
  窗口内含注册步骤指引）
- **离线账号**：标准离线 UUID（MD5 "OfflinePlayer:name" v3）
- **Java 管理**：自动扫描注册表与常见目录，按 MC 版本自动选择 Java 8/17/21，可一键从 Adoptium 下载 JRE
- **启动**：完整版本继承链合并、规则（os/arch/features）判定、natives 解压、资源索引与虚拟资源（1.6~1.7）、多线程下载 + SHA1 校验、整合包独立目录、游戏日志落盘

## 使用

```
PyMCL.exe            # 直接运行，所有数据保存在 exe 同目录
```

- 首次使用：**账户** 页添加账号 → **下载** 页安装版本 → **主页** 点「启动游戏」
- 配置文件：`launcher.json`（游戏目录、内存、Java、下载线程、镜像开关等）
- 离线需要的 Java：MC 1.20.5+ 需 Java 21，1.18+ 需 Java 17，1.17 需 Java 16，更早版本 Java 8（设置页可自动下载）

## 开发运行

```bash
pip install requests pillow
python main.py
```

## 打包

```bash
build.bat        # 生成 Logo/图标 + PyInstaller 单文件打包 → dist/PyMCL.exe
```

## 测试

```bash
python tools/smoke_test.py [--full]   # 核心逻辑联网冒烟测试（清单/各加载器列表/下载校验/OptiFine 无头安装等）
python tools/gui_smoke.py             # GUI 冒烟测试
```

## 更新日志

### v1.0.9
- 修复：XSTS 授权只接受受众为 `rp://api.minecraftservices.com/` 的令牌——此前回退到
  `http://xboxlive.com` 受众的令牌会导致 Minecraft 授权报 `Invalid app registration`
- 修复：`login_with_xbox` 失败时给出可读原因；XSTS 失败时抛出真实错误码而非被回退掩盖

### v1.0.8
- 新增樱花二次元主题：dmoe.cc 随机壁纸作主页横幅与市场底图（压暗合成保证可读），
  设置页可开关 / 换一张 / 自定义地址

### v1.0.5 ~ v1.0.7
- 数据包（Datapack）下载：自动列出存档选择目标世界，安装到 `saves/<世界>/datapacks/`
- 恢复资源市场左右双栏布局；正式打包版默认隐藏备用授权（账户页右下角可开关）
- 登录：本地回环授权码流支持 **PKCE (S256)**，兼容 SPA/Web/公共客户端三种平台配置
- 登录：XSTS 请求改用 `SandboxId: RETAIL`（与 HMCL/minecraft-launcher-lib/官方一致）
- 错误提示中文化：XErr 2148916242 / 2148916233 / 2148916238 等给出具体排查步骤

### v1.0.0 ~ v1.0.4
- 首个正式版：原版 + 9 种加载器安装、微软正版登录、Modrinth 市场（图标/文件列表/
  标签/排序筛选）、整合包导入导出、世界导入、Java 管理、GitHub Actions 自动发布

## 常见登录错误与解决（开发过程实录）

| 错误 | 原因 | 解决 |
|---|---|---|
| `AADSTS900144: request body must contain 'client_id'` | MSA 端点只接受**表单编码**请求体，用 JSON 发送会被当作空请求体 | 改为 `application/x-www-form-urlencoded` |
| `invalid_client`（随手填的 Client ID） | Azure 应用不存在 | 使用真实公共 Client ID 或自建应用 |
| `The application is a first party application, the user does not have consent...` | 借用 Azure CLI 等第一方应用的 Client ID，用户无法为 Xbox Live 授权 | 换第三方应用（如 Prism 的公共 ID）或自建 |
| `AADSTS70002: must be marked as 'mobile'`（设备代码流） | 应用未开启「允许公共客户端流」 | 应用注册 → 身份验证 → 允许公共客户端流 = 是 |
| `Proof Key for Code Exchange is required` | 应用要求 PKCE（SPA 平台或策略强制） | 授权 URL 带 `code_challenge`+`S256`，换令牌带 `code_verifier` |
| `AADSTS70002: must include a 'client_secret'` | 应用注册在「Web」平台（机密客户端） | 填入 Client Secret，或把重定向 URI 移到「移动和桌面应用」平台 |
| `AADSTS50011: redirect URI mismatch` | 回调地址未注册 | 注册 `http://localhost`（不带端口）到「移动和桌面应用」平台 |
| `XErr 2148916242` | Xbox Live 拒绝：账号地区不支持 / Xbox 档案问题。**挂 VPN 无效**（检查基于账号注册地区而非 IP） | account.microsoft.com 改地区 → xbox.com 登录创建档案；或用离线账号 |
| `Invalid app registration`（login_with_xbox） | XSTS 令牌受众不对：用了 `RelyingParty: http://xboxlive.com` 签出的令牌去登 Minecraft | XSTS 只用 `RelyingParty: rp://api.minecraftservices.com/` + `SandboxId: RETAIL` |
| OptiFine 安装后没有新版本目录 | OptiFine 无头安装器只认 `APPDATA` 定位游戏目录 | 子进程重定向 `APPDATA=<游戏根目录的上级>`，运行 `optifine.Installer QUIET` |

## 目录结构

```
mclauncher/        核心库
  config.py        配置与账号持久化（RLock 保护）
  net.py           HTTP + BMCLAPI 镜像映射 + 流式下载(sha1/重试)
  downloads.py     多线程下载管理器
  versions.py      版本清单/继承链合并/库与资源收集/校验
  installers.py    原版 + 9 种加载器安装
  market.py        Modrinth 搜索/整合包(mrpack+CurseForge)/世界导入
  auth.py          微软设备代码流登录 / 离线账号
  javafind.py      Java 检测/推荐/Adoptium 自动下载
  launch.py        启动参数拼装与进程启动
gui/               Tkinter 界面（深色扁平，5 页 + 对话框）
tools/             gen_logo.py / smoke_test.py / gui_smoke.py
```

## 声明

仅供学习交流。Minecraft 版权归 Mojang/Microsoft 所有；正版登录使用 Microsoft 官方 OAuth 接口，游戏文件下载自 Mojang 官方源与 BMCLAPI 公共镜像。
