"""hd_config.py —— 把一份 JSON 配置变成 paint_engine 能吃的 scene 字典。
让"输入"只有一个东西：一份可读、可改、可版本管理的 config.json。
"""
import os

TEXT_DEFAULT = dict(font='ZhiMangXing-Regular.ttf', size=54, t0=0.8, t1=None,
                    pos=[0.5, 0.905], anchor='mm', fade=0.45,
                    color=[246, 241, 230], stroke=[24, 22, 28], stroke_width=3)


def _resolve(base, p):
    if p is None:
        return None
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))


def build_scene(cfg, base_dir=None):
    """cfg: dict(来自 config.json)。base_dir: 相对路径的基准（一般=config 所在目录）。"""
    base_dir = base_dir or os.getcwd()
    size = tuple(cfg.get('size', [1920, 1080]))
    fps = int(cfg.get('fps', 24))
    dur = float(cfg.get('dur', 10.0))

    ink0 = float(cfg.get('ink0', 0.0))
    ink_dur = float(cfg.get('ink_dur', 1.5))
    # 默认让上色紧接着"线条画完"之前一点点开始，衔接更连贯
    col0 = float(cfg.get('col0', round(ink0 + ink_dur * 0.7, 3)))
    if 'col_dur' in cfg:
        col_dur = float(cfg['col_dur'])
    elif 'col_frac' in cfg:
        col_dur = max(1.0, dur * float(cfg['col_frac']))
    else:
        col_dur = float(min(6.5, max(3.6, dur * 0.55)))   # 上色占镜头约 55%

    wipe_dur = float(cfg.get('wipe_dur', 0.7))
    wipe0 = cfg.get('wipe0')
    wipe0 = (dur - wipe_dur) if wipe0 is None else float(wipe0)

    texts = []
    for t in cfg.get('texts', []):
        d = dict(TEXT_DEFAULT)
        d.update(t)
        if d.get('t1') is None:                            # 未给 t1 时给个默认时长
            d['t1'] = round(d['t0'] + float(t.get('hold', 2.2)), 3)
        texts.append(d)

    return {
        'size': size, 'fps': fps, 'dur': dur, 'seed': int(cfg.get('seed', 1)),
        'img': _resolve(base_dir, cfg.get('img', 'input.png')),
        'fit': bool(cfg.get('fit', True)), 'soft': float(cfg.get('soft', 0.4)),
        'ink0': ink0, 'ink_dur': ink_dur, 'ink_angle': float(cfg.get('ink_angle', 40.0)),
        'col0': col0, 'col_dur': col_dur,
        'strokes1': int(cfg.get('strokes1', 22)), 'strokes2': int(cfg.get('strokes2', 10)),
        'brush1': cfg.get('brush1'), 'brush2': cfg.get('brush2'),
        'live_amp': float(cfg.get('live_amp', 5.0)),
        'wipe0': wipe0, 'wipe_dur': wipe_dur,
        'overlays': cfg.get('overlays', []), 'texts': texts,
        'paper_base': tuple(cfg.get('paper_base', [240, 235, 224])),
        'grain': float(cfg.get('grain', 0.018)),
        'vig': float(cfg.get('vig', 0.22)),
    }
