# coding: utf-8
"""
motion.py
=========
모션 엔진. 로봇에 모션을 보내는 백그라운드 러너.

- send_once(n)        : 단발 모션 1회
- start_sequence(seq) : 시퀀스를 500ms 간격으로 '반복' (조이스틱 전/후진 등)
- stop_sequence()     : 반복 중지 + 기본자세 복귀
- forward()/backward(): 모션테이블 기반 전진/후진 반복

기존 robot_controller 의 HumanoidRobot / MotionSequencer 도 재노출한다.
"""

import time
import threading

from robot_controller import HumanoidRobot, MotionSequencer  # noqa: F401  (재노출)
from motion_table import (
    FORWARD_SEQUENCE, BACKWARD_SEQUENCE, SEQUENCE_DELAY_MS, READY_MOTION,
    SAFE_SIT, SAFE_UP, POWER_OFF_HOLD,
)
from motor_map import ALL_IDS

# 인식 반응 LED 연출 기본값
REACTION_COLOR = (0, 150, 255)      # 페이드 색 (시안)
ACTION_LED_HOLD = 1.6               # 모션 실행 후 페이드아웃까지 대기(초)


class MotionRunner:
    """모션 전송을 백그라운드 스레드에서 처리. UI 블로킹 방지 + 연속 시퀀스 지원."""

    def __init__(self, robot, on_disconnect=None):
        self.robot = robot
        self.on_disconnect = on_disconnect      # 전송 실패 시 호출되는 콜백
        self._lock = threading.Lock()
        self._seq = None                         # 반복 중인 시퀀스(list) or None
        self._seq_delay = SEQUENCE_DELAY_MS / 1000.0
        self._oneshots = []                      # 단발 모션 큐
        self._stop = threading.Event()
        self._cancel_action = threading.Event()  # 동작 중지 버튼 → 반응 즉시 종료
        self._busy = False                       # 반응(효과) 진행 중
        self._disconnected = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    @property
    def busy(self) -> bool:
        """LED 반응/모션 연출이 진행 중인지(새 트리거를 막기 위함)."""
        return self._busy

    # ---------- 외부 API ----------
    def _enqueue(self, task) -> None:
        with self._lock:
            self._oneshots.append(task)

    def send_once(self, motion: int) -> None:
        self._enqueue(("motion", int(motion)))

    def led(self, leds) -> None:
        """LED 제어 큐잉. leds = [(id, r, g, b), ...]"""
        self._enqueue(("led", list(leds)))

    def position(self, positions) -> None:
        """포지션 제어 큐잉. positions = [(id, pos, torque), ...]"""
        self._enqueue(("pos", list(positions)))

    def power(self, on: bool) -> None:
        self._enqueue(("pwr", bool(on)))

    def safe_power(self, on: bool) -> None:
        """안전 전원: 끄기=Safe Sit→7초→OFF, 켜기=ON→Safe Up."""
        self._enqueue(("safepwr", bool(on)))

    def action_with_led(self, motion: int, color=None, hold=None) -> None:
        """인식 반응: LED 페이드인→반짝→모션→페이드아웃→반짝."""
        self._enqueue(("effect", {
            "motion": int(motion),
            "color": color or REACTION_COLOR,
            "hold": ACTION_LED_HOLD if hold is None else hold,
        }))

    def start_sequence(self, seq, delay_ms: int = None) -> None:
        with self._lock:
            self._seq = list(seq)
            if delay_ms is not None:
                self._seq_delay = delay_ms / 1000.0

    def stop_sequence(self, return_ready: bool = True) -> None:
        with self._lock:
            self._seq = None
        if return_ready:
            self.send_once(READY_MOTION)

    def stop_all(self) -> None:
        """진행 중인 시퀀스/반응/대기 단발을 모두 비우고 모션 0(중단)을 전송."""
        self._cancel_action.set()           # 진행 중인 LED 반응 즉시 종료
        with self._lock:
            self._seq = None
            self._oneshots.clear()
        self.send_once(0)        # 모션 0 = 중단

    def forward(self) -> None:
        self.start_sequence(FORWARD_SEQUENCE)

    def backward(self) -> None:
        self.start_sequence(BACKWARD_SEQUENCE)

    @property
    def disconnected(self) -> bool:
        return self._disconnected

    # ---------- 내부 ----------
    def _do(self, task) -> bool:
        """task = (kind, payload). 모든 로봇 전송을 이 스레드에서 직렬화."""
        kind, payload = task
        r = self.robot
        if r is None:
            ok = False
        elif kind == "motion":
            ok = bool(r.send_motion(payload))
        elif kind == "led":
            ok = bool(r.send_leds(payload))
        elif kind == "pos":
            ok = bool(r.send_positions(payload))
        elif kind == "pwr":
            ok = bool(r.power(payload))
        elif kind == "effect":
            self._run_effect(payload)
            ok = True
        elif kind == "safepwr":
            self._run_safe_power(payload)
            ok = True
        else:
            ok = True
        if not ok:
            self._mark_disc()
        return ok

    def _mark_disc(self) -> None:
        self._disconnected = True
        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception:
                pass

    def _leds(self, leds) -> bool:
        ok = bool(self.robot.send_leds(leds)) if self.robot else False
        if not ok:
            self._mark_disc()
        return ok

    def _run_safe_power(self, on: bool) -> None:
        """켜기: 전원 ON → Safe Up / 끄기: Safe Sit → 7초 대기 → 전원 OFF."""
        if not self.robot:
            self._mark_disc()
            return
        if on:
            if not self.robot.power(True):
                self._mark_disc(); return
            if self._stop.wait(0.3):
                return
            if not self.robot.send_motion(SAFE_UP):     # 61 일어서기
                self._mark_disc()
        else:
            if not self.robot.send_motion(SAFE_SIT):    # 60 앉기
                self._mark_disc(); return
            if self._stop.wait(POWER_OFF_HOLD):         # 7초(중지 가능)
                return
            if not self.robot.power(False):
                self._mark_disc()

    def _wait(self, secs: float) -> bool:
        """secs 동안 대기. 종료(_stop)나 동작중지(_cancel_action) 시 True 반환(중단)."""
        step = 0.05
        left = secs
        while left > 0:
            w = min(step, left)
            if self._stop.wait(w):
                return True
            if self._cancel_action.is_set():
                return True
            left -= w
        return False

    def _run_effect(self, payload) -> None:
        """LED 페이드인 → 반짝 → 모션 → (hold 만큼 지속) → 페이드아웃 → 반짝 → 끄기.

        hold 가 mp3 길이면 그 시간 동안 동작이 유지된다. 동작 중지 버튼을 누르면
        (_cancel_action) 즉시 종료한다.
        """
        self._busy = True
        self._cancel_action.clear()
        ids = ALL_IDS
        r, g, b = payload["color"]
        motion = payload["motion"]
        hold = payload["hold"]
        STEP = 8
        try:
            # 페이드 인
            for k in range(1, STEP + 1):
                f = k / STEP
                if not self._leds([(i, int(r * f), int(g * f), int(b * f))
                                   for i in ids]):
                    return
                if self._wait(0.045):
                    return
            # 반짝(흰색) 후 동작
            self._leds([(i, 255, 255, 255) for i in ids])
            if self._wait(0.12):
                return
            self._leds([(i, r, g, b) for i in ids])
            if self._wait(0.05):
                return
            if self.robot:
                self.robot.send_motion(motion)
            # 동작 유지 (mp3 길이만큼; 중지 전까지 끊지 않음)
            if self._wait(hold):
                return
            # 페이드 아웃
            for k in range(STEP, -1, -1):
                f = k / STEP
                if not self._leds([(i, int(r * f), int(g * f), int(b * f))
                                   for i in ids]):
                    return
                if self._wait(0.045):
                    return
            # 마지막 반짝
            self._leds([(i, 255, 255, 255) for i in ids])
            self._wait(0.12)
        finally:
            # 끝/중지 시 LED 끄기
            try:
                if self.robot:
                    self.robot.send_leds([(i, 0, 0, 0) for i in ids])
            except Exception:
                pass
            self._busy = False

    def _send(self, motion: int) -> bool:
        return self._do(("motion", motion))

    def _loop(self) -> None:
        while not self._stop.is_set():
            task = None
            with self._lock:
                if self._oneshots:
                    task = self._oneshots.pop(0)
                seq = list(self._seq) if self._seq else None

            if task is not None:
                self._do(task)
                self._stop.wait(0.05)
                continue

            if seq:
                for m in seq:
                    if self._stop.is_set():
                        break
                    with self._lock:
                        # 시퀀스가 바뀌었거나 단발이 들어오면 즉시 양보
                        if self._seq is None or self._oneshots:
                            break
                    self._send(m)
                    if self._stop.wait(self._seq_delay):
                        break
            else:
                self._stop.wait(0.03)

    def close(self) -> None:
        self._stop.set()
        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass
