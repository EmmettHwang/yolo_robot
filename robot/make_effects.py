# coding: utf-8
"""
make_effects.py
===============
효과음(.wav) 합성기 — 외부 음원/의존성 없이 numpy 로 생성한다.

생성물 (assets/sounds/):
  - stop.wav       : 동작 정지 "딱!" + 순종하듯 전원 내려가는 소리(세탁기 OFF 느낌)
  - power_on.wav   : 전원 ON — 상승 부팅음 + 확인 차임
  - power_off.wav  : 전원 OFF — 모터 회전이 잦아들며 꺼지는 소리

실행:  python make_effects.py
"""

import os
import wave
import numpy as np

from paths import SOUNDS_DIR

SR = 44100


def _env_exp(n, tau=0.25):
    """지수 감쇠 엔벨로프(0..n)."""
    t = np.linspace(0, 1, n, endpoint=False)
    return np.exp(-t / tau)


def _fade(sig, ms=8):
    """클릭 잡음 방지용 양끝 페이드."""
    f = max(1, int(SR * ms / 1000))
    if len(sig) > 2 * f:
        sig[:f] *= np.linspace(0, 1, f)
        sig[-f:] *= np.linspace(1, 0, f)
    return sig


def _sweep(f0, f1, dur, kind="exp"):
    """f0→f1 주파수 스윕 사인파."""
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    if kind == "exp":
        f = f0 * (f1 / f0) ** (t / dur)
    else:
        f = np.linspace(f0, f1, n)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(phase)


def _norm(sig, peak=0.9):
    m = np.max(np.abs(sig)) or 1.0
    return sig / m * peak


def _write(name, sig):
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    sig = _norm(np.asarray(sig, dtype=np.float64))
    pcm = (sig * 32767).astype("<i2")
    path = os.path.join(SOUNDS_DIR, name + ".wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"  [ok] {path}  ({len(sig)/SR:.2f}s)")


# ============================================================
# 1) 정지 "딱!" — 순종하듯 탁 멈추는 소리
# ============================================================
def make_stop():
    # (a) 짧고 단단한 "딱" 클릭 (높은 트랜지언트 + 빠른 감쇠)
    nclk = int(SR * 0.05)
    clk = np.random.default_rng(7).standard_normal(nclk)
    clk *= _env_exp(nclk, tau=0.06)
    clk += 0.6 * np.sin(2 * np.pi * 1600 *
                        np.linspace(0, 0.05, nclk)) * _env_exp(nclk, 0.05)

    # (b) 전원 내려가듯 빠르게 떨어지는 피치 (520→110Hz)
    body = _sweep(520, 110, 0.38, "exp")
    body += 0.35 * _sweep(1040, 220, 0.38, "exp")   # 옥타브 배음(기계적)
    body *= _env_exp(len(body), tau=0.16)

    # (c) 마지막 묵직한 "쿵" (저음 안착)
    nth = int(SR * 0.12)
    thunk = np.sin(2 * np.pi * 90 * np.linspace(0, 0.12, nth))
    thunk *= _env_exp(nth, tau=0.10)

    sig = np.concatenate([clk, body, 0.7 * thunk])
    return _fade(sig)


# ============================================================
# 2) 전원 ON — 상승 부팅음 + 확인 차임
# ============================================================
def make_power_on():
    # (a) 저음에서 솟구치는 부팅 스윕 (110→760Hz)
    boot = _sweep(110, 760, 0.42, "exp")
    boot += 0.3 * _sweep(220, 1520, 0.42, "exp")
    boot *= np.clip(np.linspace(0, 1.2, len(boot)), 0, 1)   # 점점 커짐
    boot *= 0.9

    gap = np.zeros(int(SR * 0.04))

    # (b) 확인 차임 두 음 (E6→A6, 밝고 경쾌)
    def note(freq, dur):
        n = int(SR * dur)
        s = np.sin(2 * np.pi * freq * np.linspace(0, dur, n))
        s += 0.25 * np.sin(2 * np.pi * 2 * freq * np.linspace(0, dur, n))
        return s * _env_exp(n, tau=0.22)

    chime = np.concatenate([note(1318, 0.12), note(1760, 0.20)])
    sig = np.concatenate([boot, gap, 0.8 * chime])
    return _fade(sig)


# ============================================================
# 3) 전원 OFF — 회전이 잦아들며 꺼지는 소리(세탁기 OFF)
# ============================================================
def make_power_off():
    dur = 0.85
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    # 천천히 느려지며 내려가는 피치 (430→70Hz)
    f = 430 * (70 / 430) ** (t / dur)
    phase = 2 * np.pi * np.cumsum(f) / SR
    motor = np.sin(phase) + 0.3 * np.sin(2 * phase)
    # 회전이 느려지는 듯한 비브라토(점점 느려짐)
    vib = 1 + 0.06 * np.sin(2 * np.pi * (8 * (1 - t / dur)) * t)
    motor *= vib
    motor *= np.linspace(1.0, 0.0, n) ** 1.4          # 서서히 사그라듦

    # 마지막 딸깍(릴레이 OFF)
    nclk = int(SR * 0.04)
    clk = np.random.default_rng(3).standard_normal(nclk) * _env_exp(nclk, 0.05)

    sig = np.concatenate([motor, 0.5 * clk])
    return _fade(sig)


# ============================================================
# 4) 다양한 로봇 보이스 (random 사운드용) — voice_01 ~ voice_08
# ============================================================
def _note(freq, dur, harm=0.3, tau=0.18, square=False):
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    s = np.sin(2 * np.pi * freq * t)
    if square:
        s = np.sign(s) * 0.7
    s += harm * np.sin(2 * np.pi * 2 * freq * t)
    return s * _env_exp(n, tau)


def _gap(ms):
    return np.zeros(int(SR * ms / 1000))


def make_voices():
    rng = np.random.default_rng(42)
    voices = {}

    # 01: 상승 3음 삐빅삐 (밝은 인사)
    voices["voice_01"] = np.concatenate([
        _note(523, 0.10), _gap(20), _note(784, 0.10), _gap(20),
        _note(1047, 0.16)])

    # 02: 하강 워블 (시무룩)
    s = _sweep(900, 300, 0.5) * (1 + 0.3 * np.sin(2 * np.pi * 18 *
              np.linspace(0, 0.5, int(SR * 0.5))))
    voices["voice_02"] = s * _env_exp(len(s), 0.3)

    # 03: R2D2풍 랜덤 아르페지오 (수다)
    seq = []
    for _ in range(7):
        f = float(rng.integers(400, 1500))
        seq.append(_note(f, 0.07, harm=0.4, tau=0.08, square=True))
        seq.append(_gap(15))
    voices["voice_03"] = np.concatenate(seq)

    # 04: 두 음 '부-입?' (질문하듯 끝 올림)
    voices["voice_04"] = np.concatenate([
        _note(330, 0.16), _gap(30),
        (_sweep(500, 900, 0.22) * _env_exp(int(SR * 0.22), 0.18))])

    # 05: 비브라토 치프 (귀엽게)
    n = int(SR * 0.4); t = np.linspace(0, 0.4, n)
    f = 700 + 120 * np.sin(2 * np.pi * 12 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    voices["voice_05"] = np.sin(ph) * _env_exp(n, 0.25)

    # 06: 빠른 트리플 클릭 + 톤 (놀람)
    clk = []
    for _ in range(3):
        nc = int(SR * 0.03)
        clk.append(rng.standard_normal(nc) * _env_exp(nc, 0.04))
        clk.append(_gap(25))
    voices["voice_06"] = np.concatenate(clk + [_note(880, 0.14)])

    # 07: 와우(상승→하강) 스윕
    up = _sweep(300, 1100, 0.22); dn = _sweep(1100, 400, 0.22)
    s = np.concatenate([up, dn])
    voices["voice_07"] = s * _env_exp(len(s), 0.3)

    # 08: 통통 튀는 상승 글리산도
    seq = []
    base = 400
    for k in range(5):
        seq.append(_note(base * (1.18 ** k), 0.08, tau=0.07))
        seq.append(_gap(10))
    voices["voice_08"] = np.concatenate(seq)

    for name, sig in voices.items():
        _write(name, _fade(sig))


if __name__ == "__main__":
    print("[make_effects] 효과음 생성:")
    _write("stop", make_stop())
    _write("power_on", make_power_on())
    _write("power_off", make_power_off())
    print("[make_effects] 로봇 보이스(random용) 생성:")
    make_voices()
    print("[make_effects] 완료.")
