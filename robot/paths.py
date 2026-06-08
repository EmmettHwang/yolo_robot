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
BASE_WEIGHTS = os.path.join(MODELS_DIR, "yolov5su.pt")  # ultralytics 기본 가중치(model/)
YOLO_DIR = os.path.join(BASE, "yolov5")
RUNS_DIR = os.path.join(BASE, "runs")
BEST_WEIGHTS = os.path.join(RUNS_DIR, "custom", "weights", "best.pt")

# 리소스
ASSETS = os.path.join(BASE, "assets")
SOUNDS_DIR = os.path.join(ASSETS, "sounds")
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
