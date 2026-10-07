"""
handdrawn.py —— "像人手画的"动效渲染引擎 v6
v6 修正：叠加层与字幕的时间基准统一为「秒」(此前误用帧序号)，并支持字幕描边(浅字+深描边)。
v5 修正：逐帧随机颗粒会摧毁 H.264 编码，改为全片同一张「静态颗粒版」；源图可选 soft 柔化。
其余：纸纹 · boiling(on-twos) · 暗角 · 手写体排版。rawvideo 直灌 ffmpeg。
"""
import os, subprocess
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

def _rng(seed):
    return np.random.default_rng(int(seed) & 0x7fffffff)

# ---------- 纹理 ----------
def fbm(w, h, seed, octaves=6, base=4):
    rng = _rng(seed); acc = np.zeros((h, w), np.float32); amp = 1.0; tot = 0.0
    for o in range(octaves):
        res = base * (2 ** o); hh = max(2, res); ww = max(2, int(res * w / h))
        n = rng.random((hh, ww)).astype(np.float32)
        n = cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC)
        acc += (n - 0.5) * amp; tot += amp; amp *= 0.55
    return acc / tot

def paper_texture(w, h, seed=1, base=(237, 231, 219)):
    large = fbm(w, h, seed, octaves=5, base=3)
    fine = fbm(w, h, seed + 101, octaves=6, base=11)
    fib = _rng(seed + 7).random((h, w)).astype(np.float32)
    fib = cv2.GaussianBlur(fib, (0, 0), 0.9)
    tone = 0.90 + 0.16 * large + 0.05 * fine
    tone *= (0.975 + 0.05 * (fib - 0.5))
    tex = np.stack([tone] * 3, -1) * np.array(base, np.float32)[None, None, :] / 255.0
    return np.clip(tex, 0, 1).astype(np.float32)

# ---------- boiling ----------
def boil_maps(w, h, seed, amp=2.0, scale=46.0):
    rng = _rng(seed)
    hh = max(3, int(round(h / scale))); ww = max(3, int(round(w / scale)))
    dx = (rng.random((hh, ww)).astype(np.float32) * 2 - 1)
    dy = (rng.random((hh, ww)).astype(np.float32) * 2 - 1)
    s = max(1.0, hh * 0.07)
    dx = cv2.GaussianBlur(dx, (0, 0), s); dy = cv2.GaussianBlur(dy, (0, 0), s)
    dx = cv2.resize(dx, (w, h), interpolation=cv2.INTER_CUBIC) * amp
    dy = cv2.resize(dy, (w, h), interpolation=cv2.INTER_CUBIC) * amp
    return dx, dy

def warp(arr, dx, dy, gx, gy):
    return cv2.remap(arr, gx + dx, gy + dy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

def grain_plate(w, h, seed, amt=0.022):
    g = _rng(seed).standard_normal((h // 2, w // 2)).astype(np.float32)
    return (cv2.resize(g, (w, h), interpolation=cv2.INTER_LINEAR) * amt).astype(np.float32)

def vignette_mask(w, h, amt=0.24, p=1.8):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    return (1 - amt * np.clip(r, 0, 1.4) ** p).astype(np.float32)[..., None]

# ---------- 相机 ----------
def interp_rect(r0, r1, k):
    return [r0[i] + (r1[i] - r0[i]) * k for i in range(4)]

def get_crop(L, rect, out_wh):
    sw, sh = L['_wh']; x0, y0, x1, y1 = rect
    x0 = int(x0 * sw); x1 = int(x1 * sw); y0 = int(y0 * sh); y1 = int(y1 * sh)
    x0 = max(0, min(sw - 1, x0)); x1 = max(x0 + 1, min(sw, x1))
    y0 = max(0, min(sh - 1, y0)); y1 = max(y0 + 1, min(sh, y1))
    c = L['_arr'][y0:y1, x0:x1]
    interp = cv2.INTER_AREA if (x1 - x0) > out_wh[0] else cv2.INTER_LINEAR
    return cv2.resize(c, out_wh, interpolation=interp)

# ---------- 叠加层（位移按秒） ----------
def draw_overlays(img, scene, t, ts):
    H, W = img.shape[:2]
    for ov in scene.get('overlays', []):
        typ = ov['type']; sd = ov.get('seed', 1)
        if typ == 'dust':
            a = ov.get('alpha', 0.22); col = np.array((246, 241, 226), np.float32)
            for i in range(ov.get('n', 50)):
                rng = _rng(sd * 131 + i)
                x = int((rng.random() * W + ts * rng.uniform(4, 16)) % W)
                y = int((rng.random() * H - ts * rng.uniform(4, 14)) % H)
                r = 1 if rng.random() < 0.7 else 2
                y0 = max(0, y - r + 1); x0 = max(0, x - r + 1); y1 = min(H, y + r); x1 = min(W, x + r)
                if y1 <= y0 or x1 <= x0: continue
                reg = img[y0:y1, x0:x1].astype(np.float32)
                img[y0:y1, x0:x1] = (reg * (1 - a) + col * a).astype(np.uint8)
        elif typ in ('rain', 'scratch'):
            if typ == 'scratch' and (t // 2) % ov.get('period', 7) != 0: continue
            layer = np.zeros((H, W, 3), np.uint8); mask = np.zeros((H, W), np.uint8)
            if typ == 'rain':
                ang = ov.get('ang', 0.35)
                for i in range(ov.get('n', 90)):
                    rng = _rng(sd * 313 + i); spd = rng.uniform(600, 1300)
                    x = (rng.random() * W + ts * spd * ang) % W; y = (rng.random() * H + ts * spd) % H
                    ln = rng.uniform(18, 50)
                    p1 = (int(x), int(y)); p2 = (int(x - ln * ang), int(y + ln))
                    cv2.line(layer, p1, p2, (222, 230, 242), 1); cv2.line(mask, p1, p2, 255, 1)
                alpha = ov.get('alpha', 0.30)
            else:
                for i in range(ov.get('n', 3)):
                    rng = _rng(sd * 977 + (t // 2) + i)
                    x = int(rng.random() * W); y0 = int(rng.random() * H * 0.4); y1 = y0 + int(rng.uniform(120, 600))
                    off = int(rng.uniform(-6, 6))
                    cv2.line(layer, (x, y0), (x + off, y1), (255, 250, 235), 1)
                    cv2.line(mask, (x, y0), (x + off, y1), 255, 1)
                alpha = ov.get('alpha', 0.12)
            m = (mask.astype(np.float32) / 255.0 * alpha)[..., None]
            img = (img * (1 - m) + layer * m).astype(np.uint8)
    return img

# ---------- 文字（时间按秒；支持描边） ----------
FONT_CACHE = {}
def load_font(name, size):
    key = (name, size)
    if key in FONT_CACHE: return FONT_CACHE[key]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts', name)
    try:
        f = ImageFont.truetype(path, size)
    except Exception:
        f = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc', size)
    FONT_CACHE[key] = f
    return f

def draw_texts(img, scene, t, ts):
    H, W = img.shape[:2]
    for tx in scene.get('texts', []):
        t0, t1 = tx['t0'], tx['t1']
        if not (t0 <= ts <= t1): continue
        fi = tx.get('fade', 0.45)
        a = min(1.0, (ts - t0) / fi, (t1 - ts) / fi)
        a = max(0.0, min(1.0, a)) * tx.get('alpha', 1.0)
        if a <= 0.01: continue
        font = load_font(tx.get('font', 'ZhiMangXing-Regular.ttf'), tx.get('size', 42))
        txt = tx['str']
        sw = int(tx.get('stroke_width', 0))
        bb = font.getbbox(txt, stroke_width=sw)
        pad = 8 + sw + 2
        tw = bb[2] - bb[0] + 2 * pad; th = bb[3] - bb[1] + 2 * pad
        layer = Image.new('RGBA', (tw, th), (0, 0, 0, 0))
        dd = ImageDraw.Draw(layer)
        col = tuple(tx.get('color', (28, 26, 30))) + (int(255 * a),)
        if sw > 0:
            sc = tuple(tx.get('stroke', (18, 16, 20))) + (int(255 * a),)
            dd.text((-bb[0] + pad, -bb[1] + pad), txt, font=font, fill=col, stroke_width=sw, stroke_fill=sc)
        else:
            dd.text((-bb[0] + pad, -bb[1] + pad), txt, font=font, fill=col)
        arr = np.asarray(layer, np.float32) / 255.0
        alpha = arr[..., 3:4]; rgb = arr[..., :3] * 255.0
        jit = 1.1 if tx.get('jitter', True) else 0.0
        rng = _rng(scene['seed'] + (t // 2) + int(t0 * 100))
        x = int(tx['pos'][0] * W + rng.uniform(-jit, jit)); y = int(tx['pos'][1] * H + rng.uniform(-jit, jit))
        anc = tx.get('anchor', 'lt')
        if anc == 'mm': x -= tw // 2; y -= th // 2
        elif anc == 'mt': x -= tw // 2
        elif anc == 'lm': y -= th // 2
        elif anc == 'rm': x -= tw; y -= th // 2
        x0 = max(0, x); y0 = max(0, y); x1 = min(W, x + tw); y1 = min(H, y + th)
        if x1 <= x0 or y1 <= y0: continue
        sa = alpha[y0 - y:y1 - y, x0 - x:x1 - x]; srgb = rgb[y0 - y:y1 - y, x0 - x:x1 - x]
        reg = img[y0:y1, x0:x1].astype(np.float32)
        img[y0:y1, x0:x1] = (reg * (1 - sa) + srgb * sa).astype(np.uint8)
    return img

# ---------- 场景 ----------
def prepare(scene):
    W, H = scene['size']
    scene['fps'] = scene.get('fps', 24); scene['seed'] = scene.get('seed', 1)
    scene['_paper'] = paper_texture(W, H, scene['seed'] + 3, base=scene.get('paper_base', (237, 231, 219)))
    ps = scene.get('paper_strength', 0.26)
    scene['_paperfac'] = ((1 - ps) + np.clip(scene['_paper'] * 1.12, 0, 1) * ps).astype(np.float32)
    scene['_vig'] = vignette_mask(W, H, scene.get('vig', 0.24))
    scene['_grainplate'] = grain_plate(W, H, 4242, scene.get('grain', 0.022))
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    scene['_gx'], scene['_gy'] = gx, gy
    for i, L in enumerate(scene['layers']):
        im = Image.open(L['img']).convert('RGB')
        arr = np.asarray(im, np.float32) / 255.0
        soft = L.get('soft', 0.5)
        if soft > 0:
            arr = cv2.GaussianBlur(arr, (0, 0), soft)
        L['_arr'] = arr
        L['_wh'] = (im.width, im.height)
        L.setdefault('seed', scene['seed'] * 100 + i * 17 + 5)
        L.setdefault('boil', 1.4); L.setdefault('alpha', 1.0); L.setdefault('blend', 'normal')
    return scene

def render_frame_f(scene, t):
    W, H = scene['size']; k = min(1.0, max(0.0, t / max(scene['dur'] * scene.get('fps', 24), 1e-6)))
    gx, gy = scene['_gx'], scene['_gy']
    frame = None
    for L in scene['layers']:
        rect = interp_rect(L['cam'][0], L['cam'][1], k)
        arr = get_crop(L, rect, (W, H))
        amp = L.get('boil', 0.0)
        if amp > 0:
            dx, dy = boil_maps(W, H, L['seed'] + (t // 2), amp=amp)
            arr = warp(arr, dx, dy, gx, gy)
        al = L.get('alpha', 1.0); bl = L.get('blend', 'normal')
        if bl == 'normal' and al >= 0.999:
            frame = arr
            continue
        if frame is None: frame = scene['_paper'].copy()
        if bl == 'normal':     frame = frame * (1 - al) + arr * al
        elif bl == 'multiply': frame = frame * (1 - al) + (frame * arr) * al
        elif bl == 'screen':   frame = frame * (1 - al) + (1 - (1 - frame) * (1 - arr)) * al
    if frame is None: frame = scene['_paper'].copy()
    frame = frame * scene['_paperfac']
    frame += scene['_grainplate'][..., None]
    frame *= scene['_vig']
    np.clip(frame, 0, 1, out=frame)
    return frame

def compose(scene, t):
    ts = t / scene.get('fps', 24)
    img = (render_frame_f(scene, t) * 255 + 0.5).astype(np.uint8)
    img = draw_overlays(img, scene, t, ts)
    img = draw_texts(img, scene, t, ts)
    return img

def render_scene(scene, out_mp4, fps=None, crf=20, preset='ultrafast', sample=None):
    prepare(scene)
    W, H = scene['size']; fps = fps or scene['fps']
    n = int(round(scene['dur'] * fps))
    cmd = ['ffmpeg', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(fps),
           '-i', '-', '-an', '-c:v', 'libx264', '-crf', str(crf), '-pix_fmt', 'yuv420p',
           '-preset', preset, out_mp4]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for t in range(n):
        img = compose(scene, t)
        if sample and t in sample:
            Image.fromarray(img).save(f'../out/sample_{t:05d}.png')
        p.stdin.write(img.tobytes())
    p.stdin.close(); p.wait()
    return n

if __name__ == '__main__':
    import sys, time
    img = sys.argv[1] if len(sys.argv) > 1 else '../assets/desk.png'
    scene = {'size': (1920, 1080), 'fps': 24, 'dur': 4.0, 'seed': 7,
             'layers': [{'img': img, 'cam': [[0.06, 0.05, 0.86, 0.95], [0.12, 0.08, 0.92, 0.98]], 'boil': 1.4}],
             'overlays': [{'type': 'dust', 'n': 50, 'seed': 3}], 'texts': []}
    t0 = time.time(); n = render_scene(scene, '../out/probe.mp4')
    print('rendered', n, 'frames in', round(time.time() - t0, 2), 's ->', round((time.time() - t0) / n * 1000), 'ms/frame')
