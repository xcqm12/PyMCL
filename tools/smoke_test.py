"""核心逻辑联网冒烟测试。用法: python tools/smoke_test.py [--full]"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mclauncher import auth, config, installers, javafind, market, net, versions
from mclauncher.downloads import DownloadManager, Job

FULL = "--full" in sys.argv
results = []


def check(name, fn):
    try:
        out = fn()
        results.append((name, True, out))
        print(f"[PASS] {name}: {out}")
    except Exception as e:
        results.append((name, False, str(e)))
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")


def t_manifest():
    m = versions.manifest()
    assert len(m["versions"]) > 500
    return f"{len(m['versions'])} versions, latest={m['latest']['release']}"

def t_fetch_version_json():
    vj = versions.fetch_version_json("1.20.1")
    assert vj["id"] == "1.20.1"
    assert versions.load_json("1.20.1") is not None
    return "1.20.1 json ok"

def t_fabric():
    lst = installers.list_fabric_like("fabric", "1.20.1")
    assert lst, "fabric loader list empty"
    vid = installers.install_fabric_like("fabric", "1.20.1", lst[0],
                                         version_id="smoke-fabric")
    vj = versions.load_json(vid)
    assert vj["inheritsFrom"] == "1.20.1"
    chain = versions.load_chain(vid)
    merged = versions.merge_chain(chain)
    assert "KnotClient" in merged["mainClass"]
    return f"loader {lst[0]}, libs={len(merged['libraries'])}"

def t_forge_list():
    lst = installers.list_forge("1.20.1")
    assert lst
    return f"{len(lst)} builds, latest={lst[0]}"

def t_neoforge_list():
    lst = installers.list_neoforge("1.21.1")
    assert lst
    return f"{len(lst)} builds, latest={lst[0]}"

def t_optifine_list():
    lst = installers.list_optifine("1.12.2")
    assert lst
    return f"{len(lst)} patches, top={lst[0]['type']}_{lst[0]['patch']}"

def t_liteloader():
    lst = installers.list_liteloader()
    assert lst
    return f"{lst[:3]}"

def t_cleanroom():
    lst = installers.list_cleanroom()
    assert lst
    return f"{len(lst)} releases, top={lst[0]['tag']}"

def t_labymod_url():
    # 仅 HEAD 探测，不安装
    import requests
    r = requests.head("https://dl.labymod.net/latest/install/LabyMod3_Installer.jar",
                      timeout=20, allow_redirects=True)
    assert r.status_code == 200
    return "installer reachable"

def t_modrinth():
    hits = market.search("sodium", "mod", game_version="1.20.1")
    assert hits and hits[0]["title"]
    pvs = market.project_versions(hits[0]["project_id"], game_version="1.20.1", loader="fabric")
    assert pvs and market.pick_version_file(pvs[0])
    return f"top={hits[0]['title']}, {len(pvs)} files for 1.20.1 fabric"

def t_download_libs_sample():
    merged = versions.merge_chain(versions.load_chain("1.20.1"))
    tasks = versions.lib_tasks(merged)
    assert len(tasks) > 50
    small = sorted([t for t in tasks if t.size and t.size < 300000], key=lambda t: t.size)[:3]
    for t in small:
        got = net.download_stream(t.url, t.dest, sha1=t.sha1, size=t.size)
        assert got == t.size
    return f"{len(tasks)} libs total, downloaded {len(small)} samples w/ sha1"

def t_asset_index():
    merged = versions.merge_chain(versions.load_chain("1.20.1"))
    idx = versions.asset_index(merged)
    tasks = versions.asset_tasks(idx)
    assert len(tasks) > 3000
    return f"index={idx.get('id')}, {len(tasks)} assets"

def t_full_download():
    if not FULL:
        return "skipped (add --full)"
    dl = DownloadManager()
    s = versions.ensure_version("smoke-fabric", dl, skip_assets=True)
    return s

def t_offline_uuid():
    u1, u2 = auth.offline_uuid("Player"), auth.offline_uuid("Player")
    assert u1 == u2 and len(u1) == 36 and u1[14] == "3"
    return u1

def t_java_detect():
    javas = javafind.detect_javas()
    return f"{len(javas)} javas: " + "; ".join(f"{j['major']}@{j['path'][:40]}" for j in javas[:3])

def t_build_command():
    from mclauncher import launch
    vid = "smoke-fabric"
    class A: pass
    a = A(); a.name="Tester"; a.uuid=auth.offline_uuid("Tester"); a.access_token="0"
    a.user_type="msa"; a.xuid=""
    argv, gdir = launch.build_command(vid, a, "java.exe", 1280, 720)
    assert "KnotClient" in " ".join(argv)
    assert "--width" in argv and "--height" in argv
    return f"{len(argv)} args, mainClass ok"

def t_optifine_install():
    # 真实运行 OptiFine headless 安装器（需要原版 client jar）
    dl = DownloadManager()
    versions.ensure_version("1.12.2", dl, skip_assets=True)
    lst = installers.list_optifine("1.12.2")
    top = lst[0]
    javas = javafind.detect_javas()
    java = javas[0]["path"] if javas else "java"
    vid = installers.install_optifine("1.12.2", top["type"], top["patch"], java, dl,
                                      lambda s: None)
    vj = versions.load_json(vid)
    assert vj.get("inheritsFrom") == "1.12.2", "inheritsFrom missing"
    oflibs = [l for l in vj.get("libraries", []) if l.get("name", "").startswith("optifine:")]
    assert oflibs, "optifine lib not injected"
    return f"{vid}, lib={oflibs[0]['name']}"

def t_liteloader_install():
    dl = DownloadManager()
    vid = installers.install_liteloader("1.12.2", dl, lambda s: None)
    vj = versions.load_json(vid)
    assert vj.get("inheritsFrom") == "1.12.2"
    assert "--tweakClass" in vj.get("minecraftArguments", "")
    of = [l for l in vj["libraries"] if "liteloader" in l.get("name", "")]
    assert of, "liteloader lib missing"
    return f"{vid}, lib={of[0]['name']}, url={of[0]['downloads']['artifact']['url'][:40]}"

def t_liteloader_json_shape():
    data = net.get_json("https://dl.liteloader.com/versions/versions.json")
    info = data["versions"].get("1.12.2")
    if info:
        return f"1.12.2 keys={sorted(info.keys())[:8]}"
    return f"versions: {list(data['versions'].keys())[:5]}"


print("=== PyMCL 核心冒烟测试 ===")
check("版本清单", t_manifest)
check("原版版本 JSON", t_fetch_version_json)
check("Fabric 元数据", t_fabric)
check("Forge 列表", t_forge_list)
check("NeoForge 列表", t_neoforge_list)
check("OptiFine 列表", t_optifine_list)
check("LiteLoader 列表", t_liteloader)
check("LiteLoader JSON 结构", t_liteloader_json_shape)
check("Cleanroom 列表", t_cleanroom)
check("LabyMod 安装器可达", t_labymod_url)
check("Modrinth 搜索", t_modrinth)
check("库下载+校验", t_download_libs_sample)
check("资源索引", t_asset_index)
check("完整版本下载(--full)", t_full_download)
check("离线 UUID", t_offline_uuid)
check("Java 检测", t_java_detect)
check("启动命令拼装", t_build_command)
check("OptiFine 无头安装", t_optifine_install)
check("LiteLoader 安装", t_liteloader_install)

fails = [r for r in results if not r[1]]
print(f"\n=== {len(results)-len(fails)}/{len(results)} 通过 ===")
sys.exit(1 if fails else 0)
