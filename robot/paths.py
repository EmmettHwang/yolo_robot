# coding: utf-8
"""
paths.py
========
프로젝트 전역 경로 상수. 모든 모듈은 여기서 경로를 가져온다.

이 파일은 robot/ 폴더 안에 있고, 프로젝트 루트는 그 부모 폴더다.
(main.py 만 루트에 있고 나머지 .py 는 robot/ 안에 있다.)
"""

import os

# 이 파일(robot/paths.py)의 부모의 부모 = 프로젝트 루트
ROBOT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(ROBOT_DIR)

# 설정 / 데이터
CONFIG_INI = os.path.join(BASE, "config.ini")
DATA_DIR = os.path.join(BASE, "data")
OBJECT_ACTIONS_JSON = os.path.join(DATA_DIR, "object_actions.json")
MOTION_GRID_JSON = os.path.join(DATA_DIR, "motion_grid.json")

# 학습 / 모델
DATASET = os.path.join(BASE, "dataset")
IMG_DIR = os.path.join(DATASET, "images", "train")
LBL_DIR = os.path.join(DATASET, "labels", "train")
CLASSES_TXT = os.path.join(DATASET, "classes.txt")
DATA_YAML = os.path.join(DATASET, "data.yaml")
MODELS_DIR = os.path.join(BASE, "model")          # 사용자 지정: ./model
ACTIVE_MODEL = os.path.join(MODELS_DIR, "active.pt")
ACTIVE_NAME = os.path.join(MODELS_DIR, "active.name")   # active 의 원본 모델 이름
BASE_WEIGHTS = os.path.join(MODELS_DIR, "yolov5su.pt")  # ultralytics 기본 가중치(model/)
# ── gradio 브랜치(v4.0~): 런타임 추론은 OpenCV DNN(ONNX) ──
ACTIVE_ONNX = os.path.join(MODELS_DIR, "active.onnx")        # 인식에 쓰는 ONNX
ACTIVE_CLASSES = os.path.join(MODELS_DIR, "active.names")    # 클래스명(한 줄당 1개)
BASE_ONNX = os.path.join(MODELS_DIR, "yolov5su.onnx")        # 기본 ONNX
YOLO_DIR = os.path.join(BASE, "yolov5")
RUNS_DIR = os.path.join(BASE, "runs")
BEST_WEIGHTS = os.path.join(RUNS_DIR, "custom", "weights", "best.pt")

# 리소스
ASSETS = os.path.join(BASE, "assets")
SOUNDS_DIR = os.path.join(ASSETS, "sounds")   # (예약) 효과음 파일용
MP3_DIR = os.path.join(ASSETS, "mp3")
# 이미지 → ./image, PDF/프로토콜 → ./protocol
IMAGE_DIR = os.path.join(BASE, "image")
PROTOCOL_DIR = os.path.join(BASE, "protocol")
LOGO_PATH = os.path.join(IMAGE_DIR, "logo.png")
MOTORMAP_PATH = os.path.join(IMAGE_DIR, "motorMap.png")
MANUAL_PDF = os.path.join(PROTOCOL_DIR, "라인코어엠매뉴얼.pdf")

# 폰트 (한글)
FONT_PATH = "C:/Windows/Fonts/malgun.ttf"


def ensure_dirs() -> None:
    """필요한 디렉터리를 만들어 둔다."""
    for d in (DATA_DIR, SOUNDS_DIR, MP3_DIR, MODELS_DIR):
        os.makedirs(d, exist_ok=True)


def set_active_name(name: str) -> None:
    """active.pt 로 적용한 원본 모델 이름을 기록."""
    try:
        os.makedirs(MODELS_DIR, exist_ok=True)
        with open(ACTIVE_NAME, "w", encoding="utf-8") as f:
            f.write(name or "")
    except Exception:
        pass


def get_active_name() -> str:
    """active 모델의 원본 이름(없으면 None)."""
    try:
        with open(ACTIVE_NAME, encoding="utf-8") as f:
            return f.read().strip() or None
    except Exception:
        return None


def set_active_classes(names) -> None:
    """active.onnx 의 클래스명 목록을 기록(한 줄당 1개)."""
    try:
        os.makedirs(MODELS_DIR, exist_ok=True)
        with open(ACTIVE_CLASSES, "w", encoding="utf-8") as f:
            f.write("\n".join(names))
    except Exception:
        pass


def get_active_classes():
    """active.onnx 의 클래스명 목록(없으면 None)."""
    try:
        with open(ACTIVE_CLASSES, encoding="utf-8") as f:
            out = [ln.strip() for ln in f if ln.strip()]
        return out or None
    except Exception:
        return None
