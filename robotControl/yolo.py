# coding: utf-8
"""
yolo.py  (gradio 브랜치, v4.0~)
==============================
YOLO 추론 래퍼 — **OpenCV DNN(ONNX)** 기반. torch/ultralytics 불필요(경량).

- 모델: model/active.onnx (+ model/active.names 클래스명)
- v5(출력 5+nc) / v8·v11(출력 4+nc) 출력 형식을 자동 판별
- 전처리(letterbox) · 후처리(NMS)를 직접 수행

호환 인터페이스(기존 코드 그대로 사용):
  load_model() -> (model, label)      # model.names(list), model.eval() 지원
  infer(model, frame, imgsz, conf, max_det) -> ndarray[[x1,y1,x2,y2,conf,cls]]
  warmup(model, size)

.pt → .onnx 변환은 export_onnx.py 가 담당(ultralytics 사용, 변환 1회용).
"""

import os

import cv2
import numpy as np

from paths import (ACTIVE_ONNX, ACTIVE_MODEL, get_active_name,
                   get_active_classes)
from motion_table import COCO_CLASSES

INFER_IMGSZ = 320            # export_onnx.EXPORT_IMGSZ 와 동일해야 함
IOU_THRES = 0.45


class DnnYOLO:
    """OpenCV DNN ONNX 모델 래퍼. (ultralytics YOLO 와 최소 호환)"""

    def __init__(self, net, names, imgsz=INFER_IMGSZ):
        self.net = net
        self.names = names           # list[str] — names[cls_id]
        self.imgsz = imgsz

    def eval(self):                  # 호환용(아무 동작 안 함)
        return self


def _ensure_onnx():
    """active.onnx 준비: 없으면 active.pt 변환, 그것도 없으면 기본 모델 생성."""
    if os.path.exists(ACTIVE_ONNX):
        return
    import export_onnx
    if os.path.exists(ACTIVE_MODEL):
        export_onnx.apply_pt_as_active(ACTIVE_MODEL,
                                       label=get_active_name() or "active")
    else:
        export_onnx.ensure_default_onnx()


def _read_net(onnx_path):
    """한글/유니코드 경로 우회: 파일을 바이트로 읽어 버퍼로 net 생성."""
    with open(onnx_path, "rb") as f:
        buf = f.read()
    return cv2.dnn.readNetFromONNX(bytearray(buf))


def load_model():
    """(model, label) 반환. label 은 화면 표시용."""
    _ensure_onnx()
    net = _read_net(ACTIVE_ONNX)
    try:
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    except Exception:
        pass
    names = get_active_classes() or list(COCO_CLASSES)
    label = get_active_name() or "사용자 모델"
    return DnnYOLO(net, names, INFER_IMGSZ), label


def _letterbox(img, new):
    """비율 유지 리사이즈 + 114 패딩 → (canvas, ratio, dw, dh)."""
    h, w = img.shape[:2]
    r = min(new / h, new / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((new, new, 3), 114, dtype=np.uint8)
    dw, dh = (new - nw) // 2, (new - nh) // 2
    canvas[dh:dh + nh, dw:dw + nw] = resized
    return canvas, r, dw, dh


def infer(model, frame, imgsz=None, conf=0.25, max_det=300):
    """프레임 추론 → dets ndarray [[x1,y1,x2,y2,conf,cls], ...] (BGR 입력)."""
    net, names = model.net, model.names
    sz = model.imgsz
    nc = len(names)

    lb, r, dw, dh = _letterbox(frame, sz)
    blob = cv2.dnn.blobFromImage(lb, 1 / 255.0, (sz, sz), swapRB=True,
                                 crop=False)
    net.setInput(blob)
    out = net.forward()
    preds = out[0] if out.ndim == 3 else out          # (rows, cols)
    if preds.shape[0] < preds.shape[1]:               # v8/v11: (4+nc, N) → 전치
        preds = preds.T
    cols = preds.shape[1]
    has_obj = cols >= nc + 5                           # v5(=obj 포함)인지

    box = preds[:, :4].astype(np.float32)
    if has_obj:
        obj = preds[:, 4]
        cls_scores = preds[:, 5:5 + nc]
    else:
        obj = None
        cls_scores = preds[:, 4:4 + nc]
    if cls_scores.shape[1] == 0:
        return np.empty((0, 6))
    cls_ids = np.argmax(cls_scores, axis=1)
    cls_conf = cls_scores[np.arange(cls_scores.shape[0]), cls_ids]
    scores = cls_conf * obj if has_obj else cls_conf

    keep = scores >= conf
    if not np.any(keep):
        return np.empty((0, 6))
    box, scores, cls_ids = box[keep], scores[keep], cls_ids[keep]

    cx, cy, w, h = box[:, 0], box[:, 1], box[:, 2], box[:, 3]
    x1 = (cx - w / 2 - dw) / r
    y1 = (cy - h / 2 - dh) / r
    x2 = (cx + w / 2 - dw) / r
    y2 = (cy + h / 2 - dh) / r
    H, W = frame.shape[:2]
    x1 = np.clip(x1, 0, W - 1); x2 = np.clip(x2, 0, W - 1)
    y1 = np.clip(y1, 0, H - 1); y2 = np.clip(y2, 0, H - 1)

    boxes_nms = np.stack([x1, y1, x2 - x1, y2 - y1], axis=1).tolist()
    idxs = cv2.dnn.NMSBoxes(boxes_nms, scores.astype(float).tolist(),
                            float(conf), IOU_THRES)
    if len(idxs) == 0:
        return np.empty((0, 6))
    idxs = np.array(idxs).flatten()[:max_det]
    return np.stack([x1[idxs], y1[idxs], x2[idxs], y2[idxs],
                     scores[idxs], cls_ids[idxs].astype(np.float32)], axis=1)


def warmup(model, size: int = None) -> None:
    try:
        infer(model, np.zeros((model.imgsz, model.imgsz, 3), dtype=np.uint8),
              conf=0.99)
    except Exception:
        pass
