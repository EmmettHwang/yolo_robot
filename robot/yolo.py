# coding: utf-8
"""
yolo.py
=======
YOLO 모델 로드 / 추론 래퍼 (ultralytics 기반).

- ultralytics 의 YOLO 는 .pt 안의 버전을 자동 감지 → YOLOv5/v8/v11 모두 호환.
- ./yolov5 클론이 필요 없다. (pip install ultralytics)

우선순위: model/active.pt(학습/교체본) → model/yolov5s.pt(기본) → 다운로드.
"""

import os
import shutil

import numpy as np
from ultralytics import YOLO

from paths import ACTIVE_MODEL, BASE_WEIGHTS, MODELS_DIR


def load_model():
    """(model, label) 반환. label은 화면 표시용."""
    if os.path.exists(ACTIVE_MODEL):
        return YOLO(ACTIVE_MODEL), "학습/교체 모델(active.pt)"
    if os.path.exists(BASE_WEIGHTS):
        return YOLO(BASE_WEIGHTS), "기본 yolov5s"
    # 없으면 다운로드 후 model/ 폴더로 복사
    m = YOLO("yolov5su.pt")
    try:
        os.makedirs(MODELS_DIR, exist_ok=True)
        for cand in ("yolov5su.pt", "yolov5s.pt"):
            if os.path.exists(cand):
                shutil.copy(cand, BASE_WEIGHTS)
                break
    except Exception:
        pass
    return m, "기본(다운로드)"


def infer(model, frame, imgsz=320):
    """프레임 추론 → dets ndarray [[x1,y1,x2,y2,conf,cls], ...] (BGR 입력 OK)."""
    res = model(frame, imgsz=imgsz, verbose=False)
    r = res[0]
    b = r.boxes
    if b is None or len(b) == 0:
        return np.empty((0, 6))
    xyxy = b.xyxy.cpu().numpy()
    conf = b.conf.cpu().numpy().reshape(-1, 1)
    cls = b.cls.cpu().numpy().reshape(-1, 1)
    return np.hstack([xyxy, conf, cls])


def warmup(model, size: int = 320) -> None:
    try:
        model(np.zeros((size, size, 3), dtype=np.uint8), imgsz=size,
              verbose=False)
    except Exception:
        pass
