# coding: utf-8
"""
robot_control_panel.py
======================
로봇 직접 제어 패널 (LED / 포지션 / 전원). 인식 뷰의 살아있는 MotionRunner를
받아 그 백그라운드 스레드로 전송을 직렬화한다(모션과 충돌 방지).

- LED / 포지션: 슬라이더를 움직이면 실시간 전송(약 11Hz로 throttle).
- 포지션 안전 범위: 매뉴얼에 동작 위치 범위 명시가 없어, 프로토콜 예제값(±100)을
  기준으로 -100~100 로 제한. (참고: 영점 조정 범위 -12~12, 토크 5.3kgf@5V)
"""

import tkinter as tk
from tkinter import ttk

import motor_map

POS_MIN, POS_MAX = -100, 100        # 안전 위치 범위(보수적)
FLUSH_MS = 90                       # 실시간 전송 주기


class ControlPanel(tk.Toplevel):
    def __init__(self, parent, runner):
        super().__init__(parent)
        self.runner = runner
        self.title("로봇 제어 — LED / 포지션 / 전원")
        self.resizable(False, False)
        self._led_dirty = False
        self._pos_dirty = False
        self._manual = False
        self._manual_after = None
        self._alive = True
        self._build()
        self._flush()                # 실시간 전송 루프 시작

    def _build(self):
        # 전원
        pw = ttk.LabelFrame(self, text="  전원(토크)  ")
        pw.pack(fill="x", padx=10, pady=(10, 6))
        tk.Button(pw, text="전원 ON", bg="#28a745", fg="white", relief="flat",
                  width=12, cursor="hand2",
                  command=lambda: self.runner.safe_power(True)).pack(
            side="left", padx=8, pady=8)
        tk.Button(pw, text="전원 OFF", bg="#c62828", fg="white", relief="flat",
                  width=12, cursor="hand2",
                  command=lambda: self.runner.safe_power(False)).pack(
            side="left", padx=8)
        tk.Label(pw, text="ON: 전원→일어서기 / OFF: 앉기→7초→전원끔",
                 font=("Malgun Gothic", 8), fg="#777").pack(side="left", padx=6)

        # LED (실시간)
        led = ttk.LabelFrame(self, text="  LED 제어 (실시간)  ")
        led.pack(fill="x", padx=10, pady=6)
        row = tk.Frame(led); row.pack(fill="x", padx=8, pady=6)
        tk.Label(row, text="대상", font=("Malgun Gothic", 9)).pack(side="left")
        self.led_target = tk.StringVar(value="전체")
        lc = ttk.Combobox(row, textvariable=self.led_target, state="readonly",
                          width=22,
                          values=["전체"] + [motor_map.joint_label(i)
                                            for i in motor_map.ALL_IDS])
        lc.pack(side="left", padx=6)
        lc.bind("<<ComboboxSelected>>", lambda e: self._mark_led())
        self.swatch = tk.Label(row, text="      ", bg="#ff0000",
                               relief="groove")
        self.swatch.pack(side="right")

        self.r = tk.IntVar(value=255)
        self.g = tk.IntVar(value=0)
        self.b = tk.IntVar(value=0)
        for name, var, color in (("R", self.r, "#c62828"),
                                 ("G", self.g, "#2e7d32"),
                                 ("B", self.b, "#1565c0")):
            fr = tk.Frame(led); fr.pack(fill="x", padx=8)
            tk.Label(fr, text=name, width=2, fg=color).pack(side="left")
            tk.Scale(fr, from_=0, to=255, orient="horizontal", variable=var,
                     command=lambda e: (self._upd_swatch(),
                                        self._mark_led())).pack(
                side="left", fill="x", expand=True)
        brow = tk.Frame(led); brow.pack(fill="x", padx=8, pady=6)
        tk.Button(brow, text="LED 끄기", cursor="hand2",
                  command=self._led_off).pack(side="left")

        # 포지션 (실시간)
        pos = ttk.LabelFrame(self, text="  포지션 제어 (실시간)  ")
        pos.pack(fill="x", padx=10, pady=6)
        prow = tk.Frame(pos); prow.pack(fill="x", padx=8, pady=6)
        tk.Label(prow, text="관절", font=("Malgun Gothic", 9)).pack(side="left")
        self.pos_target = tk.StringVar(value=motor_map.joint_label(18))
        pc = ttk.Combobox(prow, textvariable=self.pos_target,
                          state="readonly", width=22,
                          values=[motor_map.joint_label(i)
                                  for i in motor_map.ALL_IDS])
        pc.pack(side="left", padx=6)
        pc.bind("<<ComboboxSelected>>", lambda e: self._mark_pos())

        self.pos_val = tk.IntVar(value=0)
        fr = tk.Frame(pos); fr.pack(fill="x", padx=8)
        tk.Label(fr, text="위치", width=4).pack(side="left")
        tk.Scale(fr, from_=POS_MIN, to=POS_MAX, orient="horizontal",
                 variable=self.pos_val,
                 command=lambda e: self._mark_pos()).pack(
            side="left", fill="x", expand=True)
        self.torq = tk.IntVar(value=40)
        fr2 = tk.Frame(pos); fr2.pack(fill="x", padx=8)
        tk.Label(fr2, text="토크%", width=4).pack(side="left")
        tk.Scale(fr2, from_=0, to=100, orient="horizontal", variable=self.torq,
                 command=lambda e: self._mark_pos()).pack(
            side="left", fill="x", expand=True)
        prow2 = tk.Frame(pos); prow2.pack(pady=4)
        tk.Button(prow2, text="중립(0)으로", cursor="hand2",
                  command=self._center_pos).pack(side="left", padx=4)
        self.manual_btn = tk.Button(
            prow2, text="✋ 수동 조절", bg="#607d8b", fg="white", relief="flat",
            cursor="hand2", command=self._toggle_manual)
        self.manual_btn.pack(side="left", padx=4)
        self.read_label = tk.Label(pos, text="", font=("Consolas", 10),
                                   fg="#6a1b9a")
        self.read_label.pack(pady=(2, 4))

        tk.Label(self, text=f"※ 위치 범위 {POS_MIN}~{POS_MAX} (매뉴얼에 동작범위 "
                 "명시 없음 → 예제값 ±100 기준 보수적 제한). 작은 값부터 시험하세요.",
                 font=("Malgun Gothic", 8), fg="#999",
                 wraplength=420, justify="left").pack(pady=(0, 10), padx=10)
        self._upd_swatch()

    # ---------- 실시간 전송 ----------
    def _mark_led(self):
        self._led_dirty = True

    def _mark_pos(self):
        self._pos_dirty = True

    def _flush(self):
        if not self._alive:
            return
        if self.runner:
            if self._led_dirty:
                self._led_dirty = False
                r, g, b = self.r.get(), self.g.get(), self.b.get()
                self.runner.led([(i, r, g, b) for i in self._ids_for_target()])
            if self._pos_dirty and not self._manual:   # 수동(토크해제) 중엔 전송 안 함
                self._pos_dirty = False
                jid = self._pos_joint()
                if jid is not None:
                    self.runner.position(
                        [(jid, self.pos_val.get(), self.torq.get())])
        self.after(FLUSH_MS, self._flush)

    # ---------- helpers ----------
    def _ids_for_target(self):
        t = self.led_target.get()
        if t == "전체":
            return motor_map.ALL_IDS
        try:
            return [int(t.split(" - ")[0])]
        except Exception:
            return []

    def _pos_joint(self):
        try:
            return int(self.pos_target.get().split(" - ")[0])
        except Exception:
            return None

    def _upd_swatch(self):
        self.swatch.config(
            bg=f"#{self.r.get():02x}{self.g.get():02x}{self.b.get():02x}")

    def _led_off(self):
        if self.runner:
            self.runner.led([(i, 0, 0, 0) for i in motor_map.ALL_IDS])

    def _center_pos(self):
        self.pos_val.set(0)
        self._mark_pos()

    # ---------- 수동 조절(토크 해제 + 위치 읽기) ----------
    def _toggle_manual(self):
        self._manual = not self._manual
        if self._manual:
            self.manual_btn.config(text="■ 수동 끝", bg="#c62828")
            self.read_label.config(text="토크 해제됨 — 손으로 관절을 움직여 보세요",
                                   fg="#c62828")
            if self.runner:
                self.runner.power(False)        # 토크 off → 손으로 조작 가능
            self._poll_manual()
        else:
            self.manual_btn.config(text="✋ 수동 조절", bg="#607d8b")
            self.read_label.config(text="", fg="#6a1b9a")
            if self.runner:
                self.runner.power(True)         # 토크 on → 현재 자세 유지

    def _poll_manual(self):
        if not self._manual or not self._alive:
            return
        if self.runner:
            jid = self._pos_joint()
            if jid is not None:
                self.runner.read_positions([jid], self._on_read)
        self._manual_after = self.after(300, self._poll_manual)

    def _on_read(self, res):
        # 러너 스레드 → UI 스레드로 마샬
        try:
            self.after(0, lambda r=res: self._show_read(r))
        except Exception:
            pass

    def _show_read(self, res):
        if not res:
            self.read_label.config(text="위치 읽기 실패(응답 없음)", fg="#c62828")
            return
        txt = "  ".join(f"ID{k}={v}" for k, v in res.items())
        self.read_label.config(text=f"읽은 위치 → {txt}", fg="#2e7d32")
        jid = self._pos_joint()
        val = res.get(jid)
        if val is not None and POS_MIN <= val <= POS_MAX:
            self.pos_val.set(val)               # 슬라이더에도 반영

    def destroy(self):
        self._alive = False
        if self._manual_after is not None:
            try:
                self.after_cancel(self._manual_after)
            except Exception:
                pass
        super().destroy()
