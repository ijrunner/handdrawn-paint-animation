#!/usr/bin/env python3
"""qc.py —— 成片自检（不需要"看"视频就能判断对不对）。
用法:
  python qc.py shot.mp4                      # 探针 + 解码校验 + 抽帧
  python qc.py shot.mp4 --frames 2,5,8 --outdir qc
  python qc.py --config scene.json --metrics # 打印"上色是否一笔一笔"的客观指标
"""
import argparse, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def probe(v):
    o = subprocess.run(['ffprobe', '-v', 'error',
                        '-show_entries', 'format=duration,size',
                        '-show_entries', 'stream=codec_type,codec_name,width,height,r_frame_rate',
                        '-of', 'default=nw=1', v], capture_output=True, text=True).stdout
    print(o.strip())


def decode_check(v):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', v, '-f', 'null', '-'], capture_output=True, text=True)
    ok = (r.returncode == 0 and not r.stderr.strip())
    print('decode:', 'OK（无错误）' if ok else 'FAIL\n' + r.stderr[:800])


def dump_frames(v, times, outdir):
    os.makedirs(outdir, exist_ok=True)
    for s in times:
        p = os.path.join(outdir, f'qc_{float(s):.2f}.png')
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', str(s), '-i', v, '-frames:v', '1', p])
        print('frame ->', p)


def metrics(cfgfile):
    import numpy as np, cv2
    import hd_config, paint_engine as pe
    cfg = json.load(open(cfgfile, encoding='utf-8'))
    base = os.path.dirname(os.path.abspath(cfgfile))
    sc = hd_config.build_scene(cfg, base)
    pe.prepare(sc)
    W, H = sc['size']; cd = sc['col_dur']; col0 = sc['col0']; fps = sc['fps']
    f1, f2 = sc['col_field'], sc['col_field2']
    step = max(1, int(fps * 0.12))
    prev = None; rows = []
    for t in range(int(col0 * fps), int((col0 + cd * 1.05) * fps), step):
        ts = t / fps
        raw1 = np.clip((ts - col0) / (cd * 0.72), 0, 1)
        raw2 = np.clip((ts - (col0 + cd * 0.28)) / (cd * 0.72), 0, 1)
        p1 = pe.steps(raw1, sc.get('strokes1', 22)); p2 = pe.steps(raw2, sc.get('strokes2', 10))
        cm = (np.clip((f1 <= p1) * 0.62 + (f2 <= p2) * 0.44, 0, 1) > 0.01)
        new = cm if prev is None else (cm & ~prev)
        n, lab = cv2.connectedComponents(new.astype(np.uint8), 8)
        areas = np.bincount(lab.ravel())[1:] if n > 1 else np.array([])
        big = int((areas > 0.003 * W * H).sum()) if len(areas) else 0
        rows.append((ts, cm.mean() * 100, new.mean() * 100, big))
        prev = cm
    print('  t     cov%   new%   新增大块数')
    for ts, c, nw, b in rows:
        print(f'{ts:6.1f}  {c:5.1f}  {nw:5.1f}   {b:3d}')
    news = [r[2] for r in rows[1:]]; bigs = [r[3] for r in rows[1:]]
    if news:
        import numpy as np
        holds = sum(1 for x in news if x < 0.3)
        print(f'\n判读: 平均新增 {np.mean(news):.1f}%/采样 · 新增大块中位数 {int(np.median(bigs))} · 停顿采样 {holds}/{len(news)}')
    print('笔触式=新增集中在少数大块(1~8)且质心推进、偶有停顿；满屏几十块散点=漫开(需加大 strokes 段数/放慢 col_frac)。')


def main():
    ap = argparse.ArgumentParser(description='手绘涂绘动效 · 成片自检')
    ap.add_argument('video', nargs='?', default=None)
    ap.add_argument('--config', default=None)
    ap.add_argument('--metrics', action='store_true', help='配合 --config：打印上色推进指标')
    ap.add_argument('--frames', default='2,5,8', help='抽帧时间点(秒)，逗号分隔')
    ap.add_argument('--outdir', default='qc')
    a = ap.parse_args()
    if a.config and a.metrics:
        metrics(a.config)
    elif a.video:
        print('=== 探针 ==='); probe(a.video)
        print('=== 解码 ==='); decode_check(a.video)
        print('=== 抽帧 ==='); dump_frames(a.video, [float(x) for x in a.frames.split(',')], a.outdir)
    else:
        sys.exit('用法: python qc.py shot.mp4 [--frames 2,5,8]  |  python qc.py --config scene.json --metrics')


if __name__ == '__main__':
    main()
