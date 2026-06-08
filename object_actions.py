# coding: utf-8
"""
object_actions.py
=================
인식한 객체 class → 로봇 반응(모션 + 사운드) 매핑.

매핑 구조 (JSON):
  {
    "person": {"motion": 18, "sound_kind": "tts", "sound_value": "안녕하세요"},
    "bottle": {"motion": 19, "sound_kind": "mp3", "sound_value": "C:/.../a.mp3"},
    ...
  }

- load_actions()/save_actions()  : JSON 입출력
- perform(label, runner, player) : 매핑된 모션 전송 + 사운드 재생
- ActionEditor(Frame)            : 매핑 편집 UI (탭/창에 임베드 가능)
"""

import os
import json

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from paths import OBJECT_ACTIONS_JSON, DATA_DIR
import sound as snd
from motion_table import MOTION_NAMES, motion_name


def load_actions() -> dict:
    if not os.path.exists(OBJECT_ACTIONS_JSON):
        return {}
    try:
        with open(OBJECT_ACTIONS_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_actions(mapping: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OBJECT_ACTIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def perform(label: str, runner, player, mapping: dict = None) -> bool:
    """label에 매핑된 모션/사운드를 실행. 매핑이 없으면 False."""
    mapping = mapping if mapping is not None else load_actions()
    act = mapping.get(label)
    if not act:
        return False
    motion = act.get("motion")
    if motion and runner is not None:
        runner.send_once(int(motion))
    kind = act.get("sound_kind", snd.NONE)
    value = act.get("sound_value", "")
    if player is not None and kind and kind != snd.NONE:
        player.play(kind, value)
    return True


# ============================================================
# 편집 UI (탭/프레임에 임베드)
# ============================================================
class ActionEditor(ttk.Frame):
    """객체 class별 반응(모션/사운드) 편집 프레임."""

    def __init__(self, master, class_names=None, **kw):
        super().__init__(master, **kw)
        self.mapping = load_actions()
        self.class_names = list(class_names or [])
        self.rows = {}
        self._motion_values = [f"{i} - {n}" for i, n in
                               sorted(MOTION_NAMES.items())]
        self._build()

    def set_classes(self, class_names) -> None:
        self.class_names = list(class_names or [])
        self._rebuild_rows()

    def _build(self) -> None:
        tk.Label(self, text="객체 반응 지정 (class → 모션 + 사운드)",
                 font=("Malgun Gothic", 13, "bold")).pack(pady=(8, 4))

        head = tk.Frame(self); head.pack(fill="x", padx=10)
        for txt, w in (("객체 class", 16), ("모션", 26),
                       ("사운드", 12), ("값(mp3경로 / 읽을말)", 30)):
            tk.Label(head, text=txt, width=w, anchor="w",
                     font=("Malgun Gothic", 9, "bold")).pack(side="left")

        self.body = tk.Frame(self); self.body.pack(fill="both", expand=True,
                                                   padx=10)
        self._rebuild_rows()

        bar = tk.Frame(self); bar.pack(fill="x", padx=10, pady=10)
        ttk.Button(bar, text="+ 클래스 직접 추가",
                   command=self._add_custom_class).pack(side="left")
        tk.Button(bar, text="💾 저장", bg="#28a745", fg="white",
                  relief="flat", font=("Malgun Gothic", 10, "bold"),
                  command=self._save).pack(side="right")

    def _rebuild_rows(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        self.rows = {}
        names = list(dict.fromkeys(self.class_names + list(self.mapping.keys())))
        if not names:
            tk.Label(self.body, text="(표시할 클래스가 없습니다. "
                     "모델을 로드하거나 클래스를 직접 추가하세요.)",
                     fg="#888", font=("Malgun Gothic", 9)).pack(pady=8)
            return
        for name in names:
            self._add_row(name)

    def _add_row(self, name: str) -> None:
        act = self.mapping.get(name, {})
        row = tk.Frame(self.body); row.pack(fill="x", pady=2)
        tk.Label(row, text=name, width=16, anchor="w",
                 font=("Malgun Gothic", 9)).pack(side="left")

        motion_var = tk.StringVar()
        cur_motion = act.get("motion")
        if cur_motion:
            motion_var.set(f"{cur_motion} - {motion_name(int(cur_motion))}")
        mc = ttk.Combobox(row, textvariable=motion_var, width=24,
                          values=["(없음)"] + self._motion_values,
                          state="readonly")
        mc.pack(side="left")

        kind_var = tk.StringVar(value=act.get("sound_kind", snd.NONE))
        kc = ttk.Combobox(row, textvariable=kind_var, width=10,
                          values=[k for k, _ in snd.KINDS], state="readonly")
        kc.pack(side="left", padx=(4, 0))

        val_var = tk.StringVar(value=act.get("sound_value", ""))
        ve = tk.Entry(row, textvariable=val_var, width=30)
        ve.pack(side="left", padx=(4, 0))
        tk.Button(row, text="...", width=2,
                  command=lambda v=val_var: self._browse_mp3(v)).pack(
            side="left")

        self.rows[name] = (motion_var, kind_var, val_var)

    def _browse_mp3(self, var) -> None:
        path = filedialog.askopenfilename(
            title="mp3 선택", filetypes=[("MP3", "*.mp3"), ("모든 파일", "*.*")])
        if path:
            var.set(path)

    def _add_custom_class(self) -> None:
        top = tk.Toplevel(self); top.title("클래스 추가")
        tk.Label(top, text="클래스 이름:", font=("Malgun Gothic", 10)).pack(
            padx=12, pady=(12, 4))
        var = tk.StringVar()
        tk.Entry(top, textvariable=var, width=24).pack(padx=12)

        def ok():
            n = var.get().strip()
            if n and n not in self.class_names:
                self.class_names.append(n)
                self._rebuild_rows()
            top.destroy()
        tk.Button(top, text="추가", command=ok).pack(pady=10)

    def _save(self) -> None:
        result = {}
        for name, (mv, kv, vv) in self.rows.items():
            mtext = mv.get()
            motion = None
            if mtext and mtext != "(없음)" and " - " in mtext:
                try:
                    motion = int(mtext.split(" - ")[0])
                except Exception:
                    motion = None
            entry = {"sound_kind": kv.get() or snd.NONE,
                     "sound_value": vv.get().strip()}
            if motion is not None:
                entry["motion"] = motion
            # 의미 있는 매핑만 저장
            if motion is not None or entry["sound_kind"] != snd.NONE:
                result[name] = entry
        self.mapping = result
        save_actions(result)
        messagebox.showinfo("저장", f"{len(result)}개 클래스 반응을 저장했습니다.")
