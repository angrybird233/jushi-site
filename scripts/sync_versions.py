#!/usr/bin/env python3
"""把 Gitee 更新源的版本清单同步到站点仓库，作为前端实时接口失败时的兜底快照。

数据源：https://gitee.com/angrygird233/jushi-update （master 分支）
  - version-public.json  手机版
  - version-tv.json      电视版

优先走 raw 直链；失败时回退到 Gitee OpenAPI 的 contents 接口（base64）。
GitHub Actions 每天调用一次；也可以本地直接运行：
    python scripts/sync_versions.py --out-dir .
"""

import argparse
import base64
import json
import os
import sys
import urllib.request

OWNER = "angrygird233"
REPO = "jushi-update"
BRANCH = "master"
FILES = ("version-public.json", "version-tv.json")
RAW_BASE = "https://gitee.com/{}/{}/raw/{}/".format(OWNER, REPO, BRANCH)
API_BASE = "https://gitee.com/api/v5/repos/{}/{}/contents/".format(OWNER, REPO)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "jushi-site-version-sync"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def validate(obj, name):
    """只保留结构完整的清单，避免把半截响应写进仓库。"""
    if not isinstance(obj, dict):
        raise ValueError("{}: 顶层不是对象".format(name))
    for key in ("version", "apkUrl"):
        if not obj.get(key):
            raise ValueError("{}: 缺少 {}".format(name, key))
    if not str(obj["apkUrl"]).startswith("https://"):
        raise ValueError("{}: apkUrl 必须是 https 地址".format(name))


def read_manifest(name):
    errors = []
    try:
        obj = json.loads(fetch(RAW_BASE + name).decode("utf-8"))
        validate(obj, name)
        return obj, "raw"
    except Exception as exc:  # noqa: BLE001 - 两个源任意一个可用即可
        errors.append("raw: {}".format(exc))

    try:
        payload = json.loads(fetch(API_BASE + name + "?ref=" + BRANCH).decode("utf-8"))
        if payload.get("encoding") != "base64" or not payload.get("content"):
            raise ValueError("contents 接口未返回 base64 内容")
        obj = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
        validate(obj, name)
        return obj, "api"
    except Exception as exc:  # noqa: BLE001
        errors.append("api: {}".format(exc))

    raise RuntimeError("; ".join(errors))


def main():
    parser = argparse.ArgumentParser(description="同步 Gitee 版本清单到站点仓库")
    parser.add_argument("--out-dir", default=".", help="输出目录，默认当前目录")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    summary = []
    for name in FILES:
        obj, source = read_manifest(name)
        path = os.path.join(args.out_dir, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        line = "{}: v{} (来源 {})".format(name, obj["version"], source)
        summary.append(line)
        print(line)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("## 版本清单同步结果\n")
            fh.write("\n".join("- " + line for line in summary) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - 交给 CI 判定失败
        print("同步失败: {}".format(exc), file=sys.stderr)
        sys.exit(1)
