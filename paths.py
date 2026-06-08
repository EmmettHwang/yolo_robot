# coding: utf-8
"""
paths.py
========
프로젝트 전역 경로 상수. 모든 모듈은 여기서 경로를 가져온다.
"""

import os

BASE = os.path.dirname(os.path.abspath(__file__))

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
MODELS_DIR = os.path.join(BASE, "models")
ACTIVE_MODEL = os.path.join(MODELS_DIR, "active.pt")
YOLO_DIR = os.path.join(BASE, "yolov5")
BASE_WEIGHTS = os.path.join(BASE, "yolov5s.pt")
RUNS_DIR = os.path.join(BASE, "runs")
BEST_WEIGHTS = os.path.join(RUNS_DIR, "custom", "weights", "best.pt")

# 리소스
ASSETS = os.path.join(BASE, "assets")
SOUNDS_DIR = os.path.join(ASSETS, "sounds")
MP3_DIR = os.path.join(ASSETS, "mp3")        # 동작 사운드용 mp3 보관 폴더

# 폰트 (한글)
FONT_PATH = "C:/Windows/Fonts/malgun.ttf"


def ensure_dirs() -> None:
    """필요한 디렉터리를 만들어 둔다."""
    for d in (DATA_DIR, SOUNDS_DIR, MP3_DIR):
        os.makedirs(d, exist_ok=True)
