#!/usr/bin/env python3
"""render.py —— 单镜头渲染的唯一入口。
用法:
  python render.py --config scene.json                 # 渲染整镜 -> mp4
  python render.py --config scene.json --preview 1.2,2.4,4.0,6.0
                                                        # 只出这几帧 PNG（快，不编码，用来先看效果）
可选覆盖: --out --seed --dur --crf --preset
"""
import argparse, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hd_config
import paint_engine as pe
from PIL import Image


def main():
    ap = argparse.ArgumentParser(description='手绘涂绘动效 · 单镜头渲染（config.json -> mp4）')
    ap.add_argument('--config', required=True, help='JSON 配置路径')
    ap.add_argument('--out', default=None, help='覆盖配置里的 out')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--dur', type=float, default=None)
    ap.add_argument('--crf', type=int, default=None)
    ap.add_argument('--preset', default=None)
    ap.add_argument('--preview', default=None, help='逗号分隔秒数，只渲染这些帧为 PNG')
    ap.add_argument('--preview-dir', default=None)
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding='utf-8'))
    base = os.path.dirname(os.path.abspath(a.config))
    if a.seed is not None:
        cfg['seed'] = a.seed
    if a.dur is not None:
        cfg['dur'] = a.dur
    sc = hd_config.build_scene(cfg, base)

    if not os.path.exists(sc['img']):
        sys.exit(f'[err] 找不到底图: {sc["img"]}')

    if a.preview:
        pdir = a.preview_dir or os.path.join(base, 'preview')
        pe.prepare(sc)
        os.makedirs(pdir, exist_ok=True)
        for s in a.preview.split(','):
            t = int(round(float(s) * sc['fps']))
            Image.fromarray(pe.compose(sc, t)).save(os.path.join(pdir, f'preview_{float(s):.2f}.png'))
        print('preview ->', pdir)
        return

    out = a.out or cfg.get('out') or os.path.join('out', 'shot.mp4')
    out = out if os.path.isabs(out) else os.path.normpath(os.path.join(base, out))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    crf = a.crf if a.crf is not None else int(cfg.get('crf', 18))
    preset = a.preset or cfg.get('preset', 'veryfast')

    t0 = time.time()
    n = pe.render_scene(sc, out, crf=crf, preset=preset)
    dt = time.time() - t0
    W, H = sc['size']
    print(f'OK  {out}')
    print(f'    frames={n}  dur={sc["dur"]:.2f}s  {W}x{H}@{sc["fps"]}  crf={crf} {preset}  用时 {dt:.1f}s')


if __name__ == '__main__':
    main()
