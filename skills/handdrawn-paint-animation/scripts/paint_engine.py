"""
paint_engine.py —— 让手绘插画"真的动起来" v2
每镜头时间轴：纸张 → 线条逐笔画出(draw-on) → 【画笔游走式上色：两遍，先淡底后加深】 → 呼吸/摆动/粒子 → 洗白转场
v2 改动：颜色揭示由"种子点扩散"改为"画笔沿路径游走"(brush_field)：笔尖扫过才上色，湿边加深，两遍叠色。
"""
import numpy as np, cv2, os, subprocess
from PIL import Image
import handdrawn as hd

def _rng(seed): return np.random.default_rng(int(seed) & 0x7fffffff)
def ease(x):
    x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)
def steps(p, n, draw=0.55):
    """把连续进度切成 n 段：每段先快速落笔(draw)再停顿——形成"一笔一笔"的节奏。"""
    p = np.clip(p, 0, 1); x = p * n; i = np.floor(x); u = x - i
    return np.clip((i + ease(np.clip(u / draw, 0, 1))) / n, 0, 1)
def norm(f): return (f - f.min()) / (f.max() - f.min() + 1e-8)
def warp2(a, dx, dy, gx, gy):
    return cv2.remap(a, gx + dx, gy + dy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
def warp_chan(a, dx, dy, gx, gy):
    a = a.astype(np.float32)
    if a.ndim == 2: a = a[..., None]
    out = cv2.remap(a, gx + dx, gy + dy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out[..., 0] if out.ndim == 3 else out
def fit_cover(im, W, H):
    sw, sh = im.size; s = max(W / sw, H / sh)
    nw, nh = int(sw * s + 0.5), int(sh * s + 0.5)
    im = im.resize((nw, nh), Image.LANCZOS)
    return im.crop(((nw - W) // 2, (nh - H) // 2, (nw - W) // 2 + W, (nh - H) // 2 + H))

# ---------- 线稿 / 揭示场 ----------
def line_intensity(gray, sigma=3.0, gain=3.2):
    return np.clip((cv2.GaussianBlur(gray, (0, 0), sigma) - gray) * gain, 0, 1)

def sweep_field(W, H, seed, angle=38.0, noise=0.13):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    a = np.deg2rad(angle)
    p = norm(np.cos(a) * xx + np.sin(a) * yy)
    n = norm(hd.fbm(W, H, seed, octaves=5, base=6))
    return norm(np.clip(p + (n - 0.5) * 2 * noise, 0, 1))

def brush_path(W, H, seed, spacing, vertical=False, jitter=0.035, rot=16.0, extend=0.22):
    """一笔游走的路径：来回扫（serpentine）+ 手抖 + 整体旋转，使其像斜向的笔刷而不是"压路机"。"""
    rng = _rng(seed)
    A, B = (W, H) if vertical else (H, W)
    lo_p, hi_p = -extend * A, A * (1 + extend)
    lo_c, hi_c = -extend * B, B * (1 + extend)
    pts = []; pos = lo_p; k = 0
    while pos < hi_p:
        c0, c1 = (lo_c, hi_c) if k % 2 == 0 else (hi_c, lo_c)
        m = max(8, int(abs(c1 - c0) / 40))
        for tt in np.linspace(0, 1, m):
            c = c0 + (c1 - c0) * tt
            wob = jitter * B * np.sin(tt * np.pi * 2.3 + k * 1.7)
            p = pos + wob
            pts.append((c, p) if not vertical else (p, c))
        pos += spacing * (1 + rng.normal(0, 0.10)); k += 1
    P = np.array(pts, np.float32)
    if rot:
        th = np.deg2rad(rot); co, si = np.cos(th), np.sin(th); cx, cy = W / 2, H / 2
        x = P[:, 0] - cx; y = P[:, 1] - cy
        P = np.stack([cx + co * x - si * y, cy + si * x + co * y], 1).astype(np.float32)
    return P

def streaks(W, H, seed, horizontal, amp=0.28):
    """顺笔方向的毛糙条纹：横向笔则条纹沿 x 拉长（纵向高频），反之亦然。"""
    n = norm(hd.fbm(W, H, seed, octaves=4, base=7))
    if horizontal: s = cv2.GaussianBlur(n, (0, 0), sigmaX=17.0, sigmaY=0.9)
    else:          s = cv2.GaussianBlur(n, (0, 0), sigmaX=0.9, sigmaY=17.0)
    return (norm(s) - 0.5) * 2 * amp

def field_from_path(W, H, P, R, seed=1, noise=0.13, step=2, horizontal=True):
    d = np.sqrt(((P[1:] - P[:-1]) ** 2).sum(1)); s = np.concatenate([[0], np.cumsum(d)])
    S = np.full((H, W), 1e9, np.float32)
    for k in range(0, len(P), step):
        x = int(P[k, 0]); y = int(P[k, 1]); val = max(0.0, float(s[k]) - R)
        y0 = max(0, y - R); y1 = min(H, y + R + 1); x0 = max(0, x - R); x1 = min(W, x + R + 1)
        if y1 <= y0 or x1 <= x0: continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        m = ((xx - x) ** 2 + (yy - y) ** 2) <= R * R
        np.minimum(S[y0:y1, x0:x1], val, out=S[y0:y1, x0:x1], where=m)
    S[S > 1e8] = (S[S <= 1e8].max() if (S <= 1e8).any() else 0.0)
    f = S / (S.max() + 1e-8)
    n = norm(hd.fbm(W, H, seed, octaves=5, base=5))
    st = streaks(W, H, seed + 991, horizontal, 0.28)
    return norm(np.clip(f + (n - 0.5) * 2 * noise + st, 0, 1))

def living_field(W, H, t, fps, amp=5.0):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    ph = t / (fps * 5.0) * 2 * np.pi
    return amp * np.sin(2 * np.pi * yy / (H * 0.85) + ph), amp * 0.55 * np.sin(2 * np.pi * xx / (W * 1.05) - ph * 0.8)

def prepare(cfg):
    W, H = cfg['size']; fps = cfg.get('fps', 24); seed = cfg.get('seed', 1)
    cfg['fps'] = fps; cfg['seed'] = seed
    im = Image.open(cfg['img']).convert('RGB')
    if cfg.get('fit', True): im = fit_cover(im, W, H)
    arr = np.asarray(im, np.float32) / 255.0
    if cfg.get('soft', 0.4) > 0: arr = cv2.GaussianBlur(arr, (0, 0), cfg['soft'])
    cfg['color'] = arr
    gray = cv2.cvtColor((np.clip(arr, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    cfg['line_int'] = line_intensity(gray, cfg.get('line_sigma', 2.6), cfg.get('line_gain', 3.4))
    eq = lambda f: (np.argsort(np.argsort(f.ravel())).reshape(f.shape) / (f.size - 1)).astype(np.float32)
    cfg['ink_field'] = eq(sweep_field(W, H, seed + 5, cfg.get('ink_angle', 40), cfg.get('ink_noise', 0.12)))
    # 画笔两遍
    sp1 = cfg.get('brush1') or int(H / 8)
    sp2 = cfg.get('brush2') or int(W / 6)
    P1 = brush_path(W, H, seed + 21, sp1, vertical=False, rot=16.0)
    P2 = brush_path(W, H, seed + 47, sp2, vertical=True, rot=-14.0)
    cfg['col_field'] = eq(field_from_path(W, H, P1, int(sp1 * 0.70), seed + 22, cfg.get('col_noise', 0.11), horizontal=True))
    cfg['col_field2'] = eq(field_from_path(W, H, P2, int(sp2 * 0.74), seed + 48, cfg.get('col_noise', 0.13), horizontal=False))
    # 笔尖轨迹
    def cum(P): return np.concatenate([[0], np.cumsum(np.sqrt(((P[1:] - P[:-1]) ** 2).sum(1)))]).astype(np.float32)
    cfg['_P1'], cfg['_s1'] = P1, cum(P1)
    cfg['_P2'], cfg['_s2'] = P2, cum(P2)
    cfg['tip_R1'] = int(sp1 * 0.85); cfg['tip_R2'] = int(sp2 * 0.55)
    cfg['wipe_field'] = eq(sweep_field(W, H, seed + 33, -25, 0.10))
    cfg['_paper'] = hd.paper_texture(W, H, seed + 3, base=cfg.get('paper_base', (240, 235, 224)))
    ps = cfg.get('paper_strength', 0.24)
    cfg['_papermul'] = np.clip(cfg['_paper'] * 1.12, 0, 1) * (1 - ps) + ps
    cfg['_vig'] = hd.vignette_mask(W, H, cfg.get('vig', 0.22))
    cfg['_grain'] = hd.grain_plate(W, H, seed + 77, cfg.get('grain', 0.018))
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    cfg['_gx'], cfg['_gy'] = gx, gy
    cfg.setdefault('ink0', 0.0); cfg.setdefault('ink_dur', 1.5)
    cfg.setdefault('col0', 0.85); cfg.setdefault('col_dur', 1.9)
    cfg.setdefault('wipe0', cfg['dur'] - 0.7); cfg.setdefault('wipe_dur', 0.7)
    return cfg

def path_point(P, s, f):
    f = float(np.clip(f, 0, 1)); target = f * s[-1]
    k = int(np.searchsorted(s, target)); k = min(max(k, 1), len(P) - 1)
    t = (target - s[k - 1]) / (s[k] - s[k - 1] + 1e-6)
    return P[k - 1] * (1 - t) + P[k] * t

def draw_tip(frame, x, y, R, dark):
    """在笔尖处压一点湿痕，让眼睛能跟着笔走。"""
    H, W = frame.shape[:2]
    y0 = max(0, int(y - R)); y1 = min(H, int(y + R) + 1); x0 = max(0, int(x - R)); x1 = min(W, int(x + R) + 1)
    if y1 <= y0 or x1 <= x0: return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    g = np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (R * R + 1e-6)) * 2.2).astype(np.float32)
    frame[y0:y1, x0:x1] *= (1.0 - dark * g[..., None])

def render_frame(sc, t):
    W, H = sc['size']; fps = sc['fps']; ts = t / fps
    gx, gy = sc['_gx'], sc['_gy']
    p_ink = ease((ts - sc['ink0']) / max(sc['ink_dur'], 1e-6))
    cd = max(sc['col_dur'], 1e-6)
    raw1 = np.clip((ts - sc['col0']) / (cd * 0.72), 0, 1)
    raw2 = np.clip((ts - (sc['col0'] + cd * 0.28)) / (cd * 0.72), 0, 1)
    p1 = steps(raw1, sc.get('strokes1', 22)); p2 = steps(raw2, sc.get('strokes2', 10))
    dx, dy = living_field(W, H, t, fps, sc.get('live_amp', 5.0))
    # 画笔上色：第一遍淡底 + 第二遍加深（笔尖游走）
    r1 = sc['col_field'] <= p1
    r2 = sc['col_field2'] <= p2
    cm = np.clip(r1 * 0.62 + r2 * 0.44, 0, 1).astype(np.float32)
    rim = (np.clip(1.0 - np.abs(sc['col_field'] - p1) * 9.0, 0, 1) * r1).astype(np.float32)
    color = warp2(sc['color'], dx, dy, gx, gy)
    cmw = warp_chan(cm, dx, dy, gx, gy)
    rimw = warp_chan(rim, dx, dy, gx, gy)
    color = color * (1 - rimw[..., None] * sc.get('rim_dark', 0.30))
    color = color * sc['_papermul']
    frame = sc['_paper'] * (1 - cmw[..., None]) + color * cmw[..., None]
    for Pk, sk, p, Rk, dk in ((sc.get('_P1'), sc.get('_s1'), p1, sc.get('tip_R1', 120), 0.24),
                              (sc.get('_P2'), sc.get('_s2'), p2, sc.get('tip_R2', 170), 0.13)):
        if Pk is not None and 0.0 < p < 1.0:
            px, py = path_point(Pk, sk, p)
            draw_tip(frame, px, py, Rk, dk * (1.0 - p * 0.35))
    # 线条逐笔画出 + boil
    li = sc['line_int'] * (sc['ink_field'] <= p_ink)
    bdx, bdy = hd.boil_maps(W, H, sc['seed'] + (t // 2), amp=sc.get('boil', 1.25))
    li = np.clip(warp_chan(li, bdx, bdy, gx, gy), 0, 1)
    a = (li * sc.get('ink_strength', 0.8))[..., None]
    frame = frame * (1 - a) + np.array(sc.get('ink_color', (0.09, 0.09, 0.11)), np.float32)[None, None, :] * a
    frame = frame + sc['_grain'][..., None]
    frame = np.clip(frame, 0, 1) * sc['_vig']
    if ts >= sc['wipe0']:
        wp = ease((ts - sc['wipe0']) / max(sc['wipe_dur'], 1e-6))
        wm = (sc['wipe_field'] <= wp)[..., None].astype(np.float32)
        frame = frame * (1 - wm) + sc['_paper'] * wm
    return frame

def compose(sc, t):
    img = np.clip(render_frame(sc, t) * 255 + 0.5, 0, 255).astype(np.uint8)
    ts = t / sc['fps']
    img = hd.draw_overlays(img, sc, t, ts)
    return hd.draw_texts(img, sc, t, ts)

def render_scene(sc, out_mp4, crf=18, preset='veryfast', sample=None):
    prepare(sc)
    W, H = sc['size']; fps = sc['fps']; n = int(round(sc['dur'] * fps))
    cmd = ['ffmpeg', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(fps),
           '-i', '-', '-an', '-c:v', 'libx264', '-crf', str(crf), '-pix_fmt', 'yuv420p', '-preset', preset, out_mp4]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for t in range(n):
        img = compose(sc, t)
        if sample and t in sample: Image.fromarray(img).save(f'../out/sample_{t:05d}.png')
        p.stdin.write(img.tobytes())
    p.stdin.close(); p.wait()
    return n
