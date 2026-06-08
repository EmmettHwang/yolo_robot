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

from paths import (ACTIVE_MODEL, BASE_WEIGHTS, MODELS_DIR,
                   get_active_name, set_active_name)


def _match_active_name():
    """active.pt 와 내용이 같은 model/*.pt 를 찾아 그 이름을 반환(원본명 추정)."""
    import hashlib
    try:
        asz = os.path.getsize(ACTIVE_MODEL)
        with open(ACTIVE_MODEL, "rb") as f:
            ah = hashlib.md5(f.read()).hexdigest()
        for fn in os.listdir(MODELS_DIR):
            if fn.lower().endswith(".pt") and fn != "active.pt":
                fp = os.path.join(MODELS_DIR, fn)
                try:
                    if os.path.getsize(fp) != asz:
                        continue
                    with open(fp, "rb") as f:
                        if hashlib.md5(f.read()).hexdigest() == ah:
                            return fn
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _active_label():
    name = get_active_name()
    if name:
        return name
    guess = _match_active_name()
    if guess:
        set_active_name(guess)        # 다음부터 빠르게
        return guess
    return "사용자 모델"


def load_model():
    """(model, label) 반환. label은 화면 표시용(실제 모델 이름)."""
    if os.path.exists(ACTIVE_MODEL):
        return YOLO(ACTIVE_MODEL), _active_label()
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


def infer(model, frame, imgsz=320, conf=0.25, max_det=300):
    """프레임 추론 → dets ndarray [[x1,y1,x2,y2,conf,cls], ...] (BGR 입력 OK).
    conf 미만은 제외, 최대 max_det 개."""
    res = model(frame, imgsz=imgsz, conf=conf, max_det=max_det, verbose=False)
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
