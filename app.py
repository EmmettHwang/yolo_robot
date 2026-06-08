# coding: utf-8
"""
app.py
======
YOLOv5 휴머노이드 로봇 — 탭 메인 윈도우 (진입점).

탭:
  ⚙ 포트/장치 설정 : port_selector.py 를 별도 창으로 실행 (각자 Tk 루트라 분리)
  🧠 로봇 학습     : trainer.py 를 별도 창으로 실행
  🎯 객체 반응     : object_actions.ActionEditor (임베드)
  ▶ 인식 시작      : recognition_view.RecognitionView (임베드)

포트/학습은 자체 Tk 루트를 가진 독립 앱이므로 서브프로세스로 띄운다.
객체반응/인식 뷰는 ttk.Frame 으로 설계되어 이 창에 바로 임베드된다.
"""

import os
import sys
import configparser
import subprocess

import tkinter as tk
from tkinter import ttk

from paths import BASE, CONFIG_INI, ensure_dirs
import trainer
from object_actions import ActionEditor
from recognition_view import RecognitionView

PY = sys.executable
FONT = ("Malgun Gothic", 10)


def _launch(script: str) -> None:
    """프로젝트 스크립트를 별도 프로세스로 실행."""
    subprocess.Popen([PY, os.path.join(BASE, script)], cwd=BASE)


def _current_config() -> str:
    cfg = configparser.ConfigParser()
    try:
        cfg.read(CONFIG_INI, encoding="utf-8")
        s = cfg["SETTINGS"]
        return (f"포트: {s.get('last_port') or '-'}    "
                f"카메라: {s.get('last_camera_index') or '-'}    "
                f"마이크: {s.get('last_audio_in_index') or '-'}")
    except Exception:
        return "저장된 설정이 없습니다. '장치 설정 열기'에서 선택하세요."


class App:
    def __init__(self):
        ensure_dirs()
        self.root = tk.Tk()
        self.root.title("YOLOv5 휴머노이드 로봇")
        self.root.geometry("820x780")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        nb.add(self._tab_devices(nb), text="  ⚙ 포트/장치 설정  ")
        nb.add(self._tab_training(nb), text="  🧠 로봇 학습  ")
        nb.add(self._tab_actions(nb), text="  🎯 객체 반응  ")

        self.rec_view = RecognitionView(nb)
        nb.add(self.rec_view, text="  ▶ 인식 시작  ")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 탭: 포트/장치 ----------
    def _tab_devices(self, nb):
        f = ttk.Frame(nb)
        tk.Label(f, text="포트 / 장치 설정", font=("Malgun Gothic", 15, "bold"),
                 pady=16).pack()
        tk.Label(f, text="시리얼(로봇)·카메라·마이크·스피커를 선택하고 테스트합니다.\n"
                 "(선택 결과는 자동 저장되어 인식/학습에서 사용됩니다.)",
                 font=("Malgun Gothic", 9), fg="#555", justify="center").pack()

        self.cfg_label = tk.Label(f, text=_current_config(), font=FONT,
                                  fg="#1565c0", pady=10)
        self.cfg_label.pack()

        tk.Button(f, text="🔧  장치 설정 열기", font=("Malgun Gothic", 12, "bold"),
                  bg="#1565c0", fg="white", relief="flat", cursor="hand2",
                  height=2, width=22,
                  command=lambda: _launch("port_selector.py")).pack(pady=8)
        ttk.Button(f, text="↻ 현재 설정 새로고침", cursor="hand2",
                   command=lambda: self.cfg_label.config(
                       text=_current_config())).pack()
        return f

    # ---------- 탭: 로봇 학습 ----------
    def _tab_training(self, nb):
        f = ttk.Frame(nb)
        tk.Label(f, text="로봇 학습", font=("Malgun Gothic", 15, "bold"),
                 pady=16).pack()
        tk.Label(f, text="카메라로 데이터를 수집하고(1이미지=1객체) 학습한 뒤 모델을 교체합니다.",
                 font=("Malgun Gothic", 9), fg="#555").pack(pady=(0, 10))

        def big(text, cmd, color):
            tk.Button(f, text=text, font=("Malgun Gothic", 12, "bold"),
                      bg=color, fg="white", relief="flat", cursor="hand2",
                      height=2, width=24, command=cmd).pack(pady=6)

        big("📷  데이터 수집 / 학습 / 교체 열기",
            lambda: _launch("trainer.py"), "#6a1b9a")
        tk.Label(f, text="※ 학습은 CPU라 느립니다. 클래스당 20~50장, 에폭 10~30 권장.",
                 font=("Malgun Gothic", 9), fg="#999").pack(pady=(8, 0))
        return f

    # ---------- 탭: 객체 반응 ----------
    def _tab_actions(self, nb):
        f = ttk.Frame(nb)
        classes = trainer.load_classes() or [
            "person", "bottle", "cell phone", "cup", "chair", "book"]
        editor = ActionEditor(f, class_names=classes)
        editor.pack(fill="both", expand=True)
        return f

    def _on_close(self):
        try:
            self.rec_view.on_close()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
