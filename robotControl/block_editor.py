# coding: utf-8
"""
block_editor.py
===============
블록 코딩 (캔버스 드래그형, 스크래치 느낌).

- 블록 1개 = 액션스크립터의 스텝 1개(동작+사운드+지속+🔁반복+❓조건)에 1:1 대응.
- 객체마다 '햇 블록(객체 인식)' 아래로 동작 블록을 세로로 쌓는다.
- 블록의 ≡ 손잡이를 잡고 **드래그**하면 순서/소속 객체를 바꾼다.
- 블록을 **더블클릭**하면 상세 편집 팝업이 열린다.
- 모든 변경은 object_actions JSON 으로 저장 → 액션스크립터/파이썬 탭과 즉시 공유.
"""

import os
import tkinter as tk
from tkinter import ttk

import sound as snd
import mp3_library
import object_actions
from object_actions import (
    NONE_MOTION, MAX_STEPS, CONDITIONS, COND_KEY2LABEL, COND_LABEL2KEY,
    obj_label, steps_of, load_actions, save_actions,
)
from motion_table import (
    ALL_MOTIONS, motion_label, COCO_CLASSES, coco_kr,
    PWR_ON, PWR_OFF, VOICE_CHAT,
)

# 레이아웃(px)
MARGIN = 16
COL_W = 246
COL_GAP = 22
HAT_H = 46
BLK_H = 78
BLK_GAP = 10
SLOT = BLK_H + BLK_GAP

# 블록 색(본문 / 좌측 띠)
_C_NORMAL = ("#e7f1ff", "#1565c0")
_C_POWER = ("#fff1e2", "#ef6c00")
_C_VOICE = ("#f4e9ff", "#6a1b9a")
_C_EMPTY = ("#eef1f5", "#90a4ae")


def _motion_values():
    return ([NONE_MOTION]
            + [motion_label(n) for n in ALL_MOTIONS]
            + [motion_label(PWR_ON), motion_label(PWR_OFF),
               motion_label(VOICE_CHAT)])


def _parse_motion(text):
    if text and text != NONE_MOTION and " - " in text:
        try:
            return int(text.split(" - ")[0])
        except Exception:
            return None
    return None


def _blank_step():
    return {"motion": None, "sound_kind": snd.NONE, "sound_value": "",
            "duration": None, "repeat": 1, "cond": "always"}


def _fmt_num(n):
    f = float(n)
    return str(int(f)) if f == int(f) else str(f)


def _block_colors(motion):
    if motion in (PWR_ON, PWR_OFF):
        return _C_POWER
    if motion == VOICE_CHAT:
        return _C_VOICE
    if motion is None:
        return _C_EMPTY
    return _C_NORMAL


def _motion_text(motion):
    if motion is None:
        return "동작 없음"
    if motion == PWR_ON:
        return "⚡ 전원 켜기"
    if motion == PWR_OFF:
        return "⚡ 전원 끄기"
    if motion == VOICE_CHAT:
        return "🎤 음성 대화"
    return "🤸 " + motion_label(int(motion))


def _sound_text(kind, val):
    if kind == snd.MP3:
        return "🎵 " + (os.path.basename(val) if val else "(mp3 미선택)")
    if kind == snd.TTS:
        return "🗣 " + (f'"{val}"' if val else "(읽을 말 없음)")
    if kind == snd.RANDOM:
        return "🎲 랜덤 로봇음"
    return "🔇 사운드 없음"


def _extra_text(step):
    parts = []
    rep = int(step.get("repeat", 1) or 1)
    if rep > 1:
        parts.append(f"🔁 {rep}회")
    dur = step.get("duration")
    if dur:
        parts.append(f"⏱ {_fmt_num(dur)}s")
    cond = step.get("cond", "always")
    if cond and cond != "always":
        parts.append("❓ " + COND_KEY2LABEL.get(cond, cond))
    return "   ".join(parts)


class BlockEditor(ttk.Frame):
    def __init__(self, master, on_change=None, **kw):
        super().__init__(master, **kw)
        self.on_change = on_change
        self.program = {}              # {label: [step, ...]}
        self.mp3_items = mp3_library.list_mp3()
        self._blocks = []              # 화면 블록 메타
        self._stacks = []              # 스택 기하(드롭 계산용)
        self._drag = None
        self._build()
        self.reload()

    # ============================================================
    # UI
    # ============================================================
    def _build(self):
        bar = tk.Frame(self); bar.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(bar, text="🧩 블록 코딩", font=("Malgun Gothic", 13, "bold")
                 ).pack(side="left")
        tk.Label(bar, text="  ≡ 드래그=순서·객체 이동 · ✎ 편집(또는 더블클릭)",
                 font=("Malgun Gothic", 9), fg="#888").pack(side="left")

        tk.Label(bar, text="객체 추가:", font=("Malgun Gothic", 9)).pack(
            side="left", padx=(16, 2))
        self.add_var = tk.StringVar()
        self.add_combo = ttk.Combobox(bar, textvariable=self.add_var,
                                      state="readonly", width=20)
        self.add_combo.pack(side="left", padx=(0, 4))
        tk.Button(bar, text="＋ 객체", bg="#1565c0", fg="white", relief="flat",
                  cursor="hand2", command=self._add_object).pack(side="left")
        tk.Button(bar, text="↻ 새로고침", cursor="hand2",
                  command=self.reload).pack(side="left", padx=(8, 0))

        wrap = tk.Frame(self); wrap.pack(fill="both", expand=True,
                                         padx=8, pady=(0, 8))
        self.canvas = tk.Canvas(wrap, bg="#f7f9fc", highlightthickness=0)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        xsb = ttk.Scrollbar(wrap, orient="horizontal",
                            command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(
                             -1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Shift-MouseWheel>",
                         lambda e: self.canvas.xview_scroll(
                             -1 if e.delta > 0 else 1, "units"))

    # ============================================================
    # 데이터
    # ============================================================
    def reload(self):
        """JSON을 다시 읽어 블록을 재구성(다른 탭 변경 반영)."""
        self.mp3_items = mp3_library.list_mp3()
        mapping = load_actions()
        self.program = {lbl: [dict(s) for s in steps_of(act)]
                        for lbl, act in mapping.items()}
        self._refresh_add_combo()
        self.render()

    def _save(self):
        mapping = {}
        for lbl, steps in self.program.items():
            keep = [s for s in steps
                    if s.get("motion") is not None
                    or s.get("sound_kind", snd.NONE) != snd.NONE]
            if keep:
                mapping[lbl] = {"steps": keep}
        save_actions(mapping)
        if callable(self.on_change):
            try:
                self.on_change()
            except Exception:
                pass

    def _all_objects(self):
        base = list(COCO_CLASSES)
        for k in self.program:
            if k not in base:
                base.append(k)
        return base

    def _refresh_add_combo(self):
        base = self._all_objects()
        self._obj_num = {o: i + 1 for i, o in enumerate(base)}
        used = set(self.program)
        avail = [o for o in base if o not in used]
        self._disp_to_name = {obj_label(o, self._obj_num[o]): o for o in avail}
        vals = list(self._disp_to_name)
        self.add_combo["values"] = vals
        if vals:
            self.add_combo.current(0)
        else:
            self.add_var.set("(모든 객체 추가됨)")

    def _add_object(self):
        obj = self._disp_to_name.get(self.add_var.get().strip())
        if not obj or obj in self.program:
            return
        self.program[obj] = [_blank_step()]
        self._refresh_add_combo()
        self.render()
        self._save()

    def _add_step(self, label):
        steps = self.program.get(label)
        if steps is None or len(steps) >= MAX_STEPS:
            return
        steps.append(_blank_step())
        self.render()
        self._save()

    def _del_step(self, label, idx):
        steps = self.program.get(label, [])
        if 0 <= idx < len(steps):
            steps.pop(idx)
        if not steps:                 # 스텝이 없으면 객체도 제거
            self.program.pop(label, None)
            self._refresh_add_combo()
        self.render()
        self._save()

    def _del_object(self, label):
        self.program.pop(label, None)
        self._refresh_add_combo()
        self.render()
        self._save()

    # ============================================================
    # 렌더링
    # ============================================================
    def render(self):
        for b in self._blocks:
            try:
                b["frame"].destroy()
            except Exception:
                pass
        self._blocks = []
        self._stacks = []
        self.canvas.delete("all")

        if not self.program:
            self.canvas.create_text(
                MARGIN + 220, 80, anchor="w", fill="#999",
                font=("Malgun Gothic", 12),
                text="위 ‘＋ 객체’로 객체를 추가하고, 블록을 쌓아 보세요.")
            self.canvas.configure(scrollregion=(0, 0, 600, 200))
            return

        max_h = 0
        for col, (label, steps) in enumerate(self.program.items()):
            x = MARGIN + col * (COL_W + COL_GAP)
            self._draw_hat(label, steps, x)
            first_y = MARGIN + HAT_H + BLK_GAP
            for j, step in enumerate(steps):
                self._draw_block(label, j, step, x, first_y + j * SLOT)
            add_y = first_y + len(steps) * SLOT
            self._draw_add(label, len(steps), x, add_y)
            self._stacks.append({"label": label, "x0": x, "first_y": first_y,
                                 "count": len(steps)})
            max_h = max(max_h, add_y + 40)

        total_w = MARGIN + len(self.program) * (COL_W + COL_GAP)
        self.canvas.configure(scrollregion=(0, 0, max(total_w, 600),
                                            max(max_h, 200)))

    def _draw_hat(self, label, steps, x):
        kr = coco_kr(label)
        name = f"{self._obj_num.get(label, '?')}. {label}" \
               + (f" ({kr})" if kr else "")
        fr = tk.Frame(self.canvas, bg="#263b66", bd=0,
                      highlightthickness=0)
        tk.Label(fr, text="🎯 " + name, bg="#263b66", fg="white",
                 font=("Malgun Gothic", 10, "bold")).pack(side="left",
                                                          padx=8, pady=6)
        tk.Button(fr, text="✕", bg="#263b66", fg="#ffb3b3", relief="flat",
                  cursor="hand2", bd=0,
                  command=lambda: self._del_object(label)).pack(
            side="right", padx=6)
        self.canvas.create_window(x, MARGIN, anchor="nw", window=fr,
                                  width=COL_W, height=HAT_H)
        self._blocks.append({"frame": fr})

    def _draw_block(self, label, idx, step, x, y):
        bg, stripe = _block_colors(step.get("motion"))
        fr = tk.Frame(self.canvas, bg=bg, bd=1, relief="solid",
                      highlightthickness=0)
        tk.Frame(fr, bg=stripe, width=6).pack(side="left", fill="y")
        body = tk.Frame(fr, bg=bg); body.pack(side="left", fill="both",
                                              expand=True)

        top = tk.Frame(body, bg=bg); top.pack(fill="x")
        handle = tk.Label(top, text="≡", bg=bg, fg="#555", cursor="fleur",
                          font=("Malgun Gothic", 12, "bold"))
        handle.pack(side="left", padx=(4, 2))
        tk.Label(top, text=f"#{idx + 1}", bg=bg, fg="#888",
                 font=("Consolas", 9, "bold")).pack(side="left")
        tk.Button(top, text="✕", bg=bg, fg="#c62828", relief="flat", bd=0,
                  cursor="hand2",
                  command=lambda: self._del_step(label, idx)).pack(
            side="right", padx=4)
        tk.Button(top, text="✎ 편집", bg="#1565c0", fg="white", relief="flat",
                  bd=0, cursor="hand2", font=("Malgun Gothic", 8, "bold"),
                  command=lambda: self._edit_step(label, idx)).pack(
            side="right", padx=2)

        tk.Label(body, text=_motion_text(step.get("motion")), bg=bg,
                 anchor="w", font=("Malgun Gothic", 10, "bold")).pack(
            fill="x", padx=8)
        tk.Label(body, text=_sound_text(step.get("sound_kind", snd.NONE),
                                        step.get("sound_value", "")),
                 bg=bg, anchor="w", fg="#445",
                 font=("Malgun Gothic", 9)).pack(fill="x", padx=8)
        extra = _extra_text(step)
        if extra:
            tk.Label(body, text=extra, bg=bg, anchor="w", fg="#6a1b9a",
                     font=("Malgun Gothic", 9, "bold")).pack(fill="x", padx=8)

        win = self.canvas.create_window(x, y, anchor="nw", window=fr,
                                        width=COL_W, height=BLK_H)
        meta = {"frame": fr, "win": win, "label": label, "idx": idx}
        self._blocks.append(meta)

        # 드래그(손잡이)
        handle.bind("<ButtonPress-1>",
                    lambda e, m=meta: self._drag_start(m))
        handle.bind("<B1-Motion>", lambda e: self._drag_move())
        handle.bind("<ButtonRelease-1>", lambda e: self._drag_drop())

        # 더블클릭(편집) — 블록 전체(라벨 포함, 버튼 제외)에 연결
        def _bind_dclick(widget):
            if not isinstance(widget, tk.Button):
                widget.bind("<Double-Button-1>",
                            lambda e, l=label, i=idx: self._edit_step(l, i))
            for ch in widget.winfo_children():
                _bind_dclick(ch)
        _bind_dclick(fr)

    def _draw_add(self, label, count, x, y):
        if count >= MAX_STEPS:
            return
        fr = tk.Frame(self.canvas, bg="#f7f9fc")
        tk.Button(fr, text="＋ 동작 블록", relief="flat", cursor="hand2",
                  fg="#1565c0", bg="#e3eefc",
                  font=("Malgun Gothic", 9, "bold"),
                  command=lambda: self._add_step(label)).pack(fill="x")
        self.canvas.create_window(x, y, anchor="nw", window=fr,
                                  width=COL_W, height=30)
        self._blocks.append({"frame": fr})

    # ============================================================
    # 드래그 앤 드롭
    # ============================================================
    def _pointer_canvas(self):
        px = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
        py = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
        return self.canvas.canvasx(px), self.canvas.canvasy(py)

    def _drag_start(self, meta):
        cx, cy = self._pointer_canvas()
        x0, y0 = self.canvas.coords(meta["win"])
        self._drag = {"meta": meta, "dx": cx - x0, "dy": cy - y0}
        self.canvas.tag_raise(meta["win"])
        try:
            meta["frame"].lift()
        except Exception:
            pass

    def _drag_move(self):
        if not self._drag:
            return
        cx, cy = self._pointer_canvas()
        self.canvas.coords(self._drag["meta"]["win"],
                           cx - self._drag["dx"], cy - self._drag["dy"])

    def _drag_drop(self):
        if not self._drag:
            return
        meta = self._drag["meta"]
        self._drag = None
        cx, cy = self._pointer_canvas()
        target = self._stack_at(cx)
        if target is None:               # 스택 밖 → 원위치
            self.render()
            return
        slot = max(0, round((cy - target["first_y"]) / SLOT))
        self._move_step(meta["label"], meta["idx"], target["label"], slot)

    def _stack_at(self, cx):
        best = None
        for s in self._stacks:
            cxc = s["x0"] + COL_W / 2
            if best is None or abs(cx - cxc) < abs(cx - (best["x0"]
                                                         + COL_W / 2)):
                best = s
        # 가장 가까운 스택이라도 너무 멀면 무시
        if best is not None and abs(cx - (best["x0"] + COL_W / 2)) > \
                (COL_W + COL_GAP):
            return None
        return best

    def _move_step(self, src_label, src_idx, dst_label, dst_slot):
        src = self.program.get(src_label, [])
        if not (0 <= src_idx < len(src)):
            self.render()
            return
        if dst_label == src_label:
            step = src.pop(src_idx)
            if dst_slot > src_idx:
                dst_slot -= 1
            dst_slot = max(0, min(dst_slot, len(src)))
            src.insert(dst_slot, step)
        else:
            dst = self.program.get(dst_label)
            if dst is None or len(dst) >= MAX_STEPS:
                self.render()
                return
            step = src.pop(src_idx)
            dst_slot = max(0, min(dst_slot, len(dst)))
            dst.insert(dst_slot, step)
            if not src:
                self.program.pop(src_label, None)
                self._refresh_add_combo()
        self.render()
        self._save()

    # ============================================================
    # 상세 편집 팝업
    # ============================================================
    def _edit_step(self, label, idx):
        steps = self.program.get(label, [])
        if not (0 <= idx < len(steps)):
            return
        step = steps[idx]
        dlg = tk.Toplevel(self)
        dlg.title(f"블록 편집 — {label} #{idx + 1}")
        dlg.configure(bg="white")
        dlg.transient(self.winfo_toplevel())
        dlg.resizable(False, False)

        grid = tk.Frame(dlg, bg="white"); grid.pack(padx=16, pady=14)

        def row(r, text):
            tk.Label(grid, text=text, bg="white", anchor="e", width=8,
                     font=("Malgun Gothic", 10)).grid(row=r, column=0,
                                                      sticky="e", pady=4)

        # 동작
        row(0, "동작")
        mv = tk.StringVar(value=(motion_label(int(step["motion"]))
                                 if step.get("motion") else NONE_MOTION))
        ttk.Combobox(grid, textvariable=mv, state="readonly", width=26,
                     values=_motion_values()).grid(row=0, column=1,
                                                   sticky="w", pady=4)
        # 사운드
        row(1, "사운드")
        sv = tk.StringVar(value=step.get("sound_kind", snd.NONE))
        sc = ttk.Combobox(grid, textvariable=sv, state="readonly", width=26,
                          values=[k for k, _ in snd.KINDS])
        sc.grid(row=1, column=1, sticky="w", pady=4)
        # 값(동적)
        row(2, "값")
        val_holder = tk.Frame(grid, bg="white")
        val_holder.grid(row=2, column=1, sticky="w", pady=4)
        val_var = tk.StringVar(value=step.get("sound_value", ""))
        mp3_disp = tk.StringVar()

        def rebuild_value(*_a):
            for w in val_holder.winfo_children():
                w.destroy()
            kind = sv.get()
            if kind == snd.MP3:
                labels = [lb for _, lb in self.mp3_items]
                paths = [p for p, _ in self.mp3_items]
                cur = val_var.get()
                if cur and cur in paths:
                    mp3_disp.set(labels[paths.index(cur)])
                cb = ttk.Combobox(val_holder, textvariable=mp3_disp,
                                  state="readonly", width=24,
                                  values=labels or ["(assets/mp3 비어있음)"])
                cb.pack(side="left")

                def on_sel(_e):
                    if mp3_disp.get() in labels:
                        val_var.set(paths[labels.index(mp3_disp.get())])
                cb.bind("<<ComboboxSelected>>", on_sel)
            elif kind == snd.TTS:
                tk.Entry(val_holder, textvariable=val_var, width=26).pack(
                    side="left")
            elif kind == snd.RANDOM:
                val_var.set("")
                tk.Label(val_holder, text="🎲 랜덤 로봇음", bg="white",
                         fg="#6a1b9a").pack(side="left")
            else:
                val_var.set("")
                tk.Label(val_holder, text="(사운드 없음)", bg="white",
                         fg="#999").pack(side="left")
        sc.bind("<<ComboboxSelected>>", rebuild_value)
        rebuild_value()

        # 지속
        row(3, "지속(초)")
        dur = step.get("duration")
        dv = tk.StringVar(value=(_fmt_num(dur) if dur else ""))
        tk.Entry(grid, textvariable=dv, width=8).grid(row=3, column=1,
                                                      sticky="w", pady=4)
        # 반복
        row(4, "🔁 반복")
        rv = tk.IntVar(value=int(step.get("repeat", 1) or 1))
        tk.Spinbox(grid, from_=1, to=10, width=4, textvariable=rv).grid(
            row=4, column=1, sticky="w", pady=4)
        # 조건
        row(5, "❓ 만약")
        cvar = tk.StringVar(value=COND_KEY2LABEL.get(
            step.get("cond", "always"), "항상"))
        ttk.Combobox(grid, textvariable=cvar, state="readonly", width=18,
                     values=[lb for _, lb in CONDITIONS]).grid(
            row=5, column=1, sticky="w", pady=4)

        def apply_and_close():
            step["motion"] = _parse_motion(mv.get())
            step["sound_kind"] = sv.get() or snd.NONE
            step["sound_value"] = val_var.get().strip()
            t = dv.get().strip()
            try:
                step["duration"] = float(t) if t and float(t) > 0 else None
            except Exception:
                step["duration"] = None
            try:
                step["repeat"] = max(1, int(rv.get()))
            except Exception:
                step["repeat"] = 1
            step["cond"] = COND_LABEL2KEY.get(cvar.get(), "always")
            dlg.destroy()
            self.render()
            self._save()

        btns = tk.Frame(dlg, bg="white"); btns.pack(pady=(0, 14))
        tk.Button(btns, text="저장", bg="#28a745", fg="white", relief="flat",
                  cursor="hand2", width=8, font=("Malgun Gothic", 10, "bold"),
                  command=apply_and_close).pack(side="left", padx=6)
        tk.Button(btns, text="취소", cursor="hand2", width=8,
                  command=dlg.destroy).pack(side="left", padx=6)

        dlg.update_idletasks()
        try:
            px = self.winfo_toplevel().winfo_rootx() + 120
            py = self.winfo_toplevel().winfo_rooty() + 120
            dlg.geometry(f"+{px}+{py}")
            dlg.grab_set()
        except Exception:
            pass
