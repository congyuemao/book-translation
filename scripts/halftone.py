#!/usr/bin/env python3
"""把照片做成半色调网点图或多色调图，给手搓封面用（版画、海报风格）。

    python halftone.py <输入图片> <输出.png> [--crop x0,y0,x1,y1] [--mask 抠图.png] [--width 1500]
                       [--mode halftone|duotone] [--cell 11] [--angle 45] [--ink 121110] [--paper none]
                       [--stops "0:0e0d0d,0.42:b01c1a,0.78:e87846,1:f6ecd8"] [--contrast 1.0]

- --crop：裁切范围，0—1 的比例（0.17,0.13,0.86,0.70）或像素。
- --mask：黑白或带透明通道的抠图，白色或不透明的部分保留，其余透明。尺寸跟原图一样或跟裁切后一样都行。
  人像抠图可以先用别的工具做好；不给就整张保留。
- halftone：按亮度画网点，--cell 是网点间距（像素），--angle 是网角，--ink 是网点颜色，
  --paper 是底色（none 为透明，适合叠在封面色块上）。
- duotone：按亮度映射到 --stops 给的几种颜色（位置:颜色），背景同样可透明。
- 照片要用公有领域或有授权的，来源和授权写进 project.json 的 build.edition_note。
只依赖 numpy 和 Pillow。
"""
import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def hex_rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def main():
    ap = argparse.ArgumentParser(description="半色调、多色调封面图")
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--crop"); ap.add_argument("--mask")
    ap.add_argument("--width", type=int, default=1500)
    ap.add_argument("--mode", choices=["halftone", "duotone"], default="halftone")
    ap.add_argument("--cell", type=float, default=11); ap.add_argument("--angle", type=float, default=45)
    ap.add_argument("--ink", default="121110"); ap.add_argument("--paper", default="none")
    ap.add_argument("--stops", default="0:0e0d0d,0.42:b01c1a,0.78:e87846,1:f6ecd8")
    ap.add_argument("--contrast", type=float, default=1.0, help="大于 1 增强对比")
    a = ap.parse_args()
    try:
        import numpy as np
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        sys.exit("需要 numpy 和 Pillow：python -m pip install numpy pillow")

    img = Image.open(a.src).convert("L")
    mask = None
    if a.mask:
        m = Image.open(a.mask)
        mask = m.getchannel("A") if "A" in m.getbands() else m.convert("L")
    if a.crop:
        vals = [float(v) for v in a.crop.split(",")]
        w, h = img.size
        if all(v <= 1 for v in vals):
            vals = [vals[0] * w, vals[1] * h, vals[2] * w, vals[3] * h]
        box = tuple(int(v) for v in vals)
        if mask is not None and mask.size == img.size:  # 抠图按原图做的，跟着裁；按裁切后做的就不动
            mask = mask.crop(box)
        img = img.crop(box)
    if mask is not None and abs(mask.width / mask.height - img.width / img.height) > 0.02:
        sys.exit(f"抠图 {mask.size} 和{'裁切后的' if a.crop else ''}图片 {img.size} 比例对不上")
    scale = a.width / img.width
    size = (a.width, int(img.height * scale))
    img = ImageOps.autocontrast(img.resize(size, Image.LANCZOS), cutoff=1)
    alpha = np.array(mask.resize(size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(2)), float) / 255 if mask is not None \
        else np.ones((size[1], size[0]))
    v = np.array(img, float) / 255
    if a.contrast != 1:
        v = np.clip((v - 0.5) * a.contrast + 0.5, 0, 1)

    if a.mode == "halftone":
        yy, xx = np.indices(v.shape)
        t = np.deg2rad(a.angle)
        u = (xx * np.cos(t) + yy * np.sin(t)) * 2 * np.pi / a.cell
        k = (-xx * np.sin(t) + yy * np.cos(t)) * 2 * np.pi / a.cell
        screen = (np.cos(u) * np.cos(k) + 1) / 2
        ink = ((1 - v) > (1 - screen) * 0.98 + 0.01).astype(float)
        ink = np.array(Image.fromarray((ink * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.7)), float) / 255
        ink = np.clip((ink - 0.27) * 2.2, 0, 1)
        r, g, b = hex_rgb(a.ink)
        cover = ink * alpha
        if a.paper == "none":
            rgba = np.dstack([np.full(v.shape, r), np.full(v.shape, g), np.full(v.shape, b), cover * 255])
        else:
            pr, pg, pb = hex_rgb(a.paper)
            rgb = [p * (1 - cover) + c * cover for p, c in ((pr, r), (pg, g), (pb, b))]
            rgba = np.dstack(rgb + [alpha * 255])
    else:
        stops = sorted((float(p), hex_rgb(c)) for p, c in (s.split(":") for s in a.stops.split(",")))
        rgb = [np.interp(v, [s[0] for s in stops], [s[1][i] for s in stops]) for i in range(3)]
        rgba = np.dstack(rgb + [alpha * 255])
    Image.fromarray(rgba.clip(0, 255).astype("uint8"), "RGBA").save(a.out, optimize=True)
    print(f"写出 {a.out}：{size[0]}×{size[1]}，{a.mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
