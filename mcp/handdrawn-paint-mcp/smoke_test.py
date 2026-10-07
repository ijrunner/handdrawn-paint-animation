#!/usr/bin/env python3
"""smoke_test.py —— 不起任何依赖，直接对本 MCP server 说一遍协议，验证它可用。
运行: python3 smoke_test.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
EXAMPLE_IMG = os.path.join(REPO, "skills", "handdrawn-paint-animation", "examples", "example_ink.png")

p = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py")],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)


def call(obj):
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())


print("=== initialize ===")
print(json.dumps(call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2024-11-05"}}), ensure_ascii=False)[:300])

print("=== tools/list ===")
r = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
for t in r["result"]["tools"]:
    print(" -", t["name"])

print("=== tools/call: preview_handdrawn_frames ===")
r = call({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "preview_handdrawn_frames",
                     "arguments": {"config": {"img": EXAMPLE_IMG, "dur": 6.0, "seed": 213},
                                   "times": "1.2,3,5"}}})
print(r["result"]["content"][0]["text"])

p.stdin.close()
p.wait(timeout=10)
print("=== server exited, code", p.returncode, "===")
