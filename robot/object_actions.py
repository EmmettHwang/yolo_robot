# coding: utf-8
"""
object_actions.py
=================
인식한 객체 class → 로봇 반응(동작 + 사운드) 매핑.

한 객체에 '서브 동작'을 최대 5개까지 지정해 순서대로 실행할 수 있다.

매핑 구조 (JSON):
  { "person": {"steps": [
        {"motion": 18, "sound_kind": "tts", "sound_value": "안녕", "duration": 3},
        {"motion": 5,  "sound_kind": "random", "sound_value": "", "duration": 2}
     ]}, ... }

(옛 형식 {"motion":.., "sound_kind":..} 도 자동으로 steps 1개로 변환해 읽는다.)

사운드 종류: none / mp3 / tts / random(다양한 로봇음 voice_*.wav 무작위).
"""

import os
import json

import tkinter as tk
from tkinter import ttk, messagebox

from paths import OBJECT_ACTIONS_JSON, DATA_DIR
import sound as snd
import mp3_library
from motion_table import (
    ALL_MOTIONS, motion_label, COCO_CLASSES, coco_kr, PWR_ON, PWR_OFF,
    VOICE_CHAT,
)
import voice_chat

MAX_STEPS = 5
NONE_MOTION = "(없음)"

# ❓ 만약(조건) — A단계 프리셋. (key, 표시이름)
CONDITIONS = [
    ("always", "항상"),
    ("conf90", "신뢰도 90%↑"),
    ("conf70", "신뢰도 70%↑"),
    ("rand50", "확률 50%"),
    ("rand30", "확률 30%"),
    ("count2", "같은 객체 2개↑"),
    ("count3", "같은 객체 3개↑"),
    ("day", "낮(06–18시)"),
    ("night", "밤(18–06시)"),
]
COND_KEY2LABEL = dict(CONDITIONS)
COND_LABEL2KEY = {lb: k for k, lb in CONDITIONS}


def eval_condition(key, conf=1.0, count=1) -> bool:
    """스텝 실행 조건 평가. ctx: conf(신뢰도), count(같은 객체 수)."""
    import random as _r
    import datetime as _dt
    if not key or key == "always":
        return True
    h = _dt.datetime.now().hour
    return {
        "conf90": conf >= 0.90,
        "conf70": conf >= 0.70,
        "rand50": _r.random() < 0.50,
        "rand30": _r.random() < 0.30,
        "count2": count >= 2,
        "count3": count >= 3,
        "day": 6 <= h < 18,
        "night": not (6 <= h < 18),
    }.get(key, True)


def obj_label(name: str, num=None) -> str:
    """객체 이름에 번호 + 한글 번역 병기.

    num 지정 시: '1. person (사람)'  (인식/학습 화면과 일관성)
    """
    kr = coco_kr(name)
    base = f"{name} ({kr})" if kr else name
    return f"{num}. {base}" if num is not None else base


# ============================================================
# 데이터 입출력 / 정규화
# ============================================================
def _normalize(entry: dict) -> dict:
    """엔트리를 {'steps': [...]} 형태로 정규화(옛 평면 형식 호환)."""
    if isinstance(entry, dict) and isinstance(entry.get("steps"), list):
        raw = entry["steps"]
    else:
        raw = [entry] if isinstance(entry, dict) else []
    steps = []
    for s in raw[:MAX_STEPS]:
        if not isinstance(s, dict):
            continue
        steps.append({
            "motion": s.get("motion"),
            "sound_kind": s.get("sound_kind", snd.NONE),
            "sound_value": s.get("sound_value", ""),
            "duration": s.get("duration"),
            "repeat": int(s.get("repeat", 1) or 1),   # 🔁 반복 횟수
            "cond": s.get("cond", "always"),           # ❓ 만약(조건) 키
        })
    return {"steps": steps}


def steps_of(act: dict) -> list:
    """반응 엔트리에서 스텝 리스트를 반환(정규화 포함)."""
    return _normalize(act).get("steps", [])


def load_actions() -> dict:
    if not os.path.exists(OBJECT_ACTIONS_JSON):
        return {}
    try:
        with open(OBJECT_ACTIONS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        return {k: _normalize(v) for k, v in data.items()}
    except Exception:
        return {}


def save_actions(mapping: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OBJECT_ACTIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def perform(label: str, runner, player, mapping: dict = None) -> bool:
    """객체 반응 실행(서브 동작 순차). runner 가 있으면 시퀀스로 전송."""
    mapping = mapping if mapping is not None else load_actions()
    act = mapping.get(label)
    if not act:
        return False
    steps = steps_of(act)
    if not steps:
        return False
    if runner is not None and hasattr(runner, "action_sequence"):
        seq = [{"motion": s.get("motion"), "hold": s.get("duration"),
                "sound_kind": s.get("sound_kind", snd.NONE),
                "sound_value": s.get("sound_value", "")} for s in steps]
        runner.action_sequence(seq, sound_on=player is not None)
        return True
    # 폴백: 첫 스텝만 단발 실행
    s0 = steps[0]
    if s0.get("motion") and runner is not None:
        runner.send_once(int(s0["motion"]))
    kind = s0.get("sound_kind", snd.NONE)
    if player is not None and kind and kind != snd.NONE:
        player.play(kind, s0.get("sound_value", ""))
    return True


# ============================================================
# 편집 UI
# ============================================================
class ActionEditor(ttk.Frame):
    def __init__(self, master, class_names=None, **kw):
        super().__init__(master, **kw)
        self.mapping = load_actions()
        base = list(COCO_CLASSES)
        for c in (class_names or []):
            if c not in base:
                base.append(c)
        for k in self.mapping.keys():
            if k not in base:
                base.append(k)
        self.all_objects = base
        self._obj_num = {o: i + 1 for i, o in enumerate(self.all_objects)}
        self._motion_values = ([NONE_MOTION]
                               + [motion_label(n) for n in ALL_MOTIONS]
                               + [motion_label(PWR_ON), motion_label(PWR_OFF),
                                  motion_label(VOICE_CHAT)])
        self.groups = []         # 각 객체 그룹
        self._disp_to_name = {}
        self.mp3_items = mp3_library.list_mp3()
        self._build()
        self._load_existing()

    # ---------- 레이아웃 ----------
    def _build(self):
        tk.Label(self, text="🎯 인식 및 반응 설정",
                 font=("Malgun Gothic", 14, "bold")).pack(pady=(10, 2))
        tk.Label(self, text="객체마다 동작+사운드를 '서브 동작'으로 최대 5개까지 "
                 "추가해 순서대로 실행합니다. (지속 비우면 mp3 길이)",
                 font=("Malgun Gothic", 9), fg="#666").pack()

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
        tk.Button(add, text="+ 객체 추가", bg="#1565c0", fg="white",
                  relief="flat", cursor="hand2",
                  command=self._add_selected).pack(side="left")
        tk.Button(add, text="↻ mp3/목록 새로고침", cursor="hand2",
                  command=self._refresh_all).pack(side="left", padx=(8, 0))

        # 음성 대화 LLM 모델 선택(모션에서 '음성 대화' 고를 때 사용)
        vrow = tk.Frame(self); vrow.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(vrow, text="🎤 음성대화 모델:", font=("Malgun Gothic", 9),
                 fg="#555").pack(side="left")
        self.voice_model_var = tk.StringVar(value=voice_chat.load_cfg()
                                            .get("model", ""))
        self.voice_combo = ttk.Combobox(vrow, textvariable=self.voice_model_var,
                                        state="readonly", width=24)
        self.voice_combo.pack(side="left", padx=(4, 4))
        self.voice_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: voice_chat.save_cfg(model=self.voice_model_var.get()))
        tk.Button(vrow, text="↻ 모델 목록", cursor="hand2",
                  command=self._refresh_voice_models).pack(side="left")
        tk.Label(vrow, text="(로컬 Ollama 실행 필요)", font=("Malgun Gothic", 8),
                 fg="#999").pack(side="left", padx=(6, 0))
        self._refresh_voice_models()

        # 스크롤 영역
        wrap = tk.Frame(self); wrap.pack(fill="both", expand=True, padx=12,
                                         pady=(2, 6))
        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self._body_win = self.canvas.create_window((0, 0), window=self.body,
                                                   anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(
            self._body_win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bar = tk.Frame(self); bar.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(bar, text="💾 저장", bg="#28a745", fg="white", relief="flat",
                  cursor="hand2", font=("Malgun Gothic", 10, "bold"),
                  command=self._save).pack(side="right")

        self._refresh_add_combo()

    # ---------- 객체 추가 드롭다운 ----------
    def _used_objects(self):
        return {g["obj"] for g in self.groups}

    def _available_objects(self):
        used = self._used_objects()
        return [o for o in self.all_objects if o not in used]

    def _refresh_add_combo(self):
        avail = self._available_objects()
        q = self.search_var.get().strip().lower() \
            if hasattr(self, "search_var") else ""
        pairs = [(obj_label(o, self._obj_num.get(o)), o) for o in avail]
        if q:
            pairs = [(d, o) for d, o in pairs if q in d.lower()]
        self._disp_to_name = {d: o for d, o in pairs}
        self.add_combo["values"] = [d for d, _ in pairs]
        if pairs:
            self.add_combo.current(0)
        else:
            self.add_var.set("(검색결과 없음)" if q else "(모든 객체 지정됨)")

    def _refresh_voice_models(self):
        models = voice_chat.list_models()
        self.voice_combo["values"] = models or ["(Ollama 실행/모델 없음)"]
        cur = self.voice_model_var.get()
        if cur and cur in models:
            self.voice_combo.set(cur)
        elif models:
            self.voice_combo.set(models[0])
            voice_chat.save_cfg(model=models[0])

    def _refresh_all(self):
        self.mp3_items = mp3_library.list_mp3()
        for g in self.groups:
            for st in g["steps"]:
                self._rebuild_value(st)
        self._refresh_add_combo()

    # ---------- 로드 ----------
    def _load_existing(self):
        for obj, act in self.mapping.items():
            self._add_group(obj, steps_of(act))
        self._refresh_add_combo()

    def reload(self):
        """JSON을 다시 읽어 표 전체를 재구성(다른 탭에서 바꾼 내용 반영)."""
        for g in list(self.groups):
            try:
                g["frame"].destroy()
            except Exception:
                pass
        self.groups = []
        self.mp3_items = mp3_library.list_mp3()
        self.mapping = load_actions()
        self._load_existing()

    def _add_selected(self):
        disp = self.add_var.get().strip()
        obj = self._disp_to_name.get(disp, disp)
        if not obj or obj.startswith("("):
            return
        if obj in self._used_objects():
            return
        self._add_group(obj, [])          # 빈 스텝 1개로 시작
        self._refresh_add_combo()
        self._autosave()

    # ---------- 표 컬럼 정렬 ----------
    # (minsize px, weight) — 헤더와 모든 스텝 행이 같은 grid 컬럼을 써서 칸을 맞춘다.
    # 0 모션 · 1 사운드 · 2 값 · 3 지속 · 4 반복 · 5 조건 · 6 순서/삭제
    _COLS = [(200, 0), (100, 0), (212, 1), (80, 0), (74, 0), (150, 0), (100, 0)]

    def _config_cols(self, frame):
        for i, (mn, wt) in enumerate(self._COLS):
            frame.grid_columnconfigure(i, minsize=mn, weight=wt)

    # ---------- 객체 그룹(카드) ----------
    def _add_group(self, obj, steps_data):
        card = tk.Frame(self.body, bd=1, relief="solid", bg="#fbfcff")
        card.pack(fill="x", pady=4, padx=2)
        group = {"obj": obj, "frame": card, "steps": []}

        head = tk.Frame(card, bg="#eef2fb"); head.pack(fill="x")
        tk.Label(head, text=obj_label(obj, self._obj_num.get(obj)),
                 font=("Malgun Gothic", 10, "bold"), bg="#eef2fb").pack(
            side="left", padx=8, pady=4)
        tk.Button(head, text="✕ 객체 삭제", cursor="hand2",
                  relief="flat", fg="#c62828", bg="#eef2fb",
                  command=lambda g=group: self._del_group(g)).pack(
            side="right", padx=6)
        group["add_btn"] = tk.Button(
            head, text="＋ 서브 동작", cursor="hand2", relief="flat",
            fg="#1565c0", bg="#eef2fb",
            command=lambda g=group: self._add_step(g))
        group["add_btn"].pack(side="right")

        # 컬럼 헤더 — 스텝 행과 동일한 grid 컬럼을 사용해 칸을 맞춘다.
        ch = tk.Frame(card, bg="#fbfcff"); ch.pack(fill="x", padx=8)
        self._config_cols(ch)
        for col, txt in enumerate(("모션", "사운드", "값 (mp3 / 읽을 말)",
                                   "지속", "🔁 반복", "❓ 조건", "순서 · 삭제")):
            tk.Label(ch, text=txt, anchor="w", bg="#fbfcff",
                     font=("Malgun Gothic", 8, "bold"), fg="#888").grid(
                row=0, column=col, sticky="w", padx=(0, 4), pady=(0, 1))

        group["steps_frame"] = tk.Frame(card, bg="#fbfcff")
        group["steps_frame"].pack(fill="x", padx=8, pady=(0, 6))

        self.groups.append(group)
        if steps_data:
            for st in steps_data:
                self._add_step(group, st)
        else:
            self._add_step(group, {})
        self._update_add_btn(group)

    def _del_group(self, group):
        group["frame"].destroy()
        if group in self.groups:
            self.groups.remove(group)
        self._refresh_add_combo()
        self._autosave()

    def _update_add_btn(self, group):
        full = len(group["steps"]) >= MAX_STEPS
        try:
            group["add_btn"].config(
                state="disabled" if full else "normal",
                text="최대 5개" if full else "＋ 서브 동작")
        except Exception:
            pass

    # ---------- 스텝(서브 동작) ----------
    def _add_step(self, group, data=None):
        if len(group["steps"]) >= MAX_STEPS:
            return
        data = data or {}
        fr = tk.Frame(group["steps_frame"], bg="#fbfcff")
        fr.pack(fill="x", pady=1)
        self._config_cols(fr)
        step = {"frame": fr}

        # col0 모션
        mv = tk.StringVar()
        m = data.get("motion")
        mv.set(motion_label(int(m)) if m else NONE_MOTION)
        step["motion_var"] = mv
        mc = ttk.Combobox(fr, textvariable=mv, state="readonly", width=22,
                          values=self._motion_values)
        mc.grid(row=0, column=0, sticky="w", padx=(0, 4))
        mc.bind("<<ComboboxSelected>>", lambda e: self._autosave())
        step["motion_combo"] = mc

        # col1 사운드
        sv = tk.StringVar(value=data.get("sound_kind", snd.NONE))
        step["sound_var"] = sv
        sc = ttk.Combobox(fr, textvariable=sv, state="readonly", width=9,
                          values=[k for k, _ in snd.KINDS])
        sc.grid(row=0, column=1, sticky="w", padx=(0, 4))
        sc.bind("<<ComboboxSelected>>",
                lambda e, s=step: (self._rebuild_value(s), self._autosave()))
        step["sound_combo"] = sc

        # col2 값 (mp3/읽을 말/랜덤/없음) — 내용은 _rebuild_value 가 채움
        step["val_holder"] = tk.Frame(fr, bg="#fbfcff")
        step["val_holder"].grid(row=0, column=2, sticky="w", padx=(0, 4))
        step["val_var"] = tk.StringVar(value=data.get("sound_value", ""))

        # col3 지속(초)
        dur = data.get("duration")
        dv = tk.StringVar(value=(str(dur) if dur else ""))
        durwrap = tk.Frame(fr, bg="#fbfcff")
        durwrap.grid(row=0, column=3, sticky="w")
        de = tk.Entry(durwrap, textvariable=dv, width=4)
        de.pack(side="left")
        tk.Label(durwrap, text="초", font=("Malgun Gothic", 9), fg="#666",
                 bg="#fbfcff").pack(side="left")
        de.bind("<FocusOut>", lambda e: self._autosave())
        step["dur_var"] = dv

        # col4 🔁 반복 횟수
        repwrap = tk.Frame(fr, bg="#fbfcff")
        repwrap.grid(row=0, column=4, sticky="w")
        tk.Label(repwrap, text="🔁", bg="#fbfcff").pack(side="left")
        rv = tk.IntVar(value=int(data.get("repeat", 1) or 1))
        tk.Spinbox(repwrap, from_=1, to=10, width=2, textvariable=rv,
                   command=self._autosave).pack(side="left")
        step["repeat_var"] = rv

        # col5 ❓ 만약(조건)
        condwrap = tk.Frame(fr, bg="#fbfcff")
        condwrap.grid(row=0, column=5, sticky="w")
        tk.Label(condwrap, text="❓", bg="#fbfcff").pack(side="left")
        cvar = tk.StringVar(value=COND_KEY2LABEL.get(
            data.get("cond", "always"), "항상"))
        cc = ttk.Combobox(condwrap, textvariable=cvar, state="readonly",
                          width=11, values=[lb for _, lb in CONDITIONS])
        cc.pack(side="left")
        cc.bind("<<ComboboxSelected>>", lambda e: self._autosave())
        step["cond_var"] = cvar

        # col6 순서 이동 ▲/▼ · 삭제 ✕
        ctrl = tk.Frame(fr, bg="#fbfcff")
        ctrl.grid(row=0, column=6, sticky="w")
        tk.Button(ctrl, text="▲", width=2, cursor="hand2", relief="flat",
                  command=lambda g=group, s=step: self._move_step(g, s, -1)
                  ).pack(side="left")
        tk.Button(ctrl, text="▼", width=2, cursor="hand2", relief="flat",
                  command=lambda g=group, s=step: self._move_step(g, s, 1)
                  ).pack(side="left", padx=(2, 0))
        tk.Button(ctrl, text="✕", width=2, cursor="hand2", relief="flat",
                  fg="#c62828",
                  command=lambda g=group, s=step: self._del_step(g, s)).pack(
            side="left", padx=(6, 0))

        group["steps"].append(step)
        self._rebuild_value(step)
        self._update_add_btn(group)
        if data == {}:
            self._autosave()

    def _move_step(self, group, step, direction):
        """동작(서브 스텝) 순서를 위(-1)/아래(+1)로 이동."""
        steps = group["steps"]
        i = steps.index(step)
        j = i + direction
        if not (0 <= j < len(steps)):
            return
        steps[i], steps[j] = steps[j], steps[i]
        for st in steps:                 # 현재 순서대로 다시 배치
            st["frame"].pack_forget()
        for st in steps:
            st["frame"].pack(fill="x", pady=1)
        self._autosave()

    def _del_step(self, group, step):
        step["frame"].destroy()
        if step in group["steps"]:
            group["steps"].remove(step)
        if not group["steps"]:           # 스텝이 0개면 객체 자체 삭제
            self._del_group(group)
            return
        self._update_add_btn(group)
        self._autosave()

    # ---------- 값 위젯 ----------
    def _rebuild_value(self, step):
        for w in step["val_holder"].winfo_children():
            w.destroy()
        kind = step["sound_var"].get()
        if kind == snd.MP3:
            labels = [lb for _, lb in self.mp3_items]
            paths = [p for p, _ in self.mp3_items]
            disp = tk.StringVar()
            step["_mp3_disp"] = disp
            cur = step["val_var"].get()
            if cur:
                if cur in paths:
                    disp.set(labels[paths.index(cur)])
                else:
                    bn = os.path.basename(cur)
                    matched = next((lb for p, lb in self.mp3_items
                                    if os.path.basename(p) == bn), None)
                    disp.set(matched or bn)
            cb = ttk.Combobox(step["val_holder"], textvariable=disp,
                              state="readonly", width=24,
                              values=labels or ["(assets/mp3 비어있음)"])

            def on_sel(e, s=step, ps=paths, ls=labels, d=disp):
                if d.get() in ls:
                    s["val_var"].set(ps[ls.index(d.get())])
                    self._autosave()
            cb.bind("<<ComboboxSelected>>", on_sel)
            cb.pack(side="left")
        elif kind == snd.TTS:
            ent = tk.Entry(step["val_holder"], textvariable=step["val_var"],
                           width=24)
            ent.pack(side="left")
            ent.bind("<FocusOut>", lambda e: self._autosave())
        elif kind == snd.RANDOM:
            step["val_var"].set("")
            tk.Label(step["val_holder"], text="🎲 랜덤 로봇음 (다양한 소리)",
                     width=24, anchor="w", fg="#6a1b9a",
                     bg="#fbfcff").pack(side="left")
        else:
            step["val_var"].set("")
            tk.Label(step["val_holder"], text="(사운드 없음)", width=24,
                     anchor="w", fg="#999", bg="#fbfcff").pack(side="left")

    # ---------- 저장 ----------
    def _step_motion_num(self, step):
        t = step["motion_var"].get()
        if t and t != NONE_MOTION and " - " in t:
            try:
                return int(t.split(" - ")[0])
            except Exception:
                return None
        return None

    def _collect(self) -> dict:
        result = {}
        for g in self.groups:
            steps = []
            for st in g["steps"]:
                motion = self._step_motion_num(st)
                kind = st["sound_var"].get() or snd.NONE
                val = st["val_var"].get().strip()
                if motion is None and kind == snd.NONE:
                    continue
                entry = {"motion": motion, "sound_kind": kind,
                         "sound_value": val}
                t = st["dur_var"].get().strip()
                if t:
                    try:
                        d = float(t)
                        if d > 0:
                            entry["duration"] = d
                    except Exception:
                        pass
                try:
                    rep = int(st["repeat_var"].get())
                    if rep > 1:
                        entry["repeat"] = rep
                except Exception:
                    pass
                cond = COND_LABEL2KEY.get(st["cond_var"].get(), "always")
                if cond != "always":
                    entry["cond"] = cond
                steps.append(entry)
            if steps:
                result[g["obj"]] = {"steps": steps}
        return result

    def _autosave(self):
        self.mapping = self._collect()
        save_actions(self.mapping)

    def _save(self):
        self._autosave()
        messagebox.showinfo("저장",
                            f"{len(self.mapping)}개 객체 반응을 저장했습니다.")
