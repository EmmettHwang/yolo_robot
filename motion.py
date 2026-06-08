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
)


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
        self._disconnected = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

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
        """진행 중인 시퀀스/대기 단발을 모두 비우고 모션 0(중단)을 전송."""
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
        else:
            ok = True
        if not ok:
            self._disconnected = True
            if self.on_disconnect:
                try:
                    self.on_disconnect()
                except Exception:
                    pass
        return ok

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
