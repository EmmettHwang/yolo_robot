# coding: utf-8
"""
motion_grid.py
==============
4×4 동작 버튼 그리드 위젯. 각 버튼에 모션 + 사운드(음성없음/mp3/TTS)를 지정.

- 좌클릭 : on_action(entry) 호출 → 소비자가 모션 전송 + 사운드 재생
- 우클릭 : 편집 다이얼로그(모션 드롭다운 + 사운드 드롭다운 + 값)
- 매핑은 data/motion_grid.json 에 저장/복원
  entry 구조: {"motion": int, "sound_kind": str, "sound_value": str}
"""

import os
import json

import tkinter as tk
from tkinter import ttk, messagebox

from paths import MOTION_GRID_JSON, DATA_DIR
from motion_table import motion_name, motion_label, ALL_MOTIONS
import sound as snd
import mp3_library

# 기본 매핑(모션 번호)
DEFAULT_MOTIONS = [
    1, 18, 19, 17,
    5, 6, 7, 8,
    2, 9, 12, 13,
    20, 21, 30, 55,
]


def _default_entries():
    return [{"motion": m, "sound_kind": snd.NONE, "sound_value": ""}
            for m in DEFAULT_MOTIONS]


class MotionGrid(tk.Frame):
    def __init__(self, master, on_action=None, show_save=True, **kw):
        super().__init__(master, **kw)
        self.on_action = on_action
        self.show_save = show_save        # 자체 저장 버튼 표시 여부
        self.entries = self._load()
        self.buttons = []
        self._build()

    def save(self) -> None:
        """외부에서 호출하는 조용한 저장(메시지 없음)."""
        self._save()

    # ---------- 저장/복원 ----------
    def _load(self) -> list:
        if os.path.exists(MOTION_GRID_JSON):
            try:
                with open(MOTION_GRID_JSON, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, list) and len(d) == 16:
                    out = []
                    for it in d:
                        if isinstance(it, dict):
                            out.append({
                                "motion": int(it.get("motion", 1)),
                                "sound_kind": it.get("sound_kind", snd.NONE),
                                "sound_value": it.get("sound_value", ""),
                            })
                        else:        # 구버전(정수)
                            out.append({"motion": int(it),
                                        "sound_kind": snd.NONE,
                                        "sound_value": ""})
                    return out
            except Exception:
                pass
        return _default_entries()

    def _save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(MOTION_GRID_JSON, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)

    # ---------- UI ----------
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
        tk.Label(bar, text="좌클릭=실행 · 우클릭=동작/사운드 설정", fg="#888",
                 font=("Malgun Gothic", 8)).pack(side="left")
        if self.show_save:
            tk.Button(bar, text="💾 저장", cursor="hand2",
                      command=self._save_btn).pack(side="right")

    def _refresh(self) -> None:
        for i, b in enumerate(self.buttons):
            e = self.entries[i]
            n = e["motion"]
            short = motion_name(n).split("(")[0].strip()
            tag = " 🔊" if e.get("sound_kind", snd.NONE) != snd.NONE else ""
            b.config(text=f"{n}{tag}\n{short}")

    def set_enabled(self, enabled: bool) -> None:
        st = "normal" if enabled else "disabled"
        for b in self.buttons:
            b.config(state=st)

    def _click(self, i: int) -> None:
        if self.on_action:
            self.on_action(self.entries[i])

    # ---------- 편집 다이얼로그 ----------
    def _edit(self, i: int) -> None:
        e = self.entries[i]
        top = tk.Toplevel(self)
        top.title(f"{i + 1}번 버튼 설정")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)

        # 모션
        tk.Label(top, text="동작(모션):", font=("Malgun Gothic", 10)).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        mvar = tk.StringVar(value=motion_label(e["motion"]))
        ttk.Combobox(top, textvariable=mvar, state="readonly", width=30,
                     values=[motion_label(n) for n in ALL_MOTIONS]).grid(
            row=0, column=1, padx=12, pady=(12, 4))

        # 사운드 종류
        tk.Label(top, text="사운드:", font=("Malgun Gothic", 10)).grid(
            row=1, column=0, sticky="w", padx=12, pady=4)
        svar = tk.StringVar(value=e.get("sound_kind", snd.NONE))
        scombo = ttk.Combobox(top, textvariable=svar, state="readonly",
                              width=30, values=[k for k, _ in snd.KINDS])
        scombo.grid(row=1, column=1, padx=12, pady=4)

        # 값 (사운드 종류에 따라 교체)
        tk.Label(top, text="값:", font=("Malgun Gothic", 10)).grid(
            row=2, column=0, sticky="w", padx=12, pady=4)
        holder = tk.Frame(top); holder.grid(row=2, column=1, padx=12, pady=4,
                                            sticky="w")
        vvar = tk.StringVar(value=e.get("sound_value", ""))
        mp3_items = mp3_library.list_mp3()

        def rebuild_value(*_):
            for w in holder.winfo_children():
                w.destroy()
            kind = svar.get()
            if kind == snd.MP3:
                labels = [lb for _, lb in mp3_items]
                paths = [p for p, _ in mp3_items]
                disp = tk.StringVar()
                if vvar.get() in paths:
                    disp.set(mp3_items[paths.index(vvar.get())][1])
                cb = ttk.Combobox(holder, textvariable=disp, state="readonly",
                                  width=28,
                                  values=labels or ["(assets/mp3 비어있음)"])
                cb.pack()

                def on_sel(e2):
                    if disp.get() in labels:
                        vvar.set(paths[labels.index(disp.get())])
                cb.bind("<<ComboboxSelected>>", on_sel)
            elif kind == snd.TTS:
                tk.Entry(holder, textvariable=vvar, width=30).pack()
            else:
                vvar.set("")
                tk.Label(holder, text="(사운드 없음)", fg="#999",
                         width=30, anchor="w").pack()

        scombo.bind("<<ComboboxSelected>>", rebuild_value)
        rebuild_value()

        def ok():
            t = mvar.get()
            if " - " in t:
                try:
                    self.entries[i] = {
                        "motion": int(t.split(" - ")[0]),
                        "sound_kind": svar.get() or snd.NONE,
                        "sound_value": vvar.get().strip(),
                    }
                    self._refresh()
                    self._save()        # 편집 즉시 자동 저장
                except Exception:
                    pass
            top.destroy()
        tk.Button(top, text="확인", bg="#1565c0", fg="white", relief="flat",
                  cursor="hand2", command=ok).grid(
            row=3, column=0, columnspan=2, pady=12)

    def _save_btn(self) -> None:
        self._save()
        messagebox.showinfo("저장", "4×4 그리드(동작+사운드)를 저장했습니다.")
