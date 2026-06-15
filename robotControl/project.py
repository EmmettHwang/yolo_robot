# coding: utf-8
"""
project.py
==========
인식및반응 설정을 **프로젝트 단위**로 저장/불러오기.

프로젝트 = projects/<이름>/ 폴더 1개. 그 안에 3가지 파일을 둔다:
  1) actions.json   — 액션스크립터 데이터(반응 매핑). 불러올 때 기준이 되는 원본.
  2) blocks.json    — 블록 코딩 내보내기(사람이 읽기 좋은 스텝 목록).
  3) program.py     — AI 생성 파이썬 코드.

actions.json 이 단일 진실원본(single source of truth)이고, blocks.json/program.py
는 그로부터 생성된 산출물이다. 불러오기는 actions.json 을 읽어 현재 설정에 적용한다.
"""

import os
import json

from paths import PROJECTS_DIR
import object_actions
import code_gen
from motion_table import motion_name, PWR_ON, PWR_OFF, VOICE_CHAT

ACTIONS_FILE = "actions.json"
BLOCKS_FILE = "blocks.json"
PROGRAM_FILE = "program.py"


def _safe_name(name: str) -> str:
    """폴더명에 못 쓰는 문자 제거."""
    bad = '<>:"/\\|?*'
    out = "".join(("_" if c in bad else c) for c in (name or "").strip())
    return out or "프로젝트"


def projects_root() -> str:
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    return PROJECTS_DIR


def list_projects():
    """저장된 프로젝트 이름 목록(actions.json 이 있는 폴더)."""
    root = projects_root()
    out = []
    try:
        for n in sorted(os.listdir(root)):
            p = os.path.join(root, n)
            if os.path.isdir(p) and os.path.exists(
                    os.path.join(p, ACTIONS_FILE)):
                out.append(n)
    except Exception:
        pass
    return out


def _motion_text(m):
    if m is None:
        return ""
    if m == PWR_ON:
        return "전원 켜기"
    if m == PWR_OFF:
        return "전원 끄기"
    if m == VOICE_CHAT:
        return "음성 대화"
    return motion_name(int(m))


def _blocks_export(mapping: dict) -> dict:
    """블록 코딩 표현(스텝을 읽기 좋게 펼친 형태)."""
    out = {}
    for label, act in mapping.items():
        rows = []
        for i, s in enumerate(object_actions.steps_of(act)):
            rows.append({
                "order": i + 1,
                "motion": s.get("motion"),
                "motion_name": _motion_text(s.get("motion")),
                "sound_kind": s.get("sound_kind", "none"),
                "sound_value": s.get("sound_value", ""),
                "duration": s.get("duration"),
                "repeat": int(s.get("repeat", 1) or 1),
                "cond": s.get("cond", "always"),
                "cond_label": object_actions.COND_KEY2LABEL.get(
                    s.get("cond", "always"), "항상"),
            })
        out[label] = rows
    return out


def project_dir(name: str) -> str:
    return os.path.join(projects_root(), _safe_name(name))


def save_project(name: str, mapping: dict = None) -> str:
    """프로젝트 폴더를 만들고 3가지 파일을 저장. 폴더 경로 반환."""
    mapping = mapping if mapping is not None else object_actions.load_actions()
    folder = project_dir(name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, ACTIONS_FILE), "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    with open(os.path.join(folder, BLOCKS_FILE), "w", encoding="utf-8") as f:
        json.dump(_blocks_export(mapping), f, ensure_ascii=False, indent=2)
    with open(os.path.join(folder, PROGRAM_FILE), "w", encoding="utf-8") as f:
        f.write(code_gen.generate_python(mapping))
    return folder


def load_project(folder: str) -> dict:
    """폴더(또는 프로젝트 이름)에서 actions.json 을 읽어 매핑 반환.

    blocks.json 만 있고 actions.json 이 없으면 blocks 로부터 복원한다.
    """
    if not os.path.isdir(folder):
        folder = project_dir(folder)
    apath = os.path.join(folder, ACTIONS_FILE)
    if os.path.exists(apath):
        with open(apath, encoding="utf-8") as f:
            data = json.load(f)
        return {k: object_actions._normalize(v) for k, v in data.items()}
    # 폴백: blocks.json 으로 복원
    bpath = os.path.join(folder, BLOCKS_FILE)
    if os.path.exists(bpath):
        with open(bpath, encoding="utf-8") as f:
            blocks = json.load(f)
        mapping = {}
        for label, rows in blocks.items():
            steps = [{"motion": r.get("motion"),
                      "sound_kind": r.get("sound_kind", "none"),
                      "sound_value": r.get("sound_value", ""),
                      "duration": r.get("duration"),
                      "repeat": int(r.get("repeat", 1) or 1),
                      "cond": r.get("cond", "always")} for r in rows]
            mapping[label] = object_actions._normalize({"steps": steps})
        return mapping
    raise FileNotFoundError(f"{folder} 에 actions.json/blocks.json 이 없습니다.")


def apply_mapping(mapping: dict) -> None:
    """불러온 매핑을 현재 작업본(object_actions JSON)에 적용."""
    object_actions.save_actions(mapping)
