#!/usr/bin/env python3
"""
handdrawn-paint MCP server  (stdio transport, zero third-party deps)

把"手绘涂绘动效"引擎暴露成 MCP 工具，任何支持 MCP 的 Agent/客户端都能直接调用。

Exposes the handdrawn-paint engine as MCP tools over stdio:
  - render_handdrawn_shot     config(dict) + out      -> mp4
  - preview_handdrawn_frames  config(dict) + times    -> a few PNG frames (fast, no encode)
  - qc_handdrawn_shot         video | config          -> QC report (probe / decode / stroke metrics)

协议 / Protocol: MCP stdio —— newline-delimited JSON-RPC 2.0.

引擎位置 / Engine lookup: 环境变量 HANDDRAWN_ENGINE_DIR，或从仓库根目录运行（自动找到
skills/handdrawn-paint-animation/scripts）。
"""
import json
import os
import subprocess
import sys
import tempfile
import traceback

SERVER_NAME = "handdrawn-paint"
SERVER_VERSION = "0.3.0"
PROTOCOL_FALLBACK = "2024-11-05"


# ---------------------------------------------------------------- engine lookup
def find_engine():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))          # repo root
    cands = [os.environ.get("HANDDRAWN_ENGINE_DIR"),
             os.path.join(root, "skills", "handdrawn-paint-animation", "scripts"),
             os.path.join(here, "engine")]
    for c in cands:
        if c and os.path.exists(os.path.join(c, "paint_engine.py")):
            return os.path.abspath(c)
    return None


def engine():
    d = find_engine()
    if not d:
        raise RuntimeError(
            "找不到引擎 (paint_engine.py)。请设置环境变量 HANDDRAWN_ENGINE_DIR 指向 "
            "skills/handdrawn-paint-animation/scripts，或从仓库根目录启动本 server。")
    if d not in sys.path:
        sys.path.insert(0, d)
    import hd_config
    import paint_engine
    return hd_config, paint_engine


# ---------------------------------------------------------------- tools
def t_render(a):
    hd_config, pe = engine()
    cfg = a["config"]
    base = a.get("base_dir") or tempfile.mkdtemp(prefix="hdpaint_")
    sc = hd_config.build_scene(cfg, base)
    if not os.path.exists(sc["img"]):
        raise RuntimeError(f"底图不存在 / image not found: {sc['img']}")
    out = a.get("out") or os.path.join(base, "shot.mp4")
    out = out if os.path.isabs(out) else os.path.join(base, out)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    n = pe.render_scene(sc, out, crf=int(a.get("crf", cfg.get("crf", 18))),
                        preset=a.get("preset", cfg.get("preset", "veryfast")))
    W, H = sc["size"]
    return (f"OK {out}\n"
            f"frames={n}  dur={sc['dur']:.2f}s  {W}x{H}@{sc['fps']}")


def t_preview(a):
    hd_config, pe = engine()
    from PIL import Image
    cfg = a["config"]
    base = a.get("base_dir") or tempfile.mkdtemp(prefix="hdpaint_")
    sc = hd_config.build_scene(cfg, base)
    if not os.path.exists(sc["img"]):
        raise RuntimeError(f"底图不存在 / image not found: {sc['img']}")
    pe.prepare(sc)
    pdir = a.get("out_dir") or os.path.join(base, "preview")
    os.makedirs(pdir, exist_ok=True)
    times = [s for s in str(a.get("times", "1.5,3,5,7")).split(",") if s.strip()]
    paths = []
    for s in times:
        t = int(round(float(s) * sc["fps"]))
        p = os.path.join(pdir, f"preview_{float(s):.2f}.png")
        Image.fromarray(pe.compose(sc, t)).save(p)
        paths.append(p)
    return "preview frames:\n" + "\n".join(paths)


def t_qc(a):
    d = find_engine()
    if not d:
        raise RuntimeError("找不到引擎目录 / engine dir not found (set HANDDRAWN_ENGINE_DIR)")
    args = [sys.executable, os.path.join(d, "qc.py")]
    if a.get("config_path"):
        args += ["--config", a["config_path"], "--metrics"]
    else:
        args += [a["video"], "--frames", a.get("frames", "2,5,8")]
    r = subprocess.run(args, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


TOOLS = [
    {
        "name": "render_handdrawn_shot",
        "description": ("把一张静态插画渲染成'正在被一笔一笔画出来'的手绘涂绘动画镜头（线条逐笔画出 → "
                        "画笔游走式水彩上色 → 呼吸微动 → 手写字幕 → 洗白转场），输出 mp4。"
                        "config 为参数字典，最小只需 {img, dur}。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "config": {"type": "object", "description": "参数字典；最小 {img, dur}。相对路径以 base_dir 为基准。"},
                "base_dir": {"type": "string", "description": "相对路径基准目录；省略则用临时目录"},
                "out": {"type": "string", "description": "输出 mp4 路径；省略则写在 base_dir/shot.mp4"},
                "crf": {"type": "integer", "description": "画质，默认 18"},
                "preset": {"type": "string", "description": "x264 速度档，默认 veryfast"}
            },
            "required": ["config"]
        }
    },
    {
        "name": "preview_handdrawn_frames",
        "description": "只渲染几个时间点的帧为 PNG（快，不编码），用于先看效果再决定是否整镜渲染。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "config": {"type": "object"},
                "times": {"type": "string", "description": "逗号分隔的秒数，默认 '1.5,3,5,7'"},
                "base_dir": {"type": "string"},
                "out_dir": {"type": "string"}
            },
            "required": ["config"]
        }
    },
    {
        "name": "qc_handdrawn_shot",
        "description": "成片自检：探针(分辨率/帧率/时长) + 解码校验 + 抽帧；或给 config 打印'上色是否一笔一笔'的客观指标。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "video": {"type": "string", "description": "要自检的 mp4 路径"},
                "frames": {"type": "string", "description": "抽帧时间点(秒)，默认 '2,5,8'"},
                "config_path": {"type": "string", "description": "给 config 路径 + 该字段则打印上色推进指标"}
            }
        }
    }
]

HANDLERS = {
    "render_handdrawn_shot": t_render,
    "preview_handdrawn_frames": t_preview,
    "qc_handdrawn_shot": t_qc,
}


# ---------------------------------------------------------------- JSON-RPC loop
def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req):
    mid = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_FALLBACK),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}}
        try:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": fn(args)}], "isError": False}}
        except Exception as e:                                   # noqa: BLE001
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}\n{traceback.format_exc()}"}],
                "isError": True}}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"resources": []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"prompts": []}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            send(resp)


if __name__ == "__main__":
    main()
