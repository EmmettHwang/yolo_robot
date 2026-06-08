# coding: utf-8
"""
joystick.py
===========
8방향 조이스틱 위젯 (tkinter Canvas).

- 누른 채 방향으로 끌면 방향(N/NE/E/SE/S/SW/W/NW)을 보고.
- 방향이 바뀔 때 on_change(direction) 호출. (가운데/놓음 = None)
- 소비자(인식 뷰)가 방향 → 모션으로 매핑한다. (위젯은 방향만 안다)
"""

import math
import tkinter as tk

# 각도(0°=동, 반시계) → 8방향
DIRS_8 = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]

DIR_LABEL = {
    "N": "전진", "S": "후진", "W": "좌", "E": "우",
    "NW": "전진좌", "NE": "전진우", "SW": "좌회전", "SE": "우회전",
}


class Joystick(tk.Frame):
    def __init__(self, master, size=200, on_change=None, **kw):
        super().__init__(master, **kw)
        self.size = size
        self.r = size // 2
        self.knob_r = max(16, size // 6)
        self.on_change = on_change
        self.cur = None
        self.enabled = True

        self.cv = tk.Canvas(self, width=size, height=size, bg="#222222",
                            highlightthickness=0, cursor="hand2")
        self.cv.pack()
        self._draw_base()
        self.knob = self.cv.create_oval(0, 0, 0, 0, fill="#1565c0",
                                        outline="#90caf9", width=2)
        self._reset_knob()

        self.cv.bind("<Button-1>", self._on_drag)
        self.cv.bind("<B1-Motion>", self._on_drag)
        self.cv.bind("<ButtonRelease-1>", self._on_release)

    # ---------- 그리기 ----------
    def _draw_base(self) -> None:
        c = self.r
        self.cv.create_oval(6, 6, self.size - 6, self.size - 6,
                            outline="#555", width=2, fill="#2b2b2b")
        self.cv.create_line(c, 12, c, self.size - 12, fill="#3a3a3a")
        self.cv.create_line(12, c, self.size - 12, c, fill="#3a3a3a")
        # 방향 라벨
        pos = {
            "N": (c, 16), "S": (c, self.size - 16),
            "W": (16, c), "E": (self.size - 16, c),
            "NW": (28, 28), "NE": (self.size - 28, 28),
            "SW": (28, self.size - 28), "SE": (self.size - 28, self.size - 28),
        }
        for d, (x, y) in pos.items():
            self.cv.create_text(x, y, text=DIR_LABEL[d], fill="#9e9e9e",
                                font=("Malgun Gothic", 8))

    def _center(self):
        return self.r, self.r

    def _reset_knob(self) -> None:
        cx, cy = self._center()
        self.cv.coords(self.knob, cx - self.knob_r, cy - self.knob_r,
                       cx + self.knob_r, cy + self.knob_r)
        self.cv.itemconfig(self.knob, fill="#1565c0")

    # ---------- 입력 ----------
    def _direction(self, x, y):
        cx, cy = self._center()
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy)
        if dist < self.r * 0.28:        # 데드존
            return None, dx, dy, dist
        ang = math.degrees(math.atan2(-dy, dx)) % 360
        idx = int((ang + 22.5) // 45) % 8
        return DIRS_8[idx], dx, dy, dist

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.cv.config(cursor="hand2" if enabled else "arrow")
        self.cv.itemconfig(self.knob,
                           fill="#1565c0" if enabled else "#555555")
        if not enabled and self.cur is not None:
            self.cur = None
            self._reset_knob()
            if self.on_change:
                self.on_change(None)

    def _on_drag(self, event) -> None:
        if not self.enabled:
            return
        d, dx, dy, dist = self._direction(event.x, event.y)
        # 노브를 반경 안으로 클램프해서 따라가게
        cx, cy = self._center()
        maxd = self.r - self.knob_r
        if dist > maxd and dist > 0:
            dx, dy = dx / dist * maxd, dy / dist * maxd
        kx, ky = cx + dx, cy + dy
        self.cv.coords(self.knob, kx - self.knob_r, ky - self.knob_r,
                       kx + self.knob_r, ky + self.knob_r)
        self.cv.itemconfig(self.knob, fill="#2e7d32" if d else "#1565c0")
        if d != self.cur:
            self.cur = d
            if self.on_change:
                self.on_change(d)

    def _on_release(self, event) -> None:
        self._reset_knob()
        if self.cur is not None:
            self.cur = None
            if self.on_change:
                self.on_change(None)
