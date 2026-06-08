# coding: utf-8
"""
yolo.py
=======
YOLOv5 모델 로드 / 추론 래퍼.
교체된 모델(models/active.pt)이 있으면 그것을, 없으면 기본 yolov5s.
"""

import os

import numpy as np
import torch

from paths import ACTIVE_MODEL, YOLO_DIR


def load_model():
    """(model, label) 반환. label은 화면 표시용."""
    if os.path.exists(ACTIVE_MODEL):
        m = torch.hub.load(YOLO_DIR, "custom", path=ACTIVE_MODEL,
                           source="local")
        return m, "학습 모델(active.pt)"
    m = torch.hub.load(YOLO_DIR, "yolov5s", pretrained=True, source="local")
    return m, "기본(COCO)"


def warmup(model, size: int = 320) -> None:
    try:
        model(np.zeros((size, size, 3), dtype=np.uint8), size=size)
    except Exception:
        pass
