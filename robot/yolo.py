# coding: utf-8
"""
yolo.py
=======
YOLOv5 모델 로드 / 추론 래퍼.
우선순위: model/active.pt(학습 교체본) → model/yolov5s.pt(기본) → 다운로드.
"""

import os
import shutil

import numpy as np
import torch

from paths import ACTIVE_MODEL, BASE_WEIGHTS, YOLO_DIR, MODELS_DIR


def load_model():
    """(model, label) 반환. label은 화면 표시용."""
    if os.path.exists(ACTIVE_MODEL):
        m = torch.hub.load(YOLO_DIR, "custom", path=ACTIVE_MODEL,
                           source="local")
        return m, "학습 모델(active.pt)"
    if os.path.exists(BASE_WEIGHTS):
        m = torch.hub.load(YOLO_DIR, "custom", path=BASE_WEIGHTS,
                           source="local")
        return m, "기본 yolov5s"
    # 가중치가 없으면 다운로드 후 model/ 폴더로 복사
    m = torch.hub.load(YOLO_DIR, "yolov5s", pretrained=True, source="local")
    try:
        os.makedirs(MODELS_DIR, exist_ok=True)
        for cand in (os.path.join(YOLO_DIR, "yolov5s.pt"),
                     os.path.join(os.getcwd(), "yolov5s.pt")):
            if os.path.exists(cand):
                shutil.copy(cand, BASE_WEIGHTS)
                break
    except Exception:
        pass
    return m, "기본(COCO, 다운로드)"


def warmup(model, size: int = 320) -> None:
    try:
        model(np.zeros((size, size, 3), dtype=np.uint8), size=size)
    except Exception:
        pass
