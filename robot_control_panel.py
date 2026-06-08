# coding: utf-8
"""
robot_control_panel.py
======================
로봇 직접 제어 패널 (LED / 포지션 / 전원). 인식 뷰의 살아있는 MotionRunner를
받아 그 백그라운드 스레드로 전송을 직렬화한다(모션과 충돌 방지).
"""

import tkinter as tk
from tkinter import ttk

import motor_map


class ControlPanel(tk.Toplevel):
    def __init__(self, parent, runner):
        super().__init__(parent)
        self.runner = runner
        self.title("로봇 제어 — LED / 포지션 / 전원")
        self.resizable(False, False)
        self._build()

    def _build(self):
        # 전원
        pw = ttk.LabelFrame(self, text="  전원(토크)  ")
        pw.pack(fill="x", padx=10, pady=(10, 6))
        tk.Button(pw, text="전원 ON", bg="#28a745", fg="white", relief="flat",
                  width=12, cursor="hand2",
                  command=lambda: self.runner.power(True)).pack(
            side="left", padx=8, pady=8)
        tk.Button(pw, text="전원 OFF", bg="#c62828", fg="white", relief="flat",
                  width=12, cursor="hand2",
                  command=lambda: self.runner.power(False)).pack(
            side="left", padx=8)

        # LED
        led = ttk.LabelFrame(self, text="  LED 제어  ")
        led.pack(fill="x", padx=10, pady=6)
        row = tk.Frame(led); row.pack(fill="x", padx=8, pady=6)
        tk.Label(row, text="대상", font=("Malgun Gothic", 9)).pack(side="left")
        self.led_target = tk.StringVar(value="전체")
        ttk.Combobox(row, textvariable=self.led_target, state="readonly",
                     width=22,
                     values=["전체"] + [motor_map.joint_label(i)
                                       for i in motor_map.ALL_IDS]).pack(
            side="left", padx=6)
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
                     command=lambda e: self._upd_swatch()).pack(
                side="left", fill="x", expand=True)
        brow = tk.Frame(led); brow.pack(fill="x", padx=8, pady=6)
        tk.Button(brow, text="LED 전송", bg="#1565c0", fg="white",
                  relief="flat", cursor="hand2",
                  command=self._send_led).pack(side="left")
        tk.Button(brow, text="LED 끄기", cursor="hand2",
                  command=self._led_off).pack(side="left", padx=6)

        # 포지션
        pos = ttk.LabelFrame(self, text="  포지션 제어  ")
        pos.pack(fill="x", padx=10, pady=6)
        prow = tk.Frame(pos); prow.pack(fill="x", padx=8, pady=6)
        tk.Label(prow, text="관절", font=("Malgun Gothic", 9)).pack(side="left")
        self.pos_target = tk.StringVar(value=motor_map.joint_label(18))
        ttk.Combobox(prow, textvariable=self.pos_target, state="readonly",
                     width=22, values=[motor_map.joint_label(i)
                                       for i in motor_map.ALL_IDS]).pack(
            side="left", padx=6)
        self.pos_val = tk.IntVar(value=0)
        fr = tk.Frame(pos); fr.pack(fill="x", padx=8)
        tk.Label(fr, text="위치", width=4).pack(side="left")
        tk.Scale(fr, from_=-1000, to=1000, orient="horizontal",
                 variable=self.pos_val).pack(side="left", fill="x", expand=True)
        self.torq = tk.IntVar(value=60)
        fr2 = tk.Frame(pos); fr2.pack(fill="x", padx=8)
        tk.Label(fr2, text="토크%", width=4).pack(side="left")
        tk.Scale(fr2, from_=0, to=100, orient="horizontal",
                 variable=self.torq).pack(side="left", fill="x", expand=True)
        tk.Button(pos, text="포지션 전송", bg="#6a1b9a", fg="white",
                  relief="flat", cursor="hand2",
                  command=self._send_pos).pack(pady=6)

        tk.Label(self, text="※ 포지션 값/범위는 모델마다 다를 수 있어요. "
                 "작은 값부터 시험하세요.", font=("Malgun Gothic", 8),
                 fg="#999").pack(pady=(0, 10))
        self._upd_swatch()

    def _ids_for_target(self):
        t = self.led_target.get()
        if t == "전체":
            return motor_map.ALL_IDS
        try:
            return [int(t.split(" - ")[0])]
        except Exception:
            return []

    def _upd_swatch(self):
        self.swatch.config(
            bg=f"#{self.r.get():02x}{self.g.get():02x}{self.b.get():02x}")

    def _send_led(self):
        if not self.runner:
            return
        r, g, b = self.r.get(), self.g.get(), self.b.get()
        self.runner.led([(i, r, g, b) for i in self._ids_for_target()])

    def _led_off(self):
        if not self.runner:
            return
        self.runner.led([(i, 0, 0, 0) for i in motor_map.ALL_IDS])

    def _send_pos(self):
        if not self.runner:
            return
        try:
            jid = int(self.pos_target.get().split(" - ")[0])
        except Exception:
            return
        self.runner.position([(jid, self.pos_val.get(), self.torq.get())])
