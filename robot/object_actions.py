# coding: utf-8
"""
object_actions.py
=================
인식한 객체 class → 로봇 반응(모션 + 사운드) 매핑.

매핑 구조 (JSON):
  { "person": {"motion": 18, "sound_kind": "tts", "sound_value": "안녕하세요"}, ... }

UI(ActionEditor):
  - 객체/모션/사운드 모두 드롭다운.
  - 객체는 '아직 지정 안 된 것'만 추가 드롭다운에 표시(중복 방지).
  - 모션도 다른 행에서 쓰인 번호는 제외(중복 방지).
  - 사운드=mp3 면 assets/mp3 목록을 메타정보(제목-아티스트(길이))로 드롭다운 표시.
"""

import os
import json

import tkinter as tk
from tkinter import ttk, messagebox

from paths import OBJECT_ACTIONS_JSON, DATA_DIR
import sound as snd
import mp3_library
from motion_table import (
    ALL_MOTIONS, motion_label, motion_name, COCO_CLASSES, coco_kr,
)


def obj_label(name: str) -> str:
    """객체 이름에 한글 번역 병기. (예: 'person' → 'person (사람)')"""
    kr = coco_kr(name)
    return f"{name} ({kr})" if kr else name

NONE_MOTION = "(없음)"


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
# 편집 UI
# ============================================================
class ActionEditor(ttk.Frame):
    def __init__(self, master, class_names=None, **kw):
        super().__init__(master, **kw)
        self.mapping = load_actions()
        # 선택 가능한 전체 객체 = COCO + 수집 클래스 + 기존 매핑 키
        base = list(COCO_CLASSES)
        for c in (class_names or []):
            if c not in base:
                base.append(c)
        for k in self.mapping.keys():
            if k not in base:
                base.append(k)
        self.all_objects = base
        self.motion_labels = [motion_label(n) for n in ALL_MOTIONS]
        self.rows = []          # 각 행: dict
        self._disp_to_name = {}  # 드롭다운 표시문자열 → 실제 클래스명
        self.mp3_items = mp3_library.list_mp3()   # [(path,label)]
        self._build()
        self._load_existing()

    # ---------- 레이아웃 ----------
    def _build(self):
        tk.Label(self, text="🎯 객체 반응 지정",
                 font=("Malgun Gothic", 14, "bold")).pack(pady=(10, 2))
        tk.Label(self, text="인식된 객체에 모션과 사운드를 지정합니다. "
                 "(객체·모션은 중복 없이 선택 · 지속시간 비우면 mp3 길이)",
                 font=("Malgun Gothic", 9), fg="#666").pack()
        # 동작 종료 자동 감지는 프로토콜상 불가 → 비활성 표시(시간 기반 사용)
        tk.Checkbutton(self, text="로봇 동작 종료 자동 감지 (미지원 — 시간 기반 사용)",
                       state="disabled", font=("Malgun Gothic", 9)).pack()

        # 추가 줄 (검색 + 드롭다운)
        add = tk.Frame(self); add.pack(fill="x", padx=12, pady=8)
        tk.Label(add, text="객체 검색:", font=("Malgun Gothic", 10)).pack(
            side="left")
        self.search_var = tk.StringVar()
        se = tk.Entry(add, textvariable=self.search_var, width=14)
        se.pack(side="left", padx=(4, 6))
        self.search_var.trace_add("write",
                                  lambda *a: self._refresh_add_combo())
        self.add_var = tk.StringVar()
        self.add_combo = ttk.Combobox(add, textvariable=self.add_var,
                                      state="readonly", width=22)
        self.add_combo.pack(side="left", padx=(0, 6))
        tk.Button(add, text="+ 추가", bg="#1565c0", fg="white", relief="flat",
                  cursor="hand2", command=self._add_selected).pack(side="left")
        tk.Button(add, text="↻ mp3/목록 새로고침", cursor="hand2",
                  command=self._refresh_all).pack(side="left", padx=(8, 0))

        # 헤더
        head = tk.Frame(self); head.pack(fill="x", padx=12)
        for txt, w in (("객체", 18), ("모션", 28), ("사운드", 11),
                       ("값(mp3 / 읽을 말) · 지속(초)", 42)):
            tk.Label(head, text=txt, width=w, anchor="w",
                     font=("Malgun Gothic", 9, "bold")).pack(side="left")

        # 스크롤 영역
        wrap = tk.Frame(self); wrap.pack(fill="both", expand=True, padx=12,
                                         pady=(2, 6))
        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bar = tk.Frame(self); bar.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(bar, text="💾 저장", bg="#28a745", fg="white", relief="flat",
                  cursor="hand2", font=("Malgun Gothic", 10, "bold"),
                  command=self._save).pack(side="right")

        self._refresh_add_combo()

    # ---------- 가용 목록 계산 (중복 방지) ----------
    def _used_objects(self):
        return {r["obj"] for r in self.rows}

    def _used_motions(self, except_row=None):
        used = set()
        for r in self.rows:
            if r is except_row:
                continue
            m = self._row_motion_num(r)
            if m is not None:
                used.add(m)
        return used

    def _available_objects(self):
        used = self._used_objects()
        return [o for o in self.all_objects if o not in used]

    def _row_motion_num(self, row):
        t = row["motion_var"].get()
        if t and t != NONE_MOTION and " - " in t:
            try:
                return int(t.split(" - ")[0])
            except Exception:
                return None
        return None

    def _available_motion_labels(self, row):
        used = self._used_motions(except_row=row)
        labels = [NONE_MOTION]
        for n in ALL_MOTIONS:
            if n not in used:
                labels.append(motion_label(n))
        cur = row["motion_var"].get()
        if cur and cur not in labels:        # 현재 선택은 항상 포함
            labels.append(cur)
        return labels

    def _refresh_add_combo(self):
        avail = self._available_objects()
        q = self.search_var.get().strip().lower() \
            if hasattr(self, "search_var") else ""
        pairs = [(obj_label(o), o) for o in avail]   # (표시, 실제명)
        if q:
            pairs = [(d, o) for d, o in pairs if q in d.lower()]
        self._disp_to_name = {d: o for d, o in pairs}
        self.add_combo["values"] = [d for d, _ in pairs]
        if pairs:
            self.add_combo.current(0)
        else:
            self.add_var.set("(검색결과 없음)" if q else "(모든 객체 지정됨)")

    def _refresh_motion_combos(self):
        for r in self.rows:
            r["motion_combo"]["values"] = self._available_motion_labels(r)

    def _refresh_all(self):
        self.mp3_items = mp3_library.list_mp3()
        for r in list(self.rows):
            self._rebuild_value(r)
        self._refresh_motion_combos()
        self._refresh_add_combo()

    # ---------- 행 추가/삭제 ----------
    def _load_existing(self):
        for obj, act in self.mapping.items():
            self._add_row(obj, act)
        self._refresh_add_combo()
        self._refresh_motion_combos()

    def _add_selected(self):
        disp = self.add_var.get().strip()
        obj = self._disp_to_name.get(disp, disp)   # 표시문자열 → 실제 클래스명
        if not obj or obj.startswith("("):
            return
        if obj in self._used_objects():
            return
        self._add_row(obj, {})
        self._refresh_add_combo()
        self._refresh_motion_combos()
        self._autosave()

    def _add_row(self, obj, act):
        row = {"obj": obj}
        fr = tk.Frame(self.body); fr.pack(fill="x", pady=2)
        row["frame"] = fr

        tk.Label(fr, text=obj_label(obj), width=22, anchor="w",
                 font=("Malgun Gothic", 9)).pack(side="left")

        mv = tk.StringVar()
        m = act.get("motion")
        if m:
            mv.set(motion_label(int(m)))
        else:
            mv.set(NONE_MOTION)
        row["motion_var"] = mv
        mc = ttk.Combobox(fr, textvariable=mv, state="readonly", width=28)
        mc.pack(side="left")
        mc.bind("<<ComboboxSelected>>",
                lambda e: (self._refresh_motion_combos(), self._autosave()))
        row["motion_combo"] = mc

        sv = tk.StringVar(value=act.get("sound_kind", snd.NONE))
        row["sound_var"] = sv
        sc = ttk.Combobox(fr, textvariable=sv, state="readonly", width=10,
                          values=[k for k, _ in snd.KINDS])
        sc.pack(side="left", padx=(4, 0))
        sc.bind("<<ComboboxSelected>>",
                lambda e, r=row: (self._rebuild_value(r), self._autosave()))
        row["sound_combo"] = sc

        row["val_holder"] = tk.Frame(fr)
        row["val_holder"].pack(side="left", padx=(4, 0))
        row["val_var"] = tk.StringVar(value=act.get("sound_value", ""))

        # 지속시간(초) — 비우면 mp3 길이만큼. 라벨을 인라인으로 붙여 항상 정렬
        dur = act.get("duration")
        dv = tk.StringVar(value=(str(dur) if dur else ""))
        durwrap = tk.Frame(fr); durwrap.pack(side="left", padx=(8, 0))
        tk.Label(durwrap, text="지속", font=("Malgun Gothic", 9),
                 fg="#666").pack(side="left")
        de = tk.Entry(durwrap, textvariable=dv, width=5)
        de.pack(side="left", padx=(2, 1))
        tk.Label(durwrap, text="초", font=("Malgun Gothic", 9),
                 fg="#666").pack(side="left")
        de.bind("<FocusOut>", lambda e: self._autosave())
        row["dur_var"] = dv

        tk.Button(fr, text="✕", width=2, cursor="hand2",
                  command=lambda r=row: self._del_row(r)).pack(side="left",
                                                               padx=(4, 0))
        self.rows.append(row)
        self._rebuild_value(row)

    def _del_row(self, row):
        row["frame"].destroy()
        self.rows.remove(row)
        self._refresh_add_combo()
        self._refresh_motion_combos()
        self._autosave()

    # ---------- 값 위젯 (사운드 종류에 따라 교체) ----------
    def _rebuild_value(self, row):
        for w in row["val_holder"].winfo_children():
            w.destroy()
        kind = row["sound_var"].get()
        if kind == snd.MP3:
            labels = [lb for _, lb in self.mp3_items]
            paths = [p for p, _ in self.mp3_items]
            disp = tk.StringVar()
            cur = row["val_var"].get()
            if cur in paths:
                disp.set(self.mp3_items[paths.index(cur)][1])
            cb = ttk.Combobox(row["val_holder"], textvariable=disp,
                              state="readonly", width=34,
                              values=labels or ["(assets/mp3 비어있음)"])

            def on_sel(e, r=row, ps=paths, ls=labels, d=disp):
                if d.get() in ls:
                    r["val_var"].set(ps[ls.index(d.get())])
                    self._autosave()
            cb.bind("<<ComboboxSelected>>", on_sel)
            cb.pack(side="left")
        elif kind == snd.TTS:
            ent = tk.Entry(row["val_holder"], textvariable=row["val_var"],
                           width=34)
            ent.pack(side="left")
            ent.bind("<FocusOut>", lambda e: self._autosave())
        else:
            row["val_var"].set("")
            tk.Label(row["val_holder"], text="(사운드 없음)", width=34,
                     anchor="w", fg="#999").pack(side="left")

    # ---------- 저장 ----------
    def _collect(self) -> dict:
        result = {}
        for r in self.rows:
            motion = self._row_motion_num(r)
            kind = r["sound_var"].get() or snd.NONE
            val = r["val_var"].get().strip()
            if motion is None and kind == snd.NONE:
                continue
            entry = {"sound_kind": kind, "sound_value": val}
            if motion is not None:
                entry["motion"] = motion
            dv = r.get("dur_var")
            if dv is not None:
                t = dv.get().strip()
                if t:
                    try:
                        d = float(t)
                        if d > 0:
                            entry["duration"] = d
                    except Exception:
                        pass
            result[r["obj"]] = entry
        return result

    def _autosave(self):
        """변경 즉시 조용히 저장."""
        self.mapping = self._collect()
        save_actions(self.mapping)

    def _save(self):
        self._autosave()
        messagebox.showinfo("저장", f"{len(self.mapping)}개 객체 반응을 저장했습니다.")
