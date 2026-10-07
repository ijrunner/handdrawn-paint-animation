# 原理与实现 / Architecture & Implementation

[中文](#中文) · [English](#english)

---

## 🇨🇳 中文

### 总览：一条纯程序化的逐帧渲染管线
```
底图(一张插画)
   │
   ├─ 预计算"顺序场"：每像素一个 0~1 的进度值（线条什么时候画到、颜色什么时候上到）
   │
   └─ 逐帧合成 → rawvideo 直灌 ffmpeg（中间帧不落盘）→ mp4
```
**核心思想**：把所有"什么时候出现"都事先算成一张 0~1 的**灰度场**，渲染任意一帧时只做 `field <= progress` 的向量化比较，就能得到那一帧的遮盖 mask。这样每帧只做几次数组运算，非常快，也让"逐笔"这种精细时间控制变得可调。

### 1. 纸张与"人味"
- **纸纹**：多层 fbm（分形噪声）合成大块明暗 + 细部粗糙 + 纤维，得到米白纸底。
- **颗粒**：半分辨率高斯噪声放大到全图，强度很小（~0.018）。**全片复用同一张**——若每帧重新随机，H.264 编码会从 ~25ms/帧 暴涨到 ~3500ms/帧。
- **暗角**：径向衰减，把视线收进画面中心。

### 2. 线条"逐笔画出"（draw-on）
1. **提线**：`line_intensity = clip(blur(gray) - gray) × gain`，把"比周围暗"的铅笔/墨线提出来。
2. **顺序场**：`sweep_field` = 沿某角度的平面渐变 + fbm 扰动，代表"笔从哪边开始画"。
3. **揭示**：`线 × (顺序场 <= 进度)`，线便沿扫掠方向逐段显现（等价于 SVG 的 `stroke-dasharray` 描线动画）。
> 用"秩归一化"把任意分布压成 0~1 均匀，保证"进度 = 已画出比例"线性。

### 3. 画笔游走式上色（核心）
- **笔路** `brush_path`：来回扫 + 手抖 + 整体旋转（斜向，不是横滚），范围超出画布以保证四角覆盖。
- **到达时间场** `field_from_path`：沿路径算弧长，在每个采样点的半径 R 圆盘内写入 `val = 弧长 - R`（取最小）→ 每个像素记录"笔尖覆盖到它的时刻"。**笔走到哪，哪一块才上色。**
- **笔触条纹** `streaks`：对噪声做**各向异性**模糊（顺笔方向拉长），得到顺笔的毛糙丝。
- **一笔一笔的节奏** `steps`：把进度切成 N 段，每段"前 55% 快速落笔 + 后 45% 停顿"。
- **笔尖** `draw_tip`：在笔尖处压一个高斯湿痕，眼睛能跟着笔走。
- **两遍叠色**：第一遍斜向铺淡底（62%），第二遍换向加深（44%）。
- **湿边**：上色前沿一圈压暗，模拟水彩的色素沉积。

### 4. 呼吸 / 微动（不是镜头推拉）
用缓慢正弦的像素位移场（相位随秒推进），再用 `cv2.remap` 把颜色层与 mask **一起**位移——画面像还在"湿着"、轻轻晃。

### 5. boiling（手绘抖动）
低分辨率随机位移场，用在**线条层**上，且**每 2 帧才换一次**（on-twos），模拟手绘每秒 12 张的抖动；颗粒不参与（保码率）。

### 6. 粒子 / 字幕 / 转场
- **粒子**（浮尘/雨/划痕）：位置 = `基准 + 时间(秒) × 速度`。
- **字幕**：PIL 渲染到透明图层，支持深色描边，按 `t0/t1` 淡入淡出（浅色字压深色画面才看得见）。
- **转场**：另一张斜向顺序场，用纸色把画面从一角"洗白"。

### 7. 编码与性能
每帧算完直接 `stdin.write(img.tobytes())` 喂 ffmpeg（**不逐帧存 PNG**）；x264 `veryfast/ultrafast` + CRF18。长渲染建议**前台同步跑**（部分沙箱里后台进程会被挂起）。

### 8. 声音
不包含在本仓库。旁白（TTS）与配乐属另一条流程，可与本引擎输出的无声片段用 `ffmpeg` 混流。

---

## 🇬🇧 English

### Overview: a fully procedural, per-frame render pipeline
```
one illustration
   │
   ├─ precompute "order fields": a 0~1 progress value per pixel
   │   (when the line is drawn, when the color arrives)
   │
   └─ composite each frame → pipe raw frames into ffmpeg (no PNGs on disk) → mp4
```
**Key idea**: every "when does it appear" question is precomputed as a 0~1 grayscale **field**; rendering any frame is just a vectorized `field <= progress` comparison that yields that frame's mask. Each frame is a handful of array ops — fast, and it makes fine-grained timing (like "stroke by stroke") easy to tune.

### 1. Paper & "hand-made" feel
- **Paper texture**: multi-octave fbm noise (large tone + fine grain + fibers) → off-white paper.
- **Grain**: half-res Gaussian noise upscaled, low amplitude (~0.018), **the same plate reused for the whole film** — per-frame random grain would blow H.264 encode time from ~25ms to ~3500ms per frame.
- **Vignette**: radial falloff.

### 2. Draw-on (lines drawn stroke by stroke)
1. **Line extraction**: `clip(blur(gray) - gray) × gain` isolates pencil/ink lines.
2. **Order field**: `sweep_field` = a directional ramp + fbm jitter.
3. **Reveal**: `line × (order_field <= progress)` — equivalent to an SVG `stroke-dasharray` animation.
> A rank-normalization keeps "progress = fraction drawn" linear.

### 3. Brush-travel watercolor fill (the core)
- **Brush path** `brush_path`: serpentine + hand jitter + global rotation (diagonal, not a roller), extended beyond the canvas so corners are covered.
- **Arrival-time field** `field_from_path`: along the path, for each sample write `val = arclen - R` inside a disc of radius R (taking the minimum) → each pixel records *when the brush tip first covered it*. **Only where the brush has passed gets colored.**
- **Bristle streaks** `streaks`: anisotropically blurred noise (elongated along the brush travel).
- **Stroke rhythm** `steps`: split progress into N segments, each "fast stroke (55%) then pause (45%)".
- **Brush tip** `draw_tip`: a Gaussian wet mark at the tip so the eye can follow it.
- **Two passes**: a diagonal light wash (62%) then a cross-direction deepening (44%).
- **Wet rim**: a darkened band at the fill frontier, mimicking pigment pooling.

### 4. Breathing / inner motion (no camera push-in)
A slow sinusoidal pixel-displacement field (phase advancing in seconds) applied via `cv2.remap` to the color layer **and** the mask together — the picture looks like it is still wet and gently swaying.

### 5. Boiling
A low-res random displacement field applied to the **line layer**, refreshed **every 2 frames** (on-twos) for a hand-drawn shimmer; grain is excluded to keep bitrate low.

### 6. Particles / captions / transition
- **Particles** (dust/rain/scratch): position = `base + time(seconds) × speed`.
- **Captions**: rendered by PIL onto an RGBA layer with optional dark stroke, faded by `t0/t1` (light text + dark stroke stays readable on dark art).
- **Transition**: another directional field wipes the frame to paper color.

### 7. Encoding & performance
Frames are written straight into ffmpeg's stdin (**no per-frame PNG**); x264 `veryfast/ultrafast` at CRF18. For long renders, run **in the foreground** (in some sandboxes background processes get suspended).

### 8. Audio
Not included in this repo. Narration (TTS) and music are a separate pipeline; mux them with `ffmpeg` against the silent clips produced here.
