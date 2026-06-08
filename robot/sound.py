# coding: utf-8
"""
sound.py
========
동작 시 사운드 출력. 세 가지 종류:
  - none : 음성 없음
  - mp3  : mp3 파일 재생 (pygame.mixer)
  - tts  : 텍스트 음성 변환 (pyttsx3, 오프라인 Windows SAPI)

모든 재생은 비동기(별도 스레드)라 UI/제어 루프를 막지 않는다.
"""

import os
import threading

from paths import SOUNDS_DIR

try:
    import pygame
    _HAS_PYGAME = True
except Exception:
    _HAS_PYGAME = False

try:
    import pyttsx3
    _HAS_TTS = True
except Exception:
    _HAS_TTS = False


NONE = "none"
MP3 = "mp3"
TTS = "tts"

# UI 콤보박스용 (값, 표시이름)
KINDS = [(NONE, "음성 없음"), (MP3, "MP3 재생"), (TTS, "TTS(읽기)")]


class SoundPlayer:
    def __init__(self):
        self._mixer_ready = False
        self._lock = threading.Lock()
        self._fx_cache = {}        # 효과음 Sound 캐시

    def _ensure_mixer(self) -> bool:
        if self._mixer_ready or not _HAS_PYGAME:
            return self._mixer_ready
        try:
            pygame.mixer.init()
            self._mixer_ready = True
        except Exception:
            self._mixer_ready = False
        return self._mixer_ready

    def play(self, kind: str, value: str = "") -> None:
        """kind=mp3 → value는 파일경로 / kind=tts → value는 읽을 텍스트."""
        if kind == MP3 and value:
            threading.Thread(target=self._play_mp3, args=(value,),
                             daemon=True).start()
        elif kind == TTS and value:
            threading.Thread(target=self._speak, args=(value,),
                             daemon=True).start()
        # none → 아무것도 안 함

    def _play_mp3(self, path: str) -> None:
        if not self._ensure_mixer():
            print("[sound] pygame 미설치/초기화 실패 — mp3 재생 불가")
            return
        try:
            with self._lock:
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
        except Exception as e:
            print(f"[sound] mp3 재생 실패: {e}")

    def _speak(self, text: str) -> None:
        if not _HAS_TTS:
            print("[sound] pyttsx3 미설치 — TTS 불가")
            return
        try:
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"[sound] TTS 실패: {e}")

    def stop(self) -> None:
        if self._mixer_ready:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    # ---------- 효과음 (assets/sounds/<name>.wav) ----------
    def play_effect(self, name: str) -> None:
        """캡처/시작/종료 등 짧은 효과음 재생. (mp3 음악과 별도 채널)"""
        if not name:
            return
        threading.Thread(target=self._play_wav, args=(name,),
                         daemon=True).start()

    def _play_wav(self, name: str) -> None:
        if not self._ensure_mixer():
            return
        path = os.path.join(SOUNDS_DIR, name + ".wav")
        if not os.path.exists(path):
            return
        try:
            snd = self._fx_cache.get(name)
            if snd is None:
                snd = pygame.mixer.Sound(path)
                self._fx_cache[name] = snd
            snd.play()
        except Exception as e:
            print(f"[sound] 효과음 실패({name}): {e}")


# 공용 인스턴스
player = SoundPlayer()

# 효과음 이름 상수
FX_CAPTURE = "capture"
FX_START = "start"
FX_END = "end"
FX_DETECT = "detect"
FX_STOP = "stop"            # 동작 정지 "딱!"
FX_POWER_ON = "power_on"    # 전원 ON
FX_POWER_OFF = "power_off"  # 전원 OFF
