# coding: utf-8
"""
export_onnx.py
==============
.pt(ultralytics) → .onnx 변환 + 클래스명 사이드카 기록.

런타임 추론(OpenCV DNN)은 ultralytics/torch 가 필요 없지만, .pt 를 ONNX 로
바꾸는 이 단계만 ultralytics 를 쓴다(변환 1회용 / 학습 웹앱에서도 사용).

추론과 입력 크기를 맞추기 위해 항상 imgsz=EXPORT_IMGSZ(320) 정적 export.
"""

import os
import shutil

from paths import (MODELS_DIR, ACTIVE_ONNX, ACTIVE_CLASSES, BASE_ONNX,
                   set_active_classes, set_active_name)

EXPORT_IMGSZ = 320      # 런타임 추론(INFER_SIZE)과 동일해야 함


def _names_list(model) -> list:
    n = model.names
    if isinstance(n, dict):
        return [n[k] for k in sorted(n)]
    return list(n)


def export_pt_to_onnx(pt_path: str, imgsz: int = EXPORT_IMGSZ):
    """주어진 .pt 를 같은 폴더에 .onnx 로 export. (onnx_path, names) 반환."""
    from ultralytics import YOLO
    model = YOLO(pt_path)
    onnx_path = model.export(format="onnx", imgsz=imgsz, opset=12)
    return str(onnx_path), _names_list(model)


def apply_pt_as_active(pt_path: str, label: str = None,
                       imgsz: int = EXPORT_IMGSZ) -> list:
    """.pt 를 ONNX 로 변환해 active.onnx + active.names 로 적용. names 반환."""
    onnx_path, names = export_pt_to_onnx(pt_path, imgsz)
    os.makedirs(MODELS_DIR, exist_ok=True)
    shutil.copy(onnx_path, ACTIVE_ONNX)
    set_active_classes(names)
    set_active_name(label or os.path.basename(pt_path))
    return names


def apply_onnx_as_active(onnx_path: str, names_path: str = None,
                         label: str = None) -> list:
    """이미 만들어진 .onnx 를 active.onnx 로 적용(ultralytics 불필요, 파일 복사).

    클래스명(.names)은 같은 이름의 사이드카(<stem>.names)를 자동으로 찾아 적용.
    없으면 현재 active.names 를 유지한다. 적용된 클래스 목록을 반환.
    """
    if onnx_path and os.path.abspath(onnx_path) != os.path.abspath(ACTIVE_ONNX):
        os.makedirs(MODELS_DIR, exist_ok=True)
        shutil.copy(onnx_path, ACTIVE_ONNX)
    if names_path is None:
        cand = os.path.splitext(onnx_path)[0] + ".names"
        if os.path.exists(cand):
            names_path = cand
    if (names_path and os.path.exists(names_path)
            and os.path.abspath(names_path) != os.path.abspath(ACTIVE_CLASSES)):
        shutil.copy(names_path, ACTIVE_CLASSES)
    set_active_name(label or os.path.basename(onnx_path))
    try:
        with open(ACTIVE_CLASSES, encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []


def make_base_active() -> list:
    """기본 모델(yolov5su, COCO 80클래스)을 받아 ONNX 로 만들어 active 에 적용.

    이미 active.onnx 가 있어도 **무조건 기본 모델로 교체**한다. names 반환.
    """
    from ultralytics import YOLO
    os.makedirs(MODELS_DIR, exist_ok=True)
    model = YOLO("yolov5su.pt")
    onnx_path = str(model.export(format="onnx", imgsz=EXPORT_IMGSZ, opset=12))
    shutil.copy(onnx_path, BASE_ONNX)
    shutil.copy(onnx_path, ACTIVE_ONNX)
    names = _names_list(model)
    set_active_classes(names)
    set_active_name("yolov5su (기본 모델)")
    return names


def ensure_default_onnx() -> None:
    """active.onnx 가 없으면 기본 모델(yolov5su)을 받아 ONNX 로 만들어 적용."""
    if os.path.exists(ACTIVE_ONNX):
        return
    make_base_active()


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "base":
        names = make_base_active()
        print(f"[export] 기본 모델(yolov5su) 적용 완료, 클래스 {len(names)}개")
    elif arg:
        names = apply_pt_as_active(arg)
        print(f"[export] active.onnx 적용 완료, 클래스 {len(names)}개")
    else:
        ensure_default_onnx()
        print("[export] 기본 ONNX 준비 완료")
