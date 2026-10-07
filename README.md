# Handdrawn Paint Animation · 手绘涂绘动效

> 把一张静态插画，变成一段"正在被一笔一笔画出来"的动态镜头。
> Turn a single still illustration into a shot that looks like it is being **painted, stroke by stroke**.

[中文](#-中文) · [English](#-english)

---

## 🇨🇳 中文

### 这是什么
输入 **一张插画 + 一份 JSON 配置**，输出 **一个 mp4 镜头**。
核心卖点是**上色过程**：不是滤镜、不是整体淡入，而是**一支画笔沿路径游走，走过的地方才上色**——一笔一笔、带停顿，并有可见的笔尖与湿边。

### 一条时间轴
1. **打底**：纸张纤维纹理 + 静态颗粒 + 暗角
2. **线条逐笔画出**（draw-on）：沿扫掠方向把线稿一段段"画"出来
3. **画笔游走式水彩上色**（核心）：两遍叠色（斜向铺淡底 → 换向加深）+ 笔触分段停顿 + 笔尖湿痕 + 湿边加深
4. **收尾**：画面缓慢呼吸/摆动（内部真运动，非镜头推拉）+ 浮尘/雨粒子 + 手写体字幕 + 结尾洗白转场

### 仓库结构
```
.
├── README.md                            # 本文件（中英双语）
├── docs/
│   └── architecture.md                  # 原理与实现细节（双语）
├── skills/
│   └── handdrawn-paint-animation/       # ① 技能：SOP + 引擎 + 参考 + 示例
│       ├── SKILL.md                     #    触发词 / 流程 / 硬约束
│       ├── scripts/                     #    render.py · qc.py · 渲染引擎
│       ├── references/                  #    params.md（参数）· pitfalls.md（踩坑）
│       ├── fonts/                       #    打包手写字体
│       └── examples/                    #    示例底图 + 最小配置
└── mcp/
    └── handdrawn-paint-mcp/             # ② MCP 工具（stdio，零第三方依赖）
        ├── server.py                    #    三个工具：render / preview / qc
        └── smoke_test.py                #    不发依赖、直接对协议自测
```

### 快速开始（命令行）
```bash
# 依赖：Python 3.10+ ，pip 装 numpy / opencv / Pillow；系统需 ffmpeg
pip install -r skills/handdrawn-paint-animation/requirements.txt
cd skills/handdrawn-paint-animation/scripts

python3 render.py --config ../examples/scene_example.json --preview 1.2,3,5   # 先看几帧（快）
python3 render.py --config ../examples/scene_example.json                     # 渲染整镜
python3 qc.py ../examples/shot_example.mp4 --frames 2,5,8                     # 自检
```
最小配置只要两个字段：`{"img": "你的插画.png", "dur": 9.0}`。全部参数见 `references/params.md`。

### 作为 MCP 工具使用
`mcp/handdrawn-paint-mcp/server.py` 是**零第三方依赖**的 stdio MCP server，暴露：

| 工具 | 作用 |
|---|---|
| `render_handdrawn_shot` | `config`(dict) → 渲染 mp4 |
| `preview_handdrawn_frames` | 只出几个时间点的 PNG（快，用来先看效果） |
| `qc_handdrawn_shot` | 探针 / 解码校验 / 抽帧 / 上色推进指标 |

客户端配置示例：
```json
{
  "mcpServers": {
    "handdrawn-paint": {
      "command": "python3",
      "args": ["/绝对路径/handdrawn-paint-animation/mcp/handdrawn-paint-mcp/server.py"]
    }
  }
}
```
自测（不需要任何 MCP 客户端）：
```bash
python3 mcp/handdrawn-paint-mcp/smoke_test.py
```

### 作为 Skill 使用
把 `skills/handdrawn-paint-animation/` 整个目录放入你的技能目录并注册。支持该机制的 Agent 会读取 `SKILL.md` 的 SOP 自动调用。

### 环境要求
Python 3.10+；`numpy`、`opencv-python-headless`、`Pillow`；系统 `ffmpeg / ffprobe ≥ 5`。

### 延伸阅读
- 原理与实现 → `docs/architecture.md`
- 参数手册 → `skills/handdrawn-paint-animation/references/params.md`
- 踩坑清单（改引擎前必读）→ `skills/handdrawn-paint-animation/references/pitfalls.md`

---

## 🇬🇧 English

### What it is
Feed it **one illustration + one JSON config**, get back **one animated mp4 shot**.
The selling point is the *painting process*: this is not a filter, not a global fade-in — a **brush travels along a path and only the area it has passed gets colored**, stroke by stroke, with pauses, a visible brush tip and wet edges.

### The timeline of one shot
1. **Ground**: paper-fiber texture + a single static grain plate + vignette
2. **Draw-on**: pencil/ink lines are revealed progressively along a sweep direction
3. **Brush-travel watercolor fill** (the core): two passes (diagonal light wash → cross-direction deepening) + stroke segmentation with pauses + a wet brush tip + darkened wet rim
4. **Finish**: a slow "breathing" warp (real inner motion, not a camera move) + dust/rain particles + handwritten captions + a wash-out transition

### Repository layout
```
.
├── README.md                            # this file (bilingual)
├── docs/architecture.md                 # how it works, in detail (bilingual)
├── skills/handdrawn-paint-animation/    # ① Skill: SOP + engine + refs + examples
└── mcp/handdrawn-paint-mcp/             # ② MCP server (stdio, zero third-party deps)
```

### Quick start (CLI)
```bash
pip install -r skills/handdrawn-paint-animation/requirements.txt   # plus system ffmpeg
cd skills/handdrawn-paint-animation/scripts

python3 render.py --config ../examples/scene_example.json --preview 1.2,3,5   # preview frames (fast)
python3 render.py --config ../examples/scene_example.json                     # render the full shot
python3 qc.py ../examples/shot_example.mp4 --frames 2,5,8                     # self-check
```
The minimal config needs only `{"img": "your_art.png", "dur": 9.0}`. Full parameter list: `references/params.md`.

### Use it as an MCP tool
`mcp/handdrawn-paint-mcp/server.py` is a **dependency-free** stdio MCP server exposing
`render_handdrawn_shot` / `preview_handdrawn_frames` / `qc_handdrawn_shot`.

```json
{
  "mcpServers": {
    "handdrawn-paint": {
      "command": "python3",
      "args": ["/abs/path/handdrawn-paint-animation/mcp/handdrawn-paint-mcp/server.py"]
    }
  }
}
```
Self-test (no MCP client needed):
```bash
python3 mcp/handdrawn-paint-mcp/smoke_test.py
```

### Use it as a Skill
Drop `skills/handdrawn-paint-animation/` into your skills directory and register it; an agent that supports this mechanism will follow `SKILL.md`.

### Requirements
Python 3.10+, `numpy` / `opencv-python-headless` / `Pillow`, and system `ffmpeg / ffprobe ≥ 5`.

### Read more
- Architecture & implementation → `docs/architecture.md`
- Parameter manual → `skills/handdrawn-paint-animation/references/params.md`
- Pitfalls (read before touching the engine) → `skills/handdrawn-paint-animation/references/pitfalls.md`

---

## License
MIT © 2026 linuxz
