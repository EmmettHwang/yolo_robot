# coding: utf-8
"""
app.py
======
YOLOv5 휴머노이드 로봇 — 탭 메인 윈도우 (진입점).

탭:
  ⚙ 포트/장치 설정 : port_selector.py 를 별도 창으로 실행
  🧠 로봇 학습     : trainer.py 를 별도 창으로 실행
  🎯 객체 반응     : object_actions.ActionEditor (임베드)
  ▶ 인식 시작      : recognition_view.RecognitionView (임베드)
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

BG = "#f4f6fa"
HEADER_BG = "#1e2a4a"
ACCENT = "#1565c0"


def _launch(script: str) -> None:
    subprocess.Popen([PY, os.path.join(BASE, script)], cwd=BASE)


def _current_config() -> str:
    cfg = configparser.ConfigParser()
    try:
        cfg.read(CONFIG_INI, encoding="utf-8")
        s = cfg["SETTINGS"]
        return (f"🔌 포트 {s.get('last_port') or '-'}    "
                f"📷 카메라 {s.get('last_camera_index') or '-'}    "
                f"🎤 마이크 {s.get('last_audio_in_index') or '-'}")
    except Exception:
        return "저장된 설정이 없습니다. ‘장치 설정 열기’에서 선택하세요."


def _card(parent, icon, title, desc, btn_text, cmd, color):
    c = tk.Frame(parent, bg="white", highlightbackground="#dde3ee",
                 highlightthickness=1)
    tk.Label(c, text=icon, font=("Segoe UI Emoji", 44), bg="white").pack(
        pady=(20, 4))
    tk.Label(c, text=title, font=("Malgun Gothic", 15, "bold"),
             bg="white").pack()
    tk.Label(c, text=desc, font=("Malgun Gothic", 9), fg="#667", bg="white",
             justify="center").pack(pady=(4, 12))
    tk.Button(c, text=btn_text, bg=color, fg="white", relief="flat",
              cursor="hand2", font=("Malgun Gothic", 12, "bold"), height=2,
              activebackground=color, command=cmd).pack(
        fill="x", padx=24, pady=(0, 20))
    return c


class App:
    def __init__(self):
        ensure_dirs()
        self.root = tk.Tk()
        self.root.title("YOLOv5 휴머노이드 로봇")
        self.root.geometry("860x820")
        self.root.configure(bg=BG)
        self._style()

        # 헤더 배너
        header = tk.Frame(self.root, bg=HEADER_BG, height=64)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="🤖  YOLOv5 휴머노이드 로봇 컨트롤",
                 font=("Malgun Gothic", 17, "bold"), fg="white",
                 bg=HEADER_BG).pack(side="left", padx=20)
        tk.Label(header, text="MRT 라인코어 스마트", font=("Malgun Gothic", 10),
                 fg="#9fb3d8", bg=HEADER_BG).pack(side="right", padx=20)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        nb.add(self._tab_devices(nb), text="  ⚙  포트·장치  ")
        nb.add(self._tab_training(nb), text="  🧠  로봇 학습  ")
        nb.add(self._tab_actions(nb), text="  🎯  객체 반응  ")
        self.rec_view = RecognitionView(nb)
        nb.add(self.rec_view, text="  ▶  인식 시작  ")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", font=("Malgun Gothic", 12, "bold"),
                     padding=(20, 10), background="#dfe5f0")
        st.map("TNotebook.Tab",
               background=[("selected", ACCENT)],
               foreground=[("selected", "white")])
        st.configure("TFrame", background=BG)

    # ---------- 탭: 포트/장치 ----------
    def _tab_devices(self, nb):
        f = ttk.Frame(nb)
        self.cfg_label = tk.Label(
            f, text=_current_config(), font=("Malgun Gothic", 11, "bold"),
            fg=ACCENT, bg=BG, pady=14)
        self.cfg_label.pack(pady=(18, 0))

        card = _card(
            f, "🔧", "포트 / 장치 설정",
            "시리얼(로봇)·카메라·마이크·스피커를 선택하고\n"
            "동작 테스트·녹음/재생까지 한 곳에서.",
            "장치 설정 열기", lambda: _launch("port_selector.py"), ACCENT)
        card.pack(padx=80, pady=16, fill="x")

        tk.Button(f, text="↻ 현재 설정 새로고침", cursor="hand2", bg=BG,
                  relief="flat", fg="#555",
                  command=lambda: self.cfg_label.config(
                      text=_current_config())).pack()
        return f

    # ---------- 탭: 로봇 학습 ----------
    def _tab_training(self, nb):
        f = ttk.Frame(nb)
        card = _card(
            f, "🧠", "로봇 학습",
            "카메라로 데이터를 수집하고(1이미지=1객체)\n학습한 뒤 모델을 교체합니다.",
            "데이터 수집 / 학습 / 교체 열기",
            lambda: _launch("trainer.py"), "#6a1b9a")
        card.pack(padx=80, pady=(30, 16), fill="x")
        tk.Label(f, text="※ 학습은 CPU라 느립니다. 클래스당 20~50장, 에폭 10~30 권장.",
                 font=("Malgun Gothic", 9), fg="#999", bg=BG).pack()
        return f

    # ---------- 탭: 객체 반응 ----------
    def _tab_actions(self, nb):
        f = ttk.Frame(nb)
        classes = trainer.load_classes()
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
