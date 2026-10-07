# handdrawn-paint-mcp

把「手绘涂绘动效」引擎封装成 **MCP 工具**（stdio 传输，**零第三方依赖**）。
A **dependency-free** stdio MCP server that exposes the *handdrawn paint* engine as MCP tools.

## 工具 / Tools

| 工具 Tool | 输入 Input | 输出 Output |
|---|---|---|
| `render_handdrawn_shot` | `config`(dict, 最小 `{img, dur}`)、`base_dir?`、`out?`、`crf?`、`preset?` | 渲染一个 mp4 镜头 / renders one mp4 shot |
| `preview_handdrawn_frames` | `config`、`times?`(默认 `1.5,3,5,7`)、`out_dir?` | 几个时间点的 PNG（快，先看效果）/ a few PNG frames |
| `qc_handdrawn_shot` | `video?`、`frames?` 或 `config_path`(打指标) | 探针 / 解码校验 / 抽帧 / 上色推进指标 |

## 运行 / Run
```bash
python3 server.py          # 作为 stdio MCP server 启动 / start as a stdio MCP server
python3 smoke_test.py      # 无需 MCP 客户端，直接对协议自测 / protocol self-test
```
引擎位置由 server 自动解析；若不在仓库里运行，请设置环境变量：
```
HANDDRAWN_ENGINE_DIR=/path/to/handdrawn-paint-animation/skills/handdrawn-paint-animation/scripts
```

## 客户端配置示例 / Client config
```json
{
  "mcpServers": {
    "handdrawn-paint": {
      "command": "python3",
      "args": ["/abs/path/mcp/handdrawn-paint-mcp/server.py"],
      "env": { "HANDDRAWN_ENGINE_DIR": "/abs/path/skills/handdrawn-paint-animation/scripts" }
    }
  }
}
```

## 依赖 / Requirements
仅需引擎自身的依赖：`numpy`、`opencv-python-headless`、`Pillow`，以及系统 `ffmpeg`。
Only the engine's own deps: `numpy`, `opencv-python-headless`, `Pillow`, plus system `ffmpeg`.

一个调用示例 / one call example:
```json
{"name": "render_handdrawn_shot",
 "arguments": {"base_dir": "/tmp/myproj",
               "config": {"img": "art.png", "dur": 9.0, "seed": 213,
                          "texts": [{"str": "一笔一笔画出来", "t0": 2.4, "hold": 3.0}]}}}
```
