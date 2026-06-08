# coding: utf-8
"""
motion_grid.py
==============
4×4 동작 버튼 그리드 위젯.

- 각 버튼에 모션 번호를 매핑(좌클릭=실행, 우클릭=번호 변경).
- 매핑은 data/motion_grid.json 에 저장/복원.
- on_motion(번호) 콜백으로 실행 요청.
"""

import os
import json

import tkinter as tk
from tkinter import simpledialog, messagebox

from paths import MOTION_GRID_JSON, DATA_DIR
from motion_table import motion_name

# 기본 매핑 (모션테이블 참고)
DEFAULT = [
    1, 18, 19, 17,
    5, 6, 7, 8,
    2, 9, 12, 13,
    20, 21, 30, 55,
]


class MotionGrid(tk.Frame):
    def __init__(self, master, on_motion=None, **kw):
        super().__init__(master, **kw)
        self.on_motion = on_motion
        self.mapping = self._load()
        self.buttons = []
        self._build()

    def _load(self) -> list:
        if os.path.exists(MOTION_GRID_JSON):
            try:
                with open(MOTION_GRID_JSON, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, list) and len(d) == 16:
                    return [int(x) for x in d]
            except Exception:
                pass
        return list(DEFAULT)

    def _save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(MOTION_GRID_JSON, "w", encoding="utf-8") as f:
            json.dump(self.mapping, f, ensure_ascii=False)

    def _build(self) -> None:
        grid = tk.Frame(self); grid.pack()
        for i in range(16):
            r, c = divmod(i, 4)
            b = tk.Button(grid, width=11, height=2, cursor="hand2",
                          font=("Malgun Gothic", 8), relief="groove",
                          command=lambda i=i: self._click(i))
            b.grid(row=r, column=c, padx=2, pady=2)
            b.bind("<Button-3>", lambda e, i=i: self._edit(i))
            self.buttons.append(b)
        self._refresh()

        bar = tk.Frame(self); bar.pack(fill="x", pady=(6, 0))
        tk.Label(bar, text="좌클릭=실행 · 우클릭=번호변경", fg="#888",
                 font=("Malgun Gothic", 8)).pack(side="left")
        tk.Button(bar, text="💾 저장", cursor="hand2",
                  command=self._save_btn).pack(side="right")

    def _refresh(self) -> None:
        for i, b in enumerate(self.buttons):
            n = self.mapping[i]
            short = motion_name(n).split("(")[0].strip()
            b.config(text=f"{n}\n{short}")

    def _click(self, i: int) -> None:
        if self.on_motion:
            self.on_motion(self.mapping[i])

    def _edit(self, i: int) -> None:
        v = simpledialog.askinteger(
            "동작 번호", f"{i + 1}번 버튼에 매핑할 모션 번호 (1~255):",
            initialvalue=self.mapping[i], minvalue=1, maxvalue=255,
            parent=self)
        if v:
            self.mapping[i] = int(v)
            self._refresh()

    def _save_btn(self) -> None:
        self._save()
        messagebox.showinfo("저장", "4×4 그리드 매핑을 저장했습니다.")
