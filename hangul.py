# coding: utf-8
"""
hangul.py
=========
OpenCV(BGR) 이미지에 한글 텍스트를 그린다. (cv2.putText는 한글 미지원)

핵심: draw_texts() 는 (텍스트, 위치, 크기, 색, [외곽선색]) 목록을 받아
PIL 한 번의 변환으로 모두 그린다. 외곽선(stroke)을 주면 배경과 대비돼
글씨가 잘 보인다. (요청: 검정 글씨 + 흰 외곽선)
"""

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

from paths import FONT_PATH

_font_cache = {}


def font(size: int):
    f = _font_cache.get(size)
    if f is None:
        try:
            f = ImageFont.truetype(FONT_PATH, size)
        except Exception:
            f = ImageFont.load_default()
        _font_cache[size] = f
    return f


def _to_rgb(bgr):
    return (bgr[2], bgr[1], bgr[0])


def draw_texts(img_bgr, items):
    """items: list of dict 또는 tuple.

    tuple 형식: (text, (x, y), size, color_bgr)
    dict 형식 : {"text","pos","size","color","outline"(선택),"stroke"(선택,기본 0)}
                outline 지정 시 외곽선 색, stroke=외곽선 두께(px)
    """
    if not items:
        return img_bgr
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    for it in items:
        if isinstance(it, dict):
            text = it["text"]; pos = it["pos"]; size = it.get("size", 18)
            color = it.get("color", (255, 255, 255))
            outline = it.get("outline")
            stroke = it.get("stroke", 2 if outline else 0)
        else:
            text, pos, size, color = it
            outline, stroke = None, 0
        kwargs = {}
        if outline is not None and stroke > 0:
            kwargs["stroke_width"] = stroke
            kwargs["stroke_fill"] = _to_rgb(outline)
        draw.text(pos, text, font=font(size), fill=_to_rgb(color), **kwargs)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def outlined(text, pos, size=18, color=(0, 0, 0), outline=(255, 255, 255),
             stroke=2):
    """검정 글씨 + 흰 외곽선 같은 '잘 보이는' 텍스트 항목을 만든다."""
    return {"text": text, "pos": pos, "size": size, "color": color,
            "outline": outline, "stroke": stroke}
