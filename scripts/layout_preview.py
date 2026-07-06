#!/usr/bin/env python3
"""Screan 布局编辑器 + 图片管理 + 实时预览。

浏览器打开 http://<Pi-IP>:8765/ 就能:
  - 拖动 widget / 拉伸边角(网格 4px 吸附)
  - 添加 / 删除 widget,从下拉列表选类型
  - 上传图片,自动出现在 media 侧边栏,拖到画布变成 image widget
  - 保存 → 直接写 config.toml
  - 应用到屏幕 → sync 代码 + restart screan 服务

零依赖:只用 Python 3.11+ 标准库 (tomllib + http.server)。
"""
from __future__ import annotations
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from email.parser import BytesParser
from email.policy import default as email_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# widget 类型 → 展示色 + 是否需要 path
COLORS = {
    "clock":       "hsl(220 70% 55% / .85)",
    "cpu":         "hsl(210 80% 55% / .85)",
    "memory":      "hsl(150 60% 45% / .85)",
    "disk":        "hsl(280 55% 55% / .85)",
    "temperature": "hsl(20 85% 55% / .85)",
    "network":     "hsl(180 60% 45% / .85)",
    "host":        "hsl(45 85% 55% / .85)",
    "weather":     "hsl(200 60% 60% / .85)",
    "image":       "hsl(320 55% 55% / .85)",
    "_unknown":    "hsl(0 0% 60% / .85)",
}

WIDGET_TYPES = ["clock", "cpu", "memory", "disk", "temperature",
                "network", "host", "weather", "image"]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


# ============================ TOML 读写 ============================

def load_config(config_path: Path) -> dict:
    """解析 config.toml 返回 dict。"""
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def layout_from_config(cfg: dict) -> dict:
    """从 config dict 抽出编辑器需要的 layout。"""
    disp = cfg.get("display", {})
    rot = disp.get("rotation", 1)
    if rot in (1, 3):
        screen_w, screen_h = 480, 320
    else:
        screen_w, screen_h = 320, 480

    widgets = []
    for i, w in enumerate(cfg.get("widgets", [])):
        t = w.get("type", "?")
        r = w.get("rect", [0, 0, 0, 0])
        if not (isinstance(r, list) and len(r) == 4):
            continue
        try:
            x, y, ww, hh = (int(v) for v in r)
        except (ValueError, TypeError):
            continue
        item = {
            "type": t, "x": x, "y": y, "w": ww, "h": hh,
            "options": {k: v for k, v in w.items()
                        if k not in ("type", "rect")},
        }
        widgets.append(item)

    # 检查重叠 / 越界
    for a in widgets:
        a["out_of_bounds"] = not (
            0 <= a["x"] and 0 <= a["y"]
            and a["x"] + a["w"] <= screen_w
            and a["y"] + a["h"] <= screen_h
        )
    for i, a in enumerate(widgets):
        overlaps = []
        for j, b in enumerate(widgets):
            if i == j:
                continue
            if (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                    and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]):
                overlaps.append(j)
        a["overlaps"] = overlaps

    return {
        "screen_w": screen_w, "screen_h": screen_h,
        "rotation": rot,
        "widgets": widgets,
    }


def save_widgets_to_config(config_path: Path, widgets: list[dict]) -> None:
    """把 widgets 数组写回 config.toml,保留其他块(display/render/sampling)不变。

    做法:读原文件文本,找到第一个 [[widgets]] 位置,截断后再拼接新的 widgets 段。
    如果没有 [[widgets]],就追加到末尾。保留原有的 [display]/[render]/[sampling]。
    """
    text = config_path.read_text(encoding="utf-8")

    # 找 [[widgets]] 段开始位置(第一个)
    m = re.search(r"^\s*\[\[widgets\]\]", text, re.MULTILINE)
    if m:
        head = text[: m.start()].rstrip() + "\n\n"
    else:
        head = text.rstrip() + "\n\n"

    # 生成新的 widgets 段
    lines = ["# widgets (由 layout 编辑器生成/管理)"]
    for w in widgets:
        lines.append("")
        lines.append("[[widgets]]")
        lines.append(f'type = "{w["type"]}"')
        lines.append(f'rect = [{w["x"]}, {w["y"]}, {w["w"]}, {w["h"]}]')
        for k, v in (w.get("options") or {}).items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f'{k} = {"true" if v else "false"}')
            elif isinstance(v, (int, float)):
                lines.append(f'{k} = {v}')
    tail = "\n".join(lines) + "\n"

    config_path.write_text(head + tail, encoding="utf-8")


# ============================ 服务器 ============================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    # 由 main() 设置的类属性
    config_path: Path = Path("config.toml")
    media_dir: Path = Path("./media")
    deployed_config: Path = Path("/opt/screan/config.toml")
    deployed_media: Path = Path("/opt/screan/media")
    install_script: Path = Path("./scripts/install.sh")

    # ---- 通用 ----

    def _send_json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200,
                   content_type: str = "text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- GET ----

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._send_text(INDEX_HTML.replace(
                "__COLORS_JSON__", json.dumps(COLORS)
            ).replace(
                "__TYPES_JSON__", json.dumps(WIDGET_TYPES)
            ), content_type="text/html; charset=utf-8")
        elif path == "/api/layout":
            try:
                cfg = load_config(self.config_path)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
                return
            data = layout_from_config(cfg)
            data["config_path"] = str(self.config_path)
            data["media_dir"] = str(self.media_dir)
            self._send_json(data)
        elif path == "/api/media":
            self._send_json({"files": self._list_media()})
        elif path.startswith("/media/"):
            # 直接返回图片文件(用于 UI 缩略图)
            name = path[len("/media/"):]
            self._serve_media(name)
        else:
            self.send_error(404)

    def _list_media(self) -> list[dict]:
        if not self.media_dir.is_dir():
            return []
        out = []
        for f in sorted(self.media_dir.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                out.append({
                    "name": f.name,
                    # 关键:返回 screan 服务能看到的路径 (/opt/screan/media/...)
                    # screan systemd 设了 ProtectHome=true,访问不了 /home/
                    "path": str(self.deployed_media / f.name),
                    "size": f.stat().st_size,
                })
            except OSError:
                pass
        return out

    def _serve_media(self, name: str) -> None:
        # 防目录穿越
        if ".." in name or name.startswith("/"):
            self.send_error(400)
            return
        p = self.media_dir / name
        if not p.is_file():
            self.send_error(404)
            return
        ext = p.suffix.lower()
        mime = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png",  ".bmp": "image/bmp",
            ".gif": "image/gif",  ".webp": "image/webp",
        }.get(ext, "application/octet-stream")
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ---- POST ----

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/save":
            self._handle_save()
        elif path == "/api/upload":
            self._handle_upload()
        elif path == "/api/apply":
            self._handle_apply()
        elif path == "/api/delete-media":
            self._handle_delete_media()
        else:
            self.send_error(404)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _handle_save(self) -> None:
        try:
            data = self._read_json()
            widgets = data.get("widgets", [])
            # 校验
            cfg = load_config(self.config_path)
            layout = layout_from_config(cfg)
            sw, sh = layout["screen_w"], layout["screen_h"]
            for w in widgets:
                if not (0 <= w["x"] and 0 <= w["y"]
                        and w["x"] + w["w"] <= sw
                        and w["y"] + w["h"] <= sh):
                    raise ValueError(
                        f"widget {w['type']} 越界: "
                        f"[{w['x']},{w['y']},{w['w']},{w['h']}] 超过 {sw}×{sh}"
                    )
                if w["type"] not in WIDGET_TYPES:
                    raise ValueError(f"未知类型: {w['type']}")
                if w["w"] < 8 or w["h"] < 8:
                    raise ValueError(f"widget {w['type']} 太小 (< 8px)")
            save_widgets_to_config(self.config_path, widgets)
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"error": f"{type(e).__name__}: {e}"}, status=400)

    def _handle_upload(self) -> None:
        """multipart/form-data,字段名 'file'。手动解析(Python 3.13 移除了 cgi)。"""
        try:
            ctype = self.headers.get("Content-Type", "")
            if not ctype.lower().startswith("multipart/"):
                raise ValueError("需要 multipart/form-data")
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                raise ValueError("empty body")
            body = self.rfile.read(length)
            # 用 email 模块解析 multipart(标准库,Python 3.13 保留)
            # 把 Content-Type header 塞进去当 message header
            wrapped = b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body
            msg = BytesParser(policy=email_default).parsebytes(wrapped)
            if not msg.is_multipart():
                raise ValueError("非 multipart 消息")
            for part in msg.iter_parts():
                cd = part.get("Content-Disposition", "")
                if 'name="file"' not in cd:
                    continue
                # 提取原始文件名
                m = re.search(r'filename="([^"]*)"', cd)
                orig = m.group(1) if m else "upload"
                filename = os.path.basename(orig)
                filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
                if not filename or filename.startswith("."):
                    filename = "upload.png"
                ext = Path(filename).suffix.lower()
                if ext not in IMAGE_EXTS:
                    raise ValueError(f"不支持的图片格式: {ext}")
                data = part.get_payload(decode=True) or b""
                if not data:
                    raise ValueError("空文件")

                self.media_dir.mkdir(parents=True, exist_ok=True)
                dst = self.media_dir / filename
                n = 1
                while dst.exists():
                    stem = Path(filename).stem
                    dst = self.media_dir / f"{stem}_{n}{ext}"
                    n += 1
                dst.write_bytes(data)
                self._send_json({
                    "ok": True, "name": dst.name,
                    # 前端要用来写进 config 的路径 → screan 视角
                    "path": str(self.deployed_media / dst.name),
                })
                return
            raise ValueError("缺少 file 字段")
        except Exception as e:
            self._send_json({"error": f"{type(e).__name__}: {e}"}, status=400)

    def _handle_delete_media(self) -> None:
        try:
            data = self._read_json()
            name = data.get("name", "")
            if not name or "/" in name or ".." in name:
                raise ValueError("bad name")
            p = self.media_dir / name
            if p.is_file():
                p.unlink()
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"error": str(e)}, status=400)

    def _handle_apply(self) -> None:
        """sync 代码 + restart 服务。需要 sudo 权限。"""
        try:
            steps = []
            # 1. 把 config.toml 复制到 /opt/screan
            r = subprocess.run(
                ["sudo", "-n", "cp", str(self.config_path),
                 str(self.deployed_config)],
                capture_output=True, text=True, timeout=10,
            )
            steps.append({"step": "copy config", "rc": r.returncode,
                          "out": r.stdout, "err": r.stderr})
            if r.returncode != 0:
                self._send_json({"error": "sudo cp 失败", "steps": steps},
                                status=500)
                return

            # 2. 同步 media(用 sudo rsync)
            r = subprocess.run(
                ["sudo", "-n", "rsync", "-a", "--delete",
                 str(self.media_dir) + "/", "/opt/screan/media/"],
                capture_output=True, text=True, timeout=30,
            )
            steps.append({"step": "sync media", "rc": r.returncode,
                          "out": r.stdout, "err": r.stderr})

            # 3. 同步源码 + 重启(install.sh sync)
            r = subprocess.run(
                ["sudo", "-n", "bash", str(self.install_script), "sync"],
                capture_output=True, text=True, timeout=60,
            )
            steps.append({"step": "install.sh sync", "rc": r.returncode,
                          "out": r.stdout, "err": r.stderr})
            if r.returncode != 0:
                self._send_json({"error": "install.sh sync 失败",
                                 "steps": steps}, status=500)
                return
            self._send_json({"ok": True, "steps": steps})
        except Exception as e:
            self._send_json({"error": f"{type(e).__name__}: {e}"}, status=500)


# ============================ HTML ============================

INDEX_HTML = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Screan Layout Editor</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    font: 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #1c1c1e; color: #eee;
    display: flex; height: 100vh;
  }
  aside {
    width: 240px; flex-shrink: 0; padding: 14px;
    background: #262629; overflow-y: auto; border-right: 1px solid #333;
  }
  aside h2 { margin: 12px 0 8px; font-size: 12px; text-transform: uppercase;
             color: #888; font-weight: 600; letter-spacing: .5px; }
  main { flex: 1; padding: 20px; overflow: auto; }

  button, select, input[type=text], input[type=number] {
    font: inherit; border: 1px solid #444; background: #2c2c2e; color: #eee;
    padding: 6px 10px; border-radius: 4px;
  }
  button { cursor: pointer; }
  button:hover { background: #3a3a3c; }
  button.primary { background: #0a84ff; border-color: #0a84ff; color: #fff; }
  button.primary:hover { background: #0071ea; }
  button.danger { background: #ff453a; border-color: #ff453a; color: #fff; }
  button.danger:hover { background: #e83b32; }

  .toolbar {
    display: flex; gap: 8px; align-items: center; margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .toolbar .grow { flex: 1; }
  .status {
    font-size: 12px; padding: 4px 10px; border-radius: 3px;
    background: #333;
  }
  .status.ok { background: #1a5c1a; }
  .status.err { background: #5c1a1a; }

  #stage-wrap {
    position: relative;
    padding: 22px 0 0 34px;
  }
  #stage {
    background: #f5f5f7;
    position: relative;
    box-shadow: 0 8px 32px rgba(0,0,0,.5);
    border-radius: 3px;
    /* 明显的可编辑边界 */
    outline: 2px solid #0a84ff44;
  }
  .grid-bg {
    position: absolute; inset: 0; pointer-events: none;
    background-image:
      linear-gradient(to right,  rgba(0,0,0,.06) 1px, transparent 1px),
      linear-gradient(to bottom, rgba(0,0,0,.06) 1px, transparent 1px);
    background-size: calc(var(--scale) * 20px) calc(var(--scale) * 20px);
  }
  .widget {
    position: absolute;
    color: #fff; font-size: 12px;
    padding: 4px 6px;
    overflow: hidden;
    border-radius: 3px;
    text-shadow: 0 1px 2px rgba(0,0,0,.5);
    user-select: none;
    cursor: move;
    outline: 2px solid rgba(0,0,0,.25);
  }
  .widget.selected {
    outline: 2px solid #0a84ff;
    box-shadow: 0 0 0 4px rgba(10,132,255,.25);
    z-index: 10;
  }
  .widget.bad {
    outline-color: #ff453a !important;
  }
  .widget .type { font-weight: 700; font-size: 13px; line-height: 1.2; }
  .widget .dim { opacity: .85; font-family: monospace; font-size: 10px; line-height: 1.1; }
  .widget img.preview {
    position: absolute; inset: 0;
    width: 100%; height: 100%; object-fit: contain;
    pointer-events: none;
    opacity: .85;
  }
  .handle {
    position: absolute;
    width: 10px; height: 10px;
    background: #0a84ff; border: 1.5px solid #fff;
    border-radius: 50%;
    z-index: 20;
  }
  .handle.tl { top: -6px; left: -6px; cursor: nwse-resize; }
  .handle.tr { top: -6px; right: -6px; cursor: nesw-resize; }
  .handle.bl { bottom: -6px; left: -6px; cursor: nesw-resize; }
  .handle.br { bottom: -6px; right: -6px; cursor: nwse-resize; }
  .handle.tm { top: -6px; left: 50%; margin-left: -5px; cursor: ns-resize; }
  .handle.bm { bottom: -6px; left: 50%; margin-left: -5px; cursor: ns-resize; }
  .handle.lm { left: -6px; top: 50%; margin-top: -5px; cursor: ew-resize; }
  .handle.rm { right: -6px; top: 50%; margin-top: -5px; cursor: ew-resize; }

  .ruler-x, .ruler-y { position: absolute; color: #666;
                        font-size: 10px; font-family: monospace; }
  .ruler-x { top: 4px; left: 34px; right: 0; height: 14px; }
  .ruler-y { top: 22px; left: 0; bottom: 0; width: 30px; text-align: right; }
  .ruler-x span, .ruler-y span { position: absolute; }
  .ruler-y span { right: 4px; }

  .media-list {
    display: grid; grid-template-columns: 1fr 1fr; gap: 6px;
  }
  .media-item {
    position: relative; background: #1c1c1e; border-radius: 3px;
    padding: 4px; cursor: grab; text-align: center; overflow: hidden;
  }
  .media-item.dragging { opacity: .5; }
  .media-item img {
    width: 100%; height: 60px; object-fit: cover; display: block;
    border-radius: 2px; background: #333;
  }
  .media-item .name {
    font-size: 10px; word-break: break-all; margin-top: 2px;
    color: #aaa;
  }
  .media-item .del {
    position: absolute; top: 2px; right: 2px;
    width: 16px; height: 16px; border-radius: 50%;
    background: rgba(255,69,58,.85); color: #fff;
    font-size: 12px; line-height: 14px; text-align: center;
    cursor: pointer; opacity: 0; transition: opacity .1s;
  }
  .media-item:hover .del { opacity: 1; }
  .media-item .show-btn {
    display: block; width: 100%; margin-top: 4px;
    padding: 4px 6px; font-size: 11px;
    background: #0a84ff; color: #fff; border: none;
    border-radius: 3px; cursor: pointer;
  }
  .media-item .show-btn:hover { background: #0071ea; }
  .media-item .show-btn:disabled { background: #555; cursor: wait; }

  #upload-hint {
    padding: 8px; border: 1.5px dashed #555; text-align: center;
    color: #888; border-radius: 4px; margin-bottom: 8px;
    font-size: 12px;
  }
  #upload-hint.drag { border-color: #0a84ff; color: #0a84ff; }
  #file-input { display: none; }

  .inspector {
    background: #1c1c1e; padding: 10px; border-radius: 4px;
    margin-top: 12px; font-size: 12px;
  }
  .inspector .row { display: flex; align-items: center; gap: 8px;
                     margin-bottom: 6px; }
  .inspector .row label { width: 40px; color: #888; }
  .inspector .row input { flex: 1; }
  .legend { margin-top: 20px; font-size: 11px; color: #888; }
  .legend .swatch { display: inline-block; width: 10px; height: 10px;
                     border-radius: 2px; margin-right: 4px;
                     vertical-align: middle; }
  .legend div { margin-bottom: 3px; }
  .error {
    background: #5c1a1a; padding: 8px 10px; border-radius: 3px;
    font-family: monospace; white-space: pre-wrap;
    font-size: 11px; margin-bottom: 10px;
  }
</style>
</head>
<body>

<aside>
  <h2>添加 widget</h2>
  <div style="display:flex; gap:6px;">
    <select id="new-type" style="flex:1"></select>
    <button onclick="addWidget()">+</button>
  </div>

  <h2>图片素材</h2>
  <div id="upload-hint">
    拖到这里上传 &nbsp;/&nbsp; <a href="#" onclick="document.getElementById('file-input').click(); return false;" style="color:#0a84ff">选择文件</a>
  </div>
  <input type="file" id="file-input" accept="image/*" multiple>
  <div class="media-list" id="media-list"></div>

  <div class="inspector" id="inspector" style="display:none">
    <h2 style="margin-top:0">选中 widget</h2>
    <div class="row"><label>type</label>
      <select id="ins-type"></select></div>
    <div class="row"><label>x</label><input type="number" id="ins-x"></div>
    <div class="row"><label>y</label><input type="number" id="ins-y"></div>
    <div class="row"><label>w</label><input type="number" id="ins-w"></div>
    <div class="row"><label>h</label><input type="number" id="ins-h"></div>
    <div class="row" id="ins-path-row" style="display:none">
      <label>path</label><input type="text" id="ins-path"></div>
    <button class="danger" onclick="deleteSelected()">删除此 widget</button>
  </div>

  <div class="legend" id="legend"></div>
</aside>

<main>
  <div class="toolbar">
    <button class="primary" onclick="save()">💾 保存 config.toml</button>
    <button class="primary" onclick="apply()">🚀 应用到屏幕</button>
    <span class="grow"></span>
    <label>缩放
      <input type="range" id="scale" min="1" max="3" step="0.1" value="2"
             style="width:100px">
      <span id="scaleVal">2.0×</span>
    </label>
    <label><input type="checkbox" id="snap" checked> 4px 吸附</label>
    <span class="status" id="status">就绪</span>
  </div>
  <div id="error"></div>
  <div id="stage-wrap">
    <div class="ruler-x" id="rulerX"></div>
    <div class="ruler-y" id="rulerY"></div>
    <div id="stage"></div>
  </div>
</main>

<script>
const COLORS = __COLORS_JSON__;
const TYPES = __TYPES_JSON__;

// ---- state ----
let layout = null;        // {screen_w, screen_h, widgets:[...]}
let selectedIdx = -1;
let dirty = false;

// ---- refs ----
const stage = document.getElementById('stage');
const scaleEl = document.getElementById('scale');
const scaleValEl = document.getElementById('scaleVal');
const snapEl = document.getElementById('snap');
const statusEl = document.getElementById('status');
const errorEl = document.getElementById('error');
const mediaListEl = document.getElementById('media-list');
const uploadHint = document.getElementById('upload-hint');
const fileInput = document.getElementById('file-input');
const inspector = document.getElementById('inspector');
const insType = document.getElementById('ins-type');
const insX = document.getElementById('ins-x');
const insY = document.getElementById('ins-y');
const insW = document.getElementById('ins-w');
const insH = document.getElementById('ins-h');
const insPath = document.getElementById('ins-path');
const insPathRow = document.getElementById('ins-path-row');
const newType = document.getElementById('new-type');

// ---- init dropdowns ----
TYPES.forEach(t => {
  newType.appendChild(new Option(t, t));
  insType.appendChild(new Option(t, t));
});

// ---- fetch ----
async function loadLayout() {
  const r = await fetch('/api/layout');
  const d = await r.json();
  if (d.error) { setError(d.error); return; }
  layout = d;
  renderLegend();
  renderStage();
}
async function loadMedia() {
  const r = await fetch('/api/media');
  const d = await r.json();
  mediaListEl.innerHTML = '';
  (d.files || []).forEach(f => {
    const el = document.createElement('div');
    el.className = 'media-item';
    el.draggable = true;
    el.dataset.name = f.name;
    el.dataset.path = f.path;
    el.innerHTML =
      '<img src="/media/' + encodeURIComponent(f.name) + '" alt="">' +
      '<div class="name">' + escapeHtml(f.name) + '</div>' +
      '<button class="show-btn" onclick="showOnScreen(event, \'' +
      encodeURIComponent(f.path) + '\')">📺 显示到屏幕</button>' +
      '<div class="del" onclick="deleteMedia(event, \'' +
      encodeURIComponent(f.name) + '\')">×</div>';
    el.addEventListener('dragstart', e => {
      el.classList.add('dragging');
      e.dataTransfer.setData('media/path', f.path);
    });
    el.addEventListener('dragend', () => el.classList.remove('dragging'));
    mediaListEl.appendChild(el);
  });
}

// ---- render ----
function renderLegend() {
  const el = document.getElementById('legend');
  el.innerHTML = TYPES.map(t =>
    '<div><span class="swatch" style="background:' + COLORS[t] + '"></span>' +
    escapeHtml(t) + '</div>').join('');
}

function renderStage() {
  if (!layout) return;
  const scale = parseFloat(scaleEl.value);
  scaleValEl.textContent = scale.toFixed(1) + '×';
  stage.style.setProperty('--scale', scale);
  stage.style.width  = (layout.screen_w * scale) + 'px';
  stage.style.height = (layout.screen_h * scale) + 'px';
  stage.innerHTML = '';
  // 网格背景
  const g = document.createElement('div');
  g.className = 'grid-bg';
  stage.appendChild(g);
  // 标尺
  const rulerX = document.getElementById('rulerX');
  const rulerY = document.getElementById('rulerY');
  rulerX.innerHTML = ''; rulerY.innerHTML = '';
  for (let x = 0; x <= layout.screen_w; x += 40) {
    const s = document.createElement('span');
    s.style.left = (x * scale) + 'px';
    s.textContent = x;
    rulerX.appendChild(s);
  }
  for (let y = 0; y <= layout.screen_h; y += 40) {
    const s = document.createElement('span');
    s.style.top = (y * scale - 6) + 'px';
    s.textContent = y;
    rulerY.appendChild(s);
  }
  // widgets
  computeBadness();
  layout.widgets.forEach((w, i) => stage.appendChild(makeWidgetEl(w, i, scale)));

  updateInspector();
}

function computeBadness() {
  const sw = layout.screen_w, sh = layout.screen_h;
  layout.widgets.forEach(a => {
    a.out_of_bounds = !(a.x >= 0 && a.y >= 0 &&
      a.x + a.w <= sw && a.y + a.h <= sh);
  });
  layout.widgets.forEach((a, i) => {
    a.overlaps = [];
    layout.widgets.forEach((b, j) => {
      if (i === j) return;
      if (a.x < b.x + b.w && b.x < a.x + a.w &&
          a.y < b.y + b.h && b.y < a.y + a.h) a.overlaps.push(j);
    });
  });
}

function makeWidgetEl(w, i, scale) {
  const d = document.createElement('div');
  const bad = w.out_of_bounds || w.overlaps.length > 0;
  d.className = 'widget' + (bad ? ' bad' : '') +
    (i === selectedIdx ? ' selected' : '');
  d.style.left   = (w.x * scale) + 'px';
  d.style.top    = (w.y * scale) + 'px';
  d.style.width  = (w.w * scale) + 'px';
  d.style.height = (w.h * scale) + 'px';
  d.style.background = COLORS[w.type] || COLORS._unknown;
  d.dataset.idx = i;

  // image widget:显示缩略图
  if (w.type === 'image' && w.options && w.options.path) {
    const name = w.options.path.split('/').pop();
    d.innerHTML = '<img class="preview" src="/media/' +
      encodeURIComponent(name) + '">' +
      '<div class="type" style="position:relative;z-index:2">' +
      escapeHtml(w.type) + '</div>';
  } else {
    d.innerHTML =
      '<div class="type">' + escapeHtml(w.type) + '</div>' +
      '<div class="dim">' + w.w + '×' + w.h + '</div>' +
      '<div class="dim">' + w.x + ',' + w.y + '</div>';
  }
  // handles
  if (i === selectedIdx) {
    ['tl','tr','bl','br','tm','bm','lm','rm'].forEach(pos => {
      const h = document.createElement('div');
      h.className = 'handle ' + pos;
      h.dataset.handle = pos;
      d.appendChild(h);
    });
  }
  attachDrag(d, i);
  return d;
}

// ---- drag / resize ----
function attachDrag(el, idx) {
  el.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    const scale = parseFloat(scaleEl.value);
    const isHandle = e.target.classList.contains('handle');
    const handleType = isHandle ? e.target.dataset.handle : null;

    selectedIdx = idx;
    renderStage();

    const w = layout.widgets[idx];
    const startX = e.clientX, startY = e.clientY;
    const start = { x: w.x, y: w.y, w: w.w, h: w.h };
    e.preventDefault();

    function onMove(ev) {
      const dx = (ev.clientX - startX) / scale;
      const dy = (ev.clientY - startY) / scale;
      const snap = snapEl.checked ? 4 : 1;
      const q = v => Math.round(v / snap) * snap;
      let x = start.x, y = start.y, ww = start.w, hh = start.h;

      if (!handleType) {
        // 拖动整个 widget
        x = q(start.x + dx);
        y = q(start.y + dy);
      } else {
        if (handleType.includes('l')) {
          x = q(start.x + dx); ww = start.w + (start.x - x);
        }
        if (handleType.includes('r')) {
          ww = q(start.w + dx);
        }
        if (handleType.includes('t')) {
          y = q(start.y + dy); hh = start.h + (start.y - y);
        }
        if (handleType.includes('b')) {
          hh = q(start.h + dy);
        }
      }
      ww = Math.max(8, ww); hh = Math.max(8, hh);
      // 边界裁剪
      x = Math.max(0, Math.min(x, layout.screen_w - ww));
      y = Math.max(0, Math.min(y, layout.screen_h - hh));
      ww = Math.min(ww, layout.screen_w - x);
      hh = Math.min(hh, layout.screen_h - y);
      Object.assign(w, {x, y, w: ww, h: hh});
      markDirty();
      renderStage();
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

// ---- inspector ----
function updateInspector() {
  if (selectedIdx < 0 || !layout || !layout.widgets[selectedIdx]) {
    inspector.style.display = 'none';
    return;
  }
  const w = layout.widgets[selectedIdx];
  inspector.style.display = 'block';
  insType.value = w.type;
  insX.value = w.x; insY.value = w.y; insW.value = w.w; insH.value = w.h;
  if (w.type === 'image') {
    insPathRow.style.display = 'flex';
    insPath.value = (w.options && w.options.path) || '';
  } else {
    insPathRow.style.display = 'none';
  }
}
[insX, insY, insW, insH].forEach(el => el.addEventListener('change', () => {
  const w = layout.widgets[selectedIdx]; if (!w) return;
  w.x = +insX.value; w.y = +insY.value;
  w.w = Math.max(8, +insW.value); w.h = Math.max(8, +insH.value);
  markDirty(); renderStage();
}));
insType.addEventListener('change', () => {
  const w = layout.widgets[selectedIdx]; if (!w) return;
  w.type = insType.value;
  if (w.type !== 'image') w.options = {};
  markDirty(); renderStage();
});
insPath.addEventListener('change', () => {
  const w = layout.widgets[selectedIdx]; if (!w) return;
  w.options = w.options || {};
  w.options.path = insPath.value;
  markDirty(); renderStage();
});

// ---- toolbar ----
function addWidget() {
  const type = newType.value;
  const w = { type, x: 12, y: 12, w: 100, h: 60, options: {} };
  layout.widgets.push(w);
  selectedIdx = layout.widgets.length - 1;
  markDirty(); renderStage();
}
function deleteSelected() {
  if (selectedIdx < 0) return;
  layout.widgets.splice(selectedIdx, 1);
  selectedIdx = -1;
  markDirty(); renderStage();
}
function markDirty() {
  dirty = true;
  statusEl.textContent = '未保存';
  statusEl.className = 'status err';
}
async function save() {
  try {
    const r = await fetch('/api/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ widgets: layout.widgets }),
    });
    const d = await r.json();
    if (d.error) { setError(d.error); return; }
    dirty = false;
    statusEl.textContent = '已保存';
    statusEl.className = 'status ok';
    setError('');
  } catch (e) { setError(String(e)); }
}
async function apply() {
  if (dirty) { await save(); if (dirty) return; }
  statusEl.textContent = '部署中…';
  statusEl.className = 'status';
  try {
    const r = await fetch('/api/apply', {method: 'POST'});
    const d = await r.json();
    if (d.error) {
      setError(d.error + '\n\n' + JSON.stringify(d.steps || [], null, 2));
      statusEl.textContent = '部署失败';
      statusEl.className = 'status err';
      return;
    }
    statusEl.textContent = '已应用到屏幕';
    statusEl.className = 'status ok';
    setError('');
  } catch (e) {
    setError(String(e));
    statusEl.className = 'status err';
  }
}

// ---- upload ----
uploadHint.addEventListener('dragover', e => {
  e.preventDefault(); uploadHint.classList.add('drag');
});
uploadHint.addEventListener('dragleave', () => uploadHint.classList.remove('drag'));
uploadHint.addEventListener('drop', async e => {
  e.preventDefault();
  uploadHint.classList.remove('drag');
  for (const f of e.dataTransfer.files) await uploadOne(f);
  await loadMedia();
});
fileInput.addEventListener('change', async () => {
  for (const f of fileInput.files) await uploadOne(f);
  fileInput.value = '';
  await loadMedia();
});
async function uploadOne(file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch('/api/upload', {method: 'POST', body: fd});
  const d = await r.json();
  if (d.error) setError('upload ' + file.name + ': ' + d.error);
}
async function deleteMedia(ev, encodedName) {
  ev.stopPropagation();
  const name = decodeURIComponent(encodedName);
  if (!confirm('删除 ' + name + '?')) return;
  const r = await fetch('/api/delete-media', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name}),
  });
  const d = await r.json();
  if (d.error) setError(d.error);
  await loadMedia();
}

// 点素材的"📺 显示到屏幕":自动加/换 image widget + 保存 + 应用
async function showOnScreen(ev, encodedPath) {
  ev.stopPropagation();
  const btn = ev.target;
  const path = decodeURIComponent(encodedPath);
  btn.disabled = true; const oldText = btn.textContent;
  btn.textContent = '部署中…';
  try {
    // 若已有 image widget → 直接改 path;否则新建一个到右下默认位置
    let img = layout.widgets.find(w => w.type === 'image');
    if (img) {
      img.options = img.options || {};
      img.options.path = path;
    } else {
      // 默认位置:占用右下 WEATHER 那块 (324,188,144,128)
      layout.widgets.push({
        type: 'image', x: 324, y: 188, w: 144, h: 128,
        options: { path },
      });
    }
    renderStage();
    // 保存
    const rs = await fetch('/api/save', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ widgets: layout.widgets }),
    });
    const ds = await rs.json();
    if (ds.error) throw new Error(ds.error);
    dirty = false;
    // 应用到屏幕
    const ra = await fetch('/api/apply', {method: 'POST'});
    const da = await ra.json();
    if (da.error) throw new Error(da.error);
    statusEl.textContent = '已显示到屏幕 ✓';
    statusEl.className = 'status ok';
    setError('');
  } catch (e) {
    setError(e.message || String(e));
    statusEl.textContent = '失败';
    statusEl.className = 'status err';
  } finally {
    btn.disabled = false;
    btn.textContent = oldText;
  }
}

// 拖 media 到画布 → 生成 image widget
stage.addEventListener('dragover', e => {
  if (e.dataTransfer.types.includes('media/path')) e.preventDefault();
});
stage.addEventListener('drop', e => {
  const path = e.dataTransfer.getData('media/path');
  if (!path) return;
  e.preventDefault();
  const rect = stage.getBoundingClientRect();
  const scale = parseFloat(scaleEl.value);
  const snap = snapEl.checked ? 4 : 1;
  const q = v => Math.round(v / snap) * snap;
  const w = 120, h = 90;
  const x = Math.min(Math.max(0, q((e.clientX - rect.left) / scale - w/2)),
                     layout.screen_w - w);
  const y = Math.min(Math.max(0, q((e.clientY - rect.top) / scale - h/2)),
                     layout.screen_h - h);
  layout.widgets.push({ type: 'image', x, y, w, h, options: { path } });
  selectedIdx = layout.widgets.length - 1;
  markDirty(); renderStage();
});

// ---- misc ----
function setError(msg) {
  errorEl.innerHTML = msg ? '<div class="error">' + escapeHtml(msg) + '</div>' : '';
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  })[c]);
}
scaleEl.addEventListener('input', renderStage);
document.addEventListener('keydown', e => {
  if (selectedIdx < 0) return;
  const w = layout.widgets[selectedIdx]; if (!w) return;
  const step = e.shiftKey ? 10 : (snapEl.checked ? 4 : 1);
  if (e.key === 'ArrowLeft')  { w.x = Math.max(0, w.x - step); markDirty(); renderStage(); e.preventDefault(); }
  if (e.key === 'ArrowRight') { w.x = Math.min(layout.screen_w - w.w, w.x + step); markDirty(); renderStage(); e.preventDefault(); }
  if (e.key === 'ArrowUp')    { w.y = Math.max(0, w.y - step); markDirty(); renderStage(); e.preventDefault(); }
  if (e.key === 'ArrowDown')  { w.y = Math.min(layout.screen_h - w.h, w.y + step); markDirty(); renderStage(); e.preventDefault(); }
  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (e.target === document.body) { deleteSelected(); e.preventDefault(); }
  }
});
stage.addEventListener('mousedown', e => {
  if (e.target === stage || e.target.classList.contains('grid-bg')) {
    selectedIdx = -1; renderStage();
  }
});

// ---- boot ----
loadLayout();
loadMedia();
setInterval(loadMedia, 5000);   // 侧栏 5s 刷新一次(捕捉外部添加的图片)
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path,
                    default=Path(__file__).parent.parent / "config.toml")
    ap.add_argument("--media", type=Path,
                    default=Path(__file__).parent.parent / "media")
    ap.add_argument("--deployed-config", type=Path,
                    default=Path("/opt/screan/config.toml"))
    ap.add_argument("--deployed-media", type=Path,
                    default=Path("/opt/screan/media"))
    ap.add_argument("--install-script", type=Path,
                    default=Path(__file__).parent.parent
                    / "scripts" / "install.sh")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    if not args.config.is_file():
        print(f"config not found: {args.config}", file=sys.stderr)
        sys.exit(1)
    args.media.mkdir(parents=True, exist_ok=True)

    Handler.config_path = args.config.resolve()
    Handler.media_dir = args.media.resolve()
    Handler.deployed_config = args.deployed_config
    Handler.deployed_media = args.deployed_media
    Handler.install_script = args.install_script.resolve()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"➜  监听 http://{args.host}:{args.port}/")
    print(f"➜  预览 config:  {Handler.config_path}")
    print(f"➜  media 目录:  {Handler.media_dir}")
    print(f"➜  Ctrl-C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye.")


if __name__ == "__main__":
    main()
