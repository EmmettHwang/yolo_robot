# coding: utf-8
"""
recognition_view.py
===================
인식 화면 (tkinter). 상단=카메라+YOLO, 하단=메뉴/디스플레이 + 조이스틱 + 4×4 그리드.

- 카메라/추론은 백그라운드 스레드, 화면 갱신은 tk after 루프 → UI 안 멈춤.
- 인식 트리거: 가장 confidence 높은 1개, 직전 동작 객체와 같으면 무시, 쿨다운.
- 객체→동작/사운드 매핑(object_actions)으로 모션 전송 + 사운드.
- 조이스틱(8방향)/그리드(4×4) 수동 조작.
- 로봇 연결 끊김 감지 → 알림 후 정지.
"""

import os
import json
import time
import threading
import configparser

import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

import hangul
import yolo as yolo_mod
import sound as snd
import object_actions
from motion_table import coco_kr
from paths import CONFIG_INI, DATA_DIR
from robot_controller import HumanoidRobot
from motion import MotionRunner
from motion_table import FORWARD_SEQUENCE, BACKWARD_SEQUENCE

CONF_THRESHOLD = 0.60
INFER_EVERY = 2
INFER_SIZE = 320
PING_EVERY = 30
TRIGGER_COOLDOWN = 4.0      # 같은 트리거 반복 방지(초)

# 조이스틱 방향 → 모션 시퀀스 (홀드 시 500ms 간격 반복)
DIR_SEQ = {
    "N": FORWARD_SEQUENCE, "S": BACKWARD_SEQUENCE,
    "W": [5], "E": [6], "NW": [12], "NE": [13], "SW": [7], "SE": [8],
}


REC_SETTINGS = os.path.join(DATA_DIR, "rec_settings.json")


def _load_rec_settings():
    try:
        with open(REC_SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_rec_settings(conf, max_det):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(REC_SETTINGS, "w", encoding="utf-8") as f:
            json.dump({"conf": conf, "max_det": max_det}, f)
    except Exception:
        pass


def _clock(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "--:--:--"


def _dur(sec):
    sec = int(max(0, sec))
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def _read_config():
    cfg = configparser.ConfigParser()
    try:
        cfg.read(CONFIG_INI, encoding="utf-8")
        s = cfg["SETTINGS"]
        port = s.get("last_port") or None
        cam = s.get("last_camera_index")
        cam = int(cam) if cam not in (None, "") else 0
        return port, cam
    except Exception:
        return None, 0


class RecognitionView(ttk.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.robot = None
        self.model = None
        self.model_label = "-"
        self._pre_model = None        # app에서 미리 로드해 넘겨준 모델
        self._pre_label = None
        self.cap = None
        self.runner = None
        self.player = snd.player
        self.mapping = object_actions.load_actions()

        self.yolo_on = True
        self.sound_on = True
        _s = _load_rec_settings()                # 저장된 신뢰도/개수 복원
        self.conf_threshold = float(_s.get("conf", CONF_THRESHOLD))
        self.max_det = int(_s.get("max_det", 10))
        self.auto_start = tk.BooleanVar(master=self, value=True)  # 탭 열면 자동 시작
        self.running = False
        self._lock = threading.Lock()
        self._frame = None
        self._dets = np.empty((0, 6))
        self._disconnected = False
        self._disc_shown = False        # 끊김 알림 1회만
        self._worker = None
        self._after_id = None
        self._imgtk = None
        self._fcount = 0
        self._last_acted = ""
        self._last_trigger = 0.0
        self._empty = 0
        # 인식 지속시간 추적
        self._cur_obj = ""
        self._cur_start = 0.0
        self._prev_obj = ""
        self._prev_start = 0.0
        self._prev_dur = 0.0

        self._build()

    # ============================================================
    # UI
    # ============================================================
    def _build(self):
        # 상단: 카메라
        self.canvas = tk.Canvas(self, width=640, height=400, bg="#111111",
                                highlightthickness=0, cursor="hand2")
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.img_id = self.canvas.create_image(320, 200, anchor="center")
        self.canvas.create_text(320, 200,
                                text="‘연결 & 시작’을 누르세요 (자동 시작은 우측 체크박스)",
                                fill="#888", font=("Malgun Gothic", 12),
                                tags="hint")

        # 하단 패널
        panel = ttk.LabelFrame(self, text="  제어 / 디스플레이  ")
        panel.pack(fill="x", padx=6, pady=(0, 6))

        # --- 상단 컨트롤 줄 ---
        ctrl = tk.Frame(panel); ctrl.pack(fill="x", padx=8, pady=6)
        self.start_btn = tk.Button(
            ctrl, text="▶ 연결 & 시작", bg="#28a745", fg="white",
            relief="flat", cursor="hand2", font=("Malgun Gothic", 10, "bold"),
            command=self.toggle_start)
        self.start_btn.pack(side="left")
        self.yolo_btn = tk.Button(
            ctrl, text="YOLO: ON", width=10, cursor="hand2",
            command=self._toggle_yolo)
        self.yolo_btn.pack(side="left", padx=(8, 0))
        self.sound_btn = tk.Button(
            ctrl, text="사운드: ON", width=10, cursor="hand2",
            command=self._toggle_sound)
        self.sound_btn.pack(side="left", padx=(8, 0))
        self.stop_btn = tk.Button(
            ctrl, text="■ 동작 정지", width=10, cursor="hand2",
            bg="#ef6c00", fg="white", relief="flat",
            command=self._stop_motion)
        self.stop_btn.pack(side="left", padx=(8, 0))
        tk.Button(ctrl, text="🎛 로봇 제어", width=10, cursor="hand2",
                  bg="#6a1b9a", fg="white", relief="flat",
                  command=self._open_control_panel).pack(side="left", padx=(8, 0))
        # 매핑 새로고침 + 자동 시작은 줄 오른쪽 끝으로
        ttk.Button(ctrl, text="↻ 매핑 새로고침", cursor="hand2",
                   command=self._reload_mapping).pack(side="right")
        tk.Checkbutton(ctrl, text="자동 시작", variable=self.auto_start,
                       font=("Malgun Gothic", 9)).pack(side="right", padx=(0, 8))

        # --- 둘째 줄: 신뢰도 임계값 / 최대 인식 개수 (위아래로 크게) ---
        ctrl2 = tk.Frame(panel); ctrl2.pack(fill="x", padx=8, pady=(2, 8))
        tk.Label(ctrl2, text="신뢰도≥", font=("Malgun Gothic", 11, "bold")).pack(
            side="left", pady=8)
        self._conf_var = tk.DoubleVar(master=self, value=self.conf_threshold)
        self._conf_lbl = tk.Label(ctrl2, text=f"{self.conf_threshold:.2f}",
                                  width=5, font=("Consolas", 13, "bold"),
                                  fg="#1565c0")

        def _on_conf(v):
            self.conf_threshold = float(v)
            self._conf_lbl.config(text=f"{self.conf_threshold:.2f}")
            _save_rec_settings(self.conf_threshold, self.max_det)
        tk.Scale(ctrl2, from_=0.10, to=0.95, resolution=0.05,
                 orient="horizontal", variable=self._conf_var, showvalue=False,
                 length=240, width=26, sliderlength=34,
                 command=_on_conf).pack(side="left", pady=4)
        self._conf_lbl.pack(side="left", padx=(4, 16))
        tk.Label(ctrl2, text="최대 개수", font=("Malgun Gothic", 11, "bold")).pack(
            side="left", pady=8)
        self._maxdet_var = tk.IntVar(master=self, value=self.max_det)

        def _on_maxdet(*_):
            try:
                self.max_det = max(1, int(self._maxdet_var.get()))
            except Exception:
                pass
        self._maxdet_var.trace_add("write", _on_maxdet)
        tk.Spinbox(ctrl2, from_=1, to=50, width=4,
                   font=("Consolas", 15, "bold"),
                   textvariable=self._maxdet_var).pack(side="left", padx=(6, 0),
                                                       ipady=4)

        # 설정 저장 버튼 (시인성 강조)
        tk.Button(ctrl2, text="💾 설정 저장", bg="#1565c0", fg="white",
                  activebackground="#0d47a1", activeforeground="white",
                  relief="flat", cursor="hand2",
                  font=("Malgun Gothic", 12, "bold"),
                  command=self._save_settings).pack(side="left", padx=(16, 0),
                                                    ipadx=10, ipady=4)

        # 모델 표시 (최대 개수 옆에 크게)
        tk.Label(ctrl2, text="모델:", font=("Malgun Gothic", 12, "bold")).pack(
            side="left", padx=(20, 4))
        self.lbl_model = tk.Label(ctrl2, text="-", anchor="w", justify="left",
                                  font=("Malgun Gothic", 13, "bold"),
                                  fg="#2e7d32")
        self.lbl_model.pack(side="left")

        # --- 본문: 조이스틱 | 디스플레이 | 그리드 ---
        body = tk.Frame(panel); body.pack(fill="x", padx=8, pady=(0, 8))

        from joystick import Joystick           # 지연 import (순환 방지)
        from motion_grid import MotionGrid
        self._MotionGrid = MotionGrid

        jwrap = tk.Frame(body); jwrap.pack(side="left", padx=(0, 10))
        tk.Label(jwrap, text="조이스틱 (8방향)",
                 font=("Malgun Gothic", 9, "bold")).pack()
        self.joy = Joystick(jwrap, size=180, on_change=self._on_joystick)
        self.joy.pack()
        self.manual_hint = tk.Label(jwrap, text="", font=("Malgun Gothic", 8),
                                    fg="#c62828")
        self.manual_hint.pack()

        disp = tk.Frame(body); disp.pack(side="left", fill="both", expand=True)
        self.lbl_conn = tk.Label(disp, text="연결: -", anchor="w",
                                 justify="left", font=("Malgun Gothic", 10))
        self.lbl_obj = tk.Label(disp, text="인식: -", anchor="w",
                                justify="left",
                                font=("Malgun Gothic", 11, "bold"), fg="#1565c0")
        self.lbl_motion = tk.Label(disp, text="직전 인식: -", anchor="w",
                                   justify="left", font=("Malgun Gothic", 10))
        for w in (self.lbl_conn, self.lbl_obj, self.lbl_motion):
            w.pack(fill="x", pady=1)

        gwrap = tk.Frame(body); gwrap.pack(side="left", padx=(10, 0))
        tk.Label(gwrap, text="동작 버튼 (4×4)",
                 font=("Malgun Gothic", 9, "bold")).pack()
        self.grid = MotionGrid(gwrap, on_action=self._on_grid)
        self.grid.pack()

        self._set_manual_enabled(not self.yolo_on)   # YOLO ON이면 수동 비활성

    # ============================================================
    # 시작 / 정지
    # ============================================================
    def toggle_start(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.running:                 # 재진입 방지(딜레이/워커 중복 누적 차단)
            return
        port, cam = _read_config()
        if not port:
            messagebox.showwarning(
                "알림", "포트가 설정되지 않았습니다.\n'포트/장치 설정' 탭에서 먼저 선택하세요.")
            return
        # 직전 워커/렌더 루프가 남아있으면 확실히 정리
        self.stop()
        self._cleanup()
        # 포트가 직전에 닫혀 OS가 늦게 풀어줄 수 있어 몇 번 재시도(close→open)
        self.robot = None
        for attempt in range(4):
            try:
                r = HumanoidRobot(port, 115200)
                r.connect()
                self.robot = r
                break
            except Exception as e:
                last_err = e
                try:
                    r.close()
                except Exception:
                    pass
                time.sleep(0.4)
        if self.robot is None:
            messagebox.showerror("연결 실패",
                                 f"{port} 연결 실패:\n{last_err}")
            return
        if self._pre_model is not None:
            self.model = self._pre_model              # 앱에서 미리 로드한 모델 재사용
            self.model_label = self._pre_label or "-"
        else:
            try:
                self.model, self.model_label = yolo_mod.load_model()
                self.model.eval()
                yolo_mod.warmup(self.model, INFER_SIZE)
            except Exception as e:
                messagebox.showerror("모델 로드 실패", str(e))
                self._cleanup()
                return
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else 0
        self.cap = None
        for _ in range(5):
            self.cap = cv2.VideoCapture(cam, backend)
            if self.cap.isOpened():
                break
            self.cap.release(); time.sleep(0.3)
        if self.cap is None or not self.cap.isOpened():
            messagebox.showerror("카메라 실패", f"카메라({cam})를 열 수 없습니다.")
            self._cleanup()
            return
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.mapping = object_actions.load_actions()
        self.runner = MotionRunner(self.robot, on_disconnect=self._on_disc)
        self.runner.effects_on = self.sound_on
        self._disconnected = False
        self._disc_shown = False
        self._last_acted = ""
        self._fcount = 0
        self.running = True
        self.start_btn.config(text="■ 정지", bg="#c62828")
        self.canvas.delete("hint")
        self._set_manual_enabled(not self.yolo_on)

        self._stop_flag = threading.Event()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()
        self._schedule_render()

    def stop(self):
        self.running = False
        if hasattr(self, "_stop_flag"):
            self._stop_flag.set()
        if self._worker is not None:
            self._worker.join(timeout=1.0)
            self._worker = None
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._cleanup()
        self.start_btn.config(text="▶ 연결 & 시작", bg="#28a745")
        self.lbl_conn.config(text="연결: 정지됨")

    def _cleanup(self):
        if self.runner is not None:
            self.runner.close(); self.runner = None
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        if self.robot is not None:
            try:
                self.robot.close()
            except Exception:
                pass
            self.robot = None

    def _on_disc(self):
        self._disconnected = True

    # ============================================================
    # 워커 (카메라 + 추론 + 트리거)
    # ============================================================
    def _loop(self):
        stop = self._stop_flag          # 이 워커 전용 핸들(재시작 시 재할당돼도 안전)
        cap = self.cap
        while not stop.is_set():
            try:
                ok, frame = cap.read()
            except Exception:
                break
            if not ok or frame is None:
                if stop.wait(0.03):
                    break
                continue
            self._fcount += 1

            if self._fcount % PING_EVERY == 0 and self.robot \
                    and not self.robot.ping():
                self._disconnected = True
                break

            if self.yolo_on and self._fcount % INFER_EVERY == 0:
                dets = yolo_mod.infer(self.model, frame, INFER_SIZE,
                                      conf=self.conf_threshold,
                                      max_det=self.max_det)
                with self._lock:
                    self._dets = dets
                self._handle_triggers(dets)
            elif not self.yolo_on:
                with self._lock:
                    self._dets = np.empty((0, 6))

            with self._lock:
                self._frame = frame

    def _resolve_hold(self, st):
        """스텝 지속시간: 지정값(초) > mp3 길이 > 기본(None=러너 기본)."""
        d = st.get("duration")
        if d:
            try:
                return float(d)
            except Exception:
                pass
        if st.get("sound_kind") == snd.MP3 and st.get("sound_value"):
            try:
                import mp3_library
                dd = mp3_library.read_meta(st["sound_value"]).get("duration", 0)
                if dd and dd > 0:
                    return float(dd)
            except Exception:
                pass
        return None

    def _handle_triggers(self, dets):
        top_label, top_conf = "", 0.0
        for det in dets:
            conf = float(det[4]); cid = int(det[5])
            if conf > top_conf:
                top_conf = conf; top_label = self.model.names[cid]

        now = time.time()
        busy = bool(self.runner and self.runner.busy)
        if (top_label and top_conf >= self.conf_threshold
                and top_label != self._last_acted
                and not busy                       # 반응 진행 중이면 새 트리거 차단
                and now - self._last_trigger > TRIGGER_COOLDOWN):
            act = self.mapping.get(top_label)
            if act:
                steps = object_actions.steps_of(act)
                seq = []
                for st in steps:
                    seq.append({
                        "motion": st.get("motion"),
                        "hold": self._resolve_hold(st),
                        "sound_kind": st.get("sound_kind", snd.NONE),
                        "sound_value": st.get("sound_value", ""),
                    })
                # 서브 동작 시퀀스 실행(LED+모션+사운드, 동작중지로 취소 가능)
                if seq and self.runner:
                    self.runner.action_sequence(seq, sound_on=self.sound_on)
                self._last_acted = top_label
                self._last_trigger = now

        if top_label == "" or top_conf < self.conf_threshold:
            self._empty += 1
            if self._empty > 20:
                self._last_acted = ""
        else:
            self._empty = 0

    # ============================================================
    # 렌더 루프 (메인 스레드)
    # ============================================================
    def _schedule_render(self):
        self._render()
        if self.running:          # 정지(끊김 포함)되면 더 이상 예약하지 않음
            self._after_id = self.after(33, self._schedule_render)

    def _render(self):
        if self._disconnected:
            if self._disc_shown:          # 이미 한 번 알렸으면 무시
                return
            self._disc_shown = True
            self.stop()
            messagebox.showwarning(
                "로봇 연결 끊김",
                "로봇 연결이 끊어졌습니다.\n'포트/장치 설정'에서 다시 선택 후 시작하세요.")
            return
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
            dets = self._dets
        if frame is not None:
            top_label, top_conf, top_id = "", 0.0, -1
            hud = []
            for det in dets:
                x1, y1, x2, y2 = (int(det[0]), int(det[1]),
                                  int(det[2]), int(det[3]))
                conf = float(det[4]); cid = int(det[5])
                name = self.model.names[cid]
                kr = coco_kr(name)
                tag = f"{cid + 1}. {name}" + (f"({kr})" if kr else "")
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
                hud.append(hangul.outlined(f"{tag} {conf*100:.0f}%",
                                           (x1 + 2, max(0, y1 - 22)), 16,
                                           color=(0, 0, 0),
                                           outline=(255, 255, 255)))
                if conf > top_conf:
                    top_conf = conf; top_label = name; top_id = cid
            frame = hangul.draw_texts(frame, hud)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            cw = max(self.canvas.winfo_width(), 320)
            ch = max(self.canvas.winfo_height(), 240)
            h, w = rgb.shape[:2]
            scale = min(cw / w, ch / h)
            rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))
            self._imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.canvas.itemconfig(self.img_id, image=self._imgtk)
            self.canvas.coords(self.img_id, cw // 2, ch // 2)

            # 인식 지속시간 추적 (현재 객체가 바뀌면 직전으로 넘김)
            now = time.time()
            cur = top_label or ""
            if cur != self._cur_obj:
                if self._cur_obj:
                    self._prev_obj = self._cur_obj
                    self._prev_start = self._cur_start
                    self._prev_dur = now - self._cur_start
                self._cur_obj = cur
                self._cur_start = now if cur else 0.0

            if top_label:
                kr = coco_kr(top_label)
                name_disp = f"{top_id + 1}. {top_label}" + (
                    f" ({kr})" if kr else "")
                self.lbl_obj.config(
                    text=f"인식: {name_disp}  {top_conf*100:.0f}%\n"
                         f"최초 {_clock(self._cur_start)} · "
                         f"지속 {_dur(now - self._cur_start)}")
            else:
                self.lbl_obj.config(text="인식: -")

        self.lbl_conn.config(
            text=f"연결: {'정상' if self.robot and self.robot.is_connected else '-'}")
        if self._prev_obj:
            self.lbl_motion.config(
                text=f"직전 인식: {self._prev_obj}\n"
                     f"최초 {_clock(self._prev_start)} · "
                     f"지속 {_dur(self._prev_dur)}")
        else:
            self.lbl_motion.config(text="직전 인식: -")
        self.lbl_model.config(text=f"모델: {self.model_label}")

    # ============================================================
    # 컨트롤 콜백
    # ============================================================
    def _toggle_yolo(self):
        self.yolo_on = not self.yolo_on
        self.yolo_btn.config(text=f"YOLO: {'ON' if self.yolo_on else 'OFF'}")
        # YOLO 동작 중에는 수동 조작(조이스틱/그리드) 비활성
        self._set_manual_enabled(not self.yolo_on)

    def _set_manual_enabled(self, enabled):
        try:
            self.grid.set_enabled(enabled)
            self.joy.set_enabled(enabled)
        except Exception:
            pass
        if self.manual_hint is not None:
            self.manual_hint.config(
                text="" if enabled else "YOLO ON 중 — 수동 조작 잠금")

    def _stop_motion(self):
        if self.runner:
            self.runner.stop_all()
        try:
            self.player.stop()       # 재생 중인 mp3도 함께 중지
        except Exception:
            pass
        try:
            if self.sound_on:        # 순종하듯 "딱!" 멈추는 효과음
                self.player.play_effect(snd.FX_STOP)
        except Exception:
            pass

    def _yolo_off(self):
        """YOLO 인식을 끄고 수동 조작을 활성화(이미 꺼져 있으면 그대로)."""
        if self.yolo_on:
            self.yolo_on = False
            self.yolo_btn.config(text="YOLO: OFF")
            self._set_manual_enabled(True)

    def _open_control_panel(self):
        if not self.runner:
            messagebox.showinfo("알림", "먼저 '연결 & 시작'을 누르세요.")
            return
        # 수동 제어로 넘어가기 전: 진행 중인 동작 정지 + YOLO OFF(자동 반응 차단)
        try:
            self.runner.stop_all()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        self._yolo_off()
        from robot_control_panel import ControlPanel
        # 모달: 최상위 + 포커스 + 메인 윈도 잠금(제어판 __init__에서 처리)
        ControlPanel(self.winfo_toplevel(), self.runner)

    def _toggle_sound(self):
        self.sound_on = not self.sound_on
        self.sound_btn.config(
            text=f"사운드: {'ON' if self.sound_on else 'OFF'}")
        if self.runner:
            self.runner.effects_on = self.sound_on

    def _save_settings(self):
        """인식 창의 설정(신뢰도/최대 개수)을 저장한다."""
        try:
            self.max_det = max(1, int(self._maxdet_var.get()))
        except Exception:
            pass
        self.conf_threshold = float(self._conf_var.get())
        _save_rec_settings(self.conf_threshold, self.max_det)
        messagebox.showinfo(
            "설정 저장",
            f"신뢰도 ≥ {self.conf_threshold:.2f}\n"
            f"최대 개수 = {self.max_det}\n저장되었습니다.")

    def reload_mapping(self):
        """객체 반응 매핑을 조용히 다시 불러온다(자동 호출용)."""
        self.mapping = object_actions.load_actions()

    def _reset_recognition_state(self):
        """인식/직전 인식/지속시간 등 추적 상태 초기화."""
        self._cur_obj = ""
        self._cur_start = 0.0
        self._prev_obj = ""
        self._prev_start = 0.0
        self._prev_dur = 0.0
        self._last_acted = ""
        self._empty = 0
        with self._lock:
            self._dets = np.empty((0, 6))

    def _reload_mapping(self):
        self.reload_mapping()
        self._reset_recognition_state()       # 인식 결과/직전 인식 초기화
        messagebox.showinfo("새로고침",
                            "매핑을 다시 불러오고 인식 상태를 초기화했습니다.")

    def _on_joystick(self, direction):
        if not self.runner:
            return
        if direction is None:
            self.runner.stop_sequence(return_ready=True)
        elif direction in DIR_SEQ:
            self.runner.start_sequence(DIR_SEQ[direction])

    def set_preloaded(self, model, label):
        """app에서 (재)로드한 모델을 받음. 실행 중이면 즉시 교체(다음 추론부터 적용)."""
        self._pre_model = model
        self._pre_label = label
        if self.running and model is not None:
            self.model = model
            self.model_label = label

    def _on_grid(self, entry):
        """그리드 버튼: 모션 전송 + (지정 시) 사운드 재생."""
        if not self.runner:
            messagebox.showinfo("알림", "먼저 '연결 & 시작'을 누르세요.")
            return
        self.runner.send_once(entry.get("motion", 1))
        kind = entry.get("sound_kind", snd.NONE)
        if self.sound_on and kind and kind != snd.NONE:
            self.player.play(kind, entry.get("sound_value", ""))

    def on_close(self):
        if self.running:
            self.stop()


if __name__ == "__main__":
    root = tk.Tk()
    root.title("인식 (단독 실행)")
    root.geometry("760x720")
    view = RecognitionView(root)
    view.pack(fill="both", expand=True)
    root.protocol("WM_DELETE_WINDOW",
                  lambda: (view.on_close(), root.destroy()))
    root.mainloop()
