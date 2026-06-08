# coding: utf-8
"""
mp3_library.py
==============
assets/mp3/ 폴더의 mp3 파일을 스캔하고 메타정보(제목/아티스트/길이)를 읽는다.
드롭다운에 "제목 - 아티스트 (mm:ss)" 형태로 보여주기 위함.

mp3를 추가하려면 assets/mp3/ 폴더에 파일을 넣고 새로고침하면 된다.
"""

import os

from paths import MP3_DIR

try:
    from mutagen import File as MutagenFile
    from mutagen.easyid3 import EasyID3
    _HAS_MUTAGEN = True
except Exception:
    _HAS_MUTAGEN = False


def _fmt_dur(seconds: float) -> str:
    try:
        s = int(round(seconds))
        return f"{s // 60}:{s % 60:02d}"
    except Exception:
        return "?:??"


def read_meta(path: str) -> dict:
    """{title, artist, duration(sec)} 반환. 실패해도 파일명으로 대체."""
    stem = os.path.splitext(os.path.basename(path))[0]
    info = {"title": stem, "artist": "", "duration": 0.0}
    if not _HAS_MUTAGEN:
        return info
    try:
        easy = EasyID3(path)
        info["title"] = (easy.get("title") or [stem])[0]
        info["artist"] = (easy.get("artist") or [""])[0]
    except Exception:
        pass
    try:
        mf = MutagenFile(path)
        if mf is not None and mf.info is not None:
            info["duration"] = float(getattr(mf.info, "length", 0.0))
    except Exception:
        pass
    return info


def label_for(path: str) -> str:
    m = read_meta(path)
    artist = f" - {m['artist']}" if m["artist"] else ""
    dur = f" ({_fmt_dur(m['duration'])})" if m["duration"] else ""
    return f"{m['title']}{artist}{dur}"


def list_mp3() -> list:
    """[(path, label), ...] — assets/mp3 의 mp3 목록(메타 라벨 포함)."""
    os.makedirs(MP3_DIR, exist_ok=True)
    out = []
    for name in sorted(os.listdir(MP3_DIR)):
        if name.lower().endswith(".mp3"):
            path = os.path.join(MP3_DIR, name)
            out.append((path, label_for(path)))
    return out
