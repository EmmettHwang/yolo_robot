# coding: utf-8
"""
voice_chat.py
=============
음성 대화: 마이크(STT) → 로컬 LLM(Ollama) → 스피커(TTS).

- LLM: 로컬 Ollama(http://127.0.0.1:11434). API 키 불필요, 무료.
- STT: SpeechRecognition + Google Web Speech(ko-KR). 키 불필요(인터넷 필요).
- 녹음: sounddevice(이미 설치). 출력: pyttsx3(오프라인 TTS).

설정(data/voice_chat.json): {"model": "...", "system": "...", "listen_sec": 5}
인식 반응에서 '음성 대화' 모션(코드 1003)을 고르면 run_chat() 1회 실행.
"""

import os
import json
import urllib.request

from paths import DATA_DIR

VOICE_CFG = os.path.join(DATA_DIR, "voice_chat.json")
OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_SYSTEM = ("너는 휴머노이드 로봇이야. 한국어로 짧고 친근하게, "
                  "한두 문장으로 대답해.")


# ---------- 설정 ----------
def load_cfg() -> dict:
    cfg = {"model": "", "system": DEFAULT_SYSTEM, "listen_sec": 5}
    try:
        with open(VOICE_CFG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_cfg(model=None, system=None, listen_sec=None) -> None:
    cfg = load_cfg()
    if model is not None:
        cfg["model"] = model
    if system is not None:
        cfg["system"] = system
    if listen_sec is not None:
        cfg["listen_sec"] = listen_sec
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(VOICE_CFG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------- Ollama ----------
def list_models() -> list:
    """설치된 Ollama 모델 이름 목록(서버 미실행/미설치면 빈 리스트)."""
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def ask_ollama(model: str, system: str, user: str, timeout=60) -> str:
    body = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data.get("message", {}) or {}).get("content", "").strip()


# ---------- 녹음 / STT ----------
def _record(seconds: float, rate: int = 16000):
    import sounddevice as sd
    rec = sd.rec(int(seconds * rate), samplerate=rate, channels=1,
                 dtype="int16")
    sd.wait()
    return rec.tobytes(), rate


def _stt(raw: bytes, rate: int) -> str:
    import speech_recognition as sr
    r = sr.Recognizer()
    audio = sr.AudioData(raw, rate, 2)        # 2바이트(int16) 모노
    try:
        return r.recognize_google(audio, language="ko-KR")
    except Exception:
        return ""


# ---------- TTS ----------
def _speak(text: str) -> None:
    if not text:
        return
    try:
        import sound
        sound.speak_blocking(text)        # Windows SAPI(안정) + pyttsx3 폴백
    except Exception:
        pass


# ---------- 한 번의 대화 ----------
def run_chat(status=None) -> None:
    """마이크로 듣고 → Ollama 답변 → 말하기. status(msg) 콜백으로 진행 표시."""
    def say_status(m):
        if status:
            try:
                status(m)
            except Exception:
                pass

    cfg = load_cfg()
    model = (cfg.get("model") or "").strip()
    if not model:
        say_status("음성대화 모델이 설정되지 않았습니다(설정에서 선택)")
        _speak("음성 대화 모델이 설정되지 않았어요.")
        return
    if not list_models():
        say_status("Ollama 서버가 꺼져 있습니다(ollama serve 필요)")
        _speak("로컬 LLM 서버가 꺼져 있어요.")
        return
    try:
        say_status("🎤 듣는 중...")
        raw, rate = _record(float(cfg.get("listen_sec", 5)))
        text = _stt(raw, rate)
        if not text:
            say_status("못 알아들었습니다")
            _speak("잘 못 들었어요. 다시 말해줄래요?")
            return
        say_status(f"🗣 \"{text}\" → 생각 중...")
        reply = ask_ollama(model, cfg.get("system", DEFAULT_SYSTEM), text)
        say_status(f"🤖 {reply}")
        _speak(reply)
    except Exception as e:
        say_status(f"음성대화 오류: {e}")
