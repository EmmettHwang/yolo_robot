# coding: utf-8
"""
sim_preview.py
==============
블록 코딩 탭의 '실시간 미리보기 + 로봇 시뮬레이션' 패널.

- 왼쪽: 자율활동 엔진(RecognitionView)이 잡고 있는 카메라 프레임 + 인식 박스를
  그대로 미러링(엔진을 공유하므로 카메라/시리얼 충돌 없음).
- 오른쪽: 캔버스로 그린 휴머노이드 로봇이, 방금 인식이 실행한 동작 시퀀스를
  단계별로 따라 움직이며 '시뮬레이션' 한다.
- 반응(로봇 제어)은 엔진의 워커 스레드가 실제로 수행 → 카메라·로봇 모두 동작.
"""

import math
import time

import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

import hangul
import sound as snd
from motion_table import (
    coco_kr, motion_name, PWR_ON, PWR_OFF, VOICE_CHAT,
    FORWARD_SEQUENCE, BACKWARD_SEQUENCE,
)
from recognition_view import _read_config

CAM_W, CAM_H = 384, 288
AV_W, AV_H = 250, 288


def _sound_text(kind, val):
    if kind == snd.MP3:
        import os
        return "🎵 " + (os.path.basename(val) if val else "mp3")
    if kind == snd.TTS:
        return "🗣 " + (val or "")
    if kind == snd.RANDOM:
        return "🎲 랜덤음"
    return ""


def _motion_text(m):
    if m is None:
        return "(모션 없음)"
    if m == PWR_ON:
        return "전원 켜기"
    if m == PWR_OFF:
        return "전원 끄기"
    if m == VOICE_CHAT:
        return "음성 대화"
    return motion_name(int(m))


def _category(m):
    if m == PWR_ON:
        return "rise"
    if m == PWR_OFF:
        return "sit"
    if m == VOICE_CHAT:
        return "talk"
    if m in FORWARD_SEQUENCE or m in BACKWARD_SEQUENCE:
        return "walk"
    if m is None:
        return "idle"
    return "gesture"


class SimPreview(ttk.Frame):
    def __init__(self, master, rec_view, **kw):
        super().__init__(master, **kw)
        self.rec = rec_view
        self.active = False
        self._after = None
        self._imgtk = None
        self._phase = 0.0
        self._seen_react = 0
        # 진행 중 시뮬레이션 상태
        self._seq = []
        self._seq_label = ""
        self._idx = -1
        self._step_start = 0.0
        self._step_dur = 0.0
        self._build()
        self._draw_avatar()

    # ============================================================
    # UI
    # ============================================================
    def _build(self):
        head = tk.Frame(self); head.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(head, text="🎥 실시간 미리보기 + 🤖 로봇 시뮬레이션",
                 font=("Malgun Gothic", 11, "bold")).pack(side="left")
        self.btn = tk.Button(head, text="▶ 미리보기 시작", bg="#28a745",
                             fg="white", relief="flat", cursor="hand2",
                             font=("Malgun Gothic", 9, "bold"),
                             command=self._toggle)
        self.btn.pack(side="right")
        self.status = tk.Label(head, text="⚪ 대기", font=("Malgun Gothic", 10,
                                                          "bold"), fg="#888")
        self.status.pack(side="right", padx=10)

        body = tk.Frame(self); body.pack(fill="x", padx=8, pady=(0, 4))

        # 왼쪽: 카메라 미러
        camwrap = tk.Frame(body); camwrap.pack(side="left")
        self.cam = tk.Canvas(camwrap, width=CAM_W, height=CAM_H, bg="#111",
                             highlightthickness=0)
        self.cam.pack()
        self.cam_img = self.cam.create_image(CAM_W // 2, CAM_H // 2,
                                             anchor="center")
        self.cam_hint = self.cam.create_text(
            CAM_W // 2, CAM_H // 2, fill="#888", font=("Malgun Gothic", 11),
            text="▶ 미리보기 시작 (포트·카메라 설정 필요)")
        self.lbl_obj = tk.Label(camwrap, text="인식: -", anchor="w",
                                font=("Malgun Gothic", 10, "bold"),
                                fg="#1565c0")
        self.lbl_obj.pack(fill="x", pady=(2, 0))

        # 오른쪽: 로봇 아바타 + 동작 정보
        avwrap = tk.Frame(body); avwrap.pack(side="left", fill="both",
                                             expand=True, padx=(10, 0))
        inner = tk.Frame(avwrap); inner.pack()
        self.av = tk.Canvas(inner, width=AV_W, height=AV_H, bg="#eef3fb",
                            highlightthickness=1,
                            highlightbackground="#cdd8ea")
        self.av.pack(side="left")
        info = tk.Frame(inner); info.pack(side="left", fill="both",
                                         expand=True, padx=(8, 0))
        self.lbl_now = tk.Label(info, text="대기 중", anchor="w",
                                justify="left", font=("Malgun Gothic", 12,
                                                      "bold"), fg="#263b66")
        self.lbl_now.pack(fill="x")
        self.lbl_sound = tk.Label(info, text="", anchor="w", justify="left",
                                  font=("Malgun Gothic", 10), fg="#6a1b9a")
        self.lbl_sound.pack(fill="x", pady=(2, 6))
        tk.Label(info, text="동작 시퀀스", anchor="w", fg="#888",
                 font=("Malgun Gothic", 9, "bold")).pack(fill="x")
        self.lbl_steps = tk.Label(info, text="-", anchor="nw", justify="left",
                                  font=("Consolas", 10), fg="#445")
        self.lbl_steps.pack(fill="both", expand=True)

    # ============================================================
    # 로봇 아바타(캔버스 도형)
    # ============================================================
    def _draw_avatar(self):
        c = self.av
        cx = AV_W // 2
        # 바닥 그림자
        c.create_oval(cx - 60, AV_H - 26, cx + 60, AV_H - 8,
                      fill="#d3deef", outline="")
        # 다리
        self.leg_l = c.create_line(cx - 16, 190, cx - 20, 248, width=14,
                                   fill="#5b6b86", capstyle="round")
        self.leg_r = c.create_line(cx + 16, 190, cx + 20, 248, width=14,
                                   fill="#5b6b86", capstyle="round")
        # 몸통
        self.body = c.create_rectangle(cx - 34, 96, cx + 34, 196,
                                       fill="#3f6bd6", outline="#274a9c",
                                       width=2)
        self.chest = c.create_oval(cx - 12, 120, cx + 12, 148,
                                   fill="#9fc1ff", outline="")
        # 팔
        self.arm_l = c.create_line(cx - 34, 108, cx - 64, 150, width=12,
                                   fill="#3f6bd6", capstyle="round")
        self.arm_r = c.create_line(cx + 34, 108, cx + 64, 150, width=12,
                                   fill="#3f6bd6", capstyle="round")
        # 머리
        self.head = c.create_oval(cx - 26, 44, cx + 26, 96, fill="#dfe8fb",
                                  outline="#9fb0d0", width=2)
        self.eye_l = c.create_oval(cx - 15, 62, cx - 5, 72, fill="#263b66",
                                   outline="")
        self.eye_r = c.create_oval(cx + 5, 62, cx + 15, 72, fill="#263b66",
                                   outline="")
        self.mouth = c.create_line(cx - 8, 84, cx + 8, 84, width=2,
                                   fill="#7a4")
        # 상태 LED
        self.led = c.create_oval(cx - 6, 30, cx + 6, 42, fill="#bbb",
                                 outline="")
        self._av_cx = cx
        self._pose_idle(0.0)

    def _set_arm(self, item, sx, sy, hx, hy):
        self.av.coords(item, sx, sy, hx, hy)

    def _pose_idle(self, t):
        cx = self._av_cx
        bob = math.sin(t * 2) * 1.5
        self.av.coords(self.head, cx - 26, 44 + bob, cx + 26, 96 + bob)
        self.av.coords(self.eye_l, cx - 15, 62 + bob, cx - 5, 72 + bob)
        self.av.coords(self.eye_r, cx + 5, 62 + bob, cx + 15, 72 + bob)
        self.av.coords(self.mouth, cx - 8, 84 + bob, cx + 8, 84 + bob)
        self._set_arm(self.arm_l, cx - 34, 108, cx - 60, 156)
        self._set_arm(self.arm_r, cx + 34, 108, cx + 60, 156)
        self.av.coords(self.leg_l, cx - 16, 190, cx - 20, 248)
        self.av.coords(self.leg_r, cx + 16, 190, cx + 20, 248)
        self.av.itemconfig(self.led, fill="#9fd49f")

    def _pose(self, category, t, progress):
        cx = self._av_cx
        s = math.sin(t * 6)
        self.av.itemconfig(self.led, fill="#ffd54f")
        if category == "gesture":               # 양팔 흔들기
            up = (0.5 + 0.5 * s) * 60
            self._set_arm(self.arm_l, cx - 34, 108, cx - 64, 150 - up)
            self._set_arm(self.arm_r, cx + 34, 108, cx + 64, 150 - up)
        elif category == "walk":                 # 다리/팔 교차
            sw = s * 16
            self.av.coords(self.leg_l, cx - 16, 190, cx - 20 + sw, 248)
            self.av.coords(self.leg_r, cx + 16, 190, cx + 20 - sw, 248)
            self._set_arm(self.arm_l, cx - 34, 108, cx - 60, 156 - sw)
            self._set_arm(self.arm_r, cx + 34, 108, cx + 60, 156 + sw)
        elif category == "talk":                 # 고개 끄덕 + 입 움직임
            nod = abs(s) * 4
            self.av.coords(self.head, cx - 26, 44 + nod, cx + 26, 96 + nod)
            self.av.coords(self.eye_l, cx - 15, 62 + nod, cx - 5, 72 + nod)
            self.av.coords(self.eye_r, cx + 5, 62 + nod, cx + 15, 72 + nod)
            my = 84 + nod + (2 if s > 0 else -2)
            self.av.coords(self.mouth, cx - 8, my, cx + 8, my + abs(s) * 3)
        elif category in ("rise", "sit"):        # 일어서기 / 앉기
            p = progress if category == "rise" else (1 - progress)
            dy = (1 - p) * 34                     # 1=서있음, 0=앉음
            self.av.coords(self.body, cx - 34, 96 + dy, cx + 34, 196 + dy)
            self.av.coords(self.head, cx - 26, 44 + dy, cx + 26, 96 + dy)
            self.av.coords(self.eye_l, cx - 15, 62 + dy, cx - 5, 72 + dy)
            self.av.coords(self.eye_r, cx + 5, 62 + dy, cx + 15, 72 + dy)
            self.av.coords(self.mouth, cx - 8, 84 + dy, cx + 8, 84 + dy)
            self._set_arm(self.arm_l, cx - 34, 108 + dy, cx - 60, 156 + dy)
            self._set_arm(self.arm_r, cx + 34, 108 + dy, cx + 60, 156 + dy)
            knee = dy * 0.5
            self.av.coords(self.leg_l, cx - 16, 190 + dy, cx - 26, 248 - knee)
            self.av.coords(self.leg_r, cx + 16, 190 + dy, cx + 26, 248 - knee)
        else:
            self._pose_idle(t)

    # ============================================================
    # 시작 / 정지
    # ============================================================
    def _toggle(self):
        if self.active:
            self.stop()
        else:
            self.start()

    def start(self):
        self.active = True
        self.btn.config(text="■ 미리보기 정지", bg="#c62828")
        self._ensure_engine()
        if self._after is None:
            self._tick()

    def stop(self):
        # 미리보기(렌더)만 멈춘다. 엔진(반응)은 백그라운드로 계속 동작.
        self.active = False
        self.btn.config(text="▶ 미리보기 시작", bg="#28a745")
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        self.status.config(text="⚪ 대기", fg="#888")

    def _ensure_engine(self):
        """엔진(RecognitionView)이 안 돌고 있으면, 포트가 설정된 경우 시작."""
        try:
            if self.rec.running:
                return
            port, _cam = _read_config()
            if not port:
                self.cam.itemconfig(
                    self.cam_hint,
                    text="포트가 설정되지 않았습니다.\n① 로봇장치설정에서 포트를 먼저 선택하세요.")
                self.cam.itemconfig(self.cam_img, state="hidden")
                return
            self.rec.start()
        except Exception:
            pass

    # ============================================================
    # 루프
    # ============================================================
    def _tick(self):
        if not self.active:
            self._after = None
            return
        self._phase += 0.12
        try:
            self._mirror_camera()
            self._check_reaction()
            self._animate()
        except Exception:
            pass
        self._after = self.after(50, self._tick)

    def _mirror_camera(self):
        rec = self.rec
        with rec._lock:
            frame = None if rec._frame is None else rec._frame.copy()
            dets = rec._dets
        if frame is None or rec.model is None:
            return
        self.cam.itemconfig(self.cam_hint, state="hidden")
        self.cam.itemconfig(self.cam_img, state="normal")
        top_label, top_conf, top_id = "", 0.0, -1
        hud = []
        for det in dets:
            x1, y1, x2, y2 = (int(det[0]), int(det[1]), int(det[2]),
                              int(det[3]))
            conf = float(det[4]); cid = int(det[5])
            try:
                name = rec.model.names[cid]
            except Exception:
                name = str(cid)
            kr = coco_kr(name)
            tag = f"{name}" + (f"({kr})" if kr else "")
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
            hud.append(hangul.outlined(f"{tag} {conf*100:.0f}%",
                                       (x1 + 2, max(0, y1 - 20)), 15,
                                       color=(0, 0, 0),
                                       outline=(255, 255, 255)))
            if conf > top_conf:
                top_conf = conf; top_label = name; top_id = cid
        frame = hangul.draw_texts(frame, hud)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        scale = min(CAM_W / w, CAM_H / h)
        rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))
        self._imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.cam.itemconfig(self.cam_img, image=self._imgtk)
        if top_label:
            kr = coco_kr(top_label)
            self.lbl_obj.config(
                text=f"인식: {top_label}" + (f" ({kr})" if kr else "")
                     + f"  {top_conf*100:.0f}%")
        else:
            self.lbl_obj.config(text="인식: -")

    def _check_reaction(self):
        """엔진이 새 반응을 실행했으면 시뮬레이션 시퀀스를 시작."""
        rid = getattr(self.rec, "_react_id", 0)
        if rid != self._seen_react:
            self._seen_react = rid
            self._seq = list(getattr(self.rec, "_last_seq", []))
            self._seq_label = getattr(self.rec, "_last_seq_label", "")
            self._idx = 0 if self._seq else -1
            self._begin_step()

    def _begin_step(self):
        if 0 <= self._idx < len(self._seq):
            st = self._seq[self._idx]
            self._step_start = time.time()
            hold = st.get("hold")
            self._step_dur = float(hold) if hold else 1.5
            self.status.config(text="🟢 동작 중", fg="#2e7d32")
        else:
            self.status.config(text="⚪ 대기", fg="#888")

    def _animate(self):
        now = time.time()
        if 0 <= self._idx < len(self._seq):
            st = self._seq[self._idx]
            dur = max(0.3, self._step_dur)
            progress = min(1.0, (now - self._step_start) / dur)
            cat = _category(st.get("motion"))
            self._pose(cat, self._phase, progress)
            self.lbl_now.config(
                text=f"▶ #{self._idx + 1}/{len(self._seq)}  "
                     f"{_motion_text(st.get('motion'))}")
            self.lbl_sound.config(
                text=_sound_text(st.get("sound_kind", snd.NONE),
                                 st.get("sound_value", "")))
            self._render_steps()
            if now - self._step_start >= dur:        # 다음 단계로
                self._idx += 1
                self._begin_step()
                if self._idx >= len(self._seq):
                    self.lbl_now.config(text="대기 중")
                    self.lbl_sound.config(text="")
        else:
            self._pose_idle(self._phase)

    def _render_steps(self):
        lines = []
        for i, st in enumerate(self._seq):
            mark = "▶" if i == self._idx else " "
            snd_t = _sound_text(st.get("sound_kind", snd.NONE),
                                st.get("sound_value", ""))
            extra = f"  {snd_t}" if snd_t else ""
            lines.append(f"{mark} {i + 1}. {_motion_text(st.get('motion'))}"
                         f"{extra}")
        kr = coco_kr(self._seq_label)
        title = self._seq_label + (f" ({kr})" if kr else "")
        self.lbl_steps.config(text=f"[{title}]\n" + "\n".join(lines))
