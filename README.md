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
