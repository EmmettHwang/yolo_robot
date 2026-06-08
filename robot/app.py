# coding: utf-8
"""
app.py
======
YOLOv5 휴머노이드 로봇 — 탭 메인 윈도우 (진입점).

시퀀스 흐름(쭈욱 진행되는 느낌):
  ① 포트·장치 : 저장된 설정을 자동 검증/표시. 정상이면 잠시 후 자동으로 다음 탭.
                문제 있을 때만 '장치 설정 열기'.
  ② 로봇 학습 : 진입 시 YOLOv5 모델을 백그라운드 로딩(애니메이션). 완료되면
                '학습하기' / '다음 → 인식 시작' 활성화. (로드한 모델은 인식에서 재사용)
  ③ 객체 반응 : object_actions.ActionEditor
  ④ 인식 시작 : recognition_view.RecognitionView
"""

import os
import sys
import threading
import configparser
import subprocess

import tkinter as tk
from tkinter import ttk

import serial.tools.list_ports as list_ports
from PIL import Image, ImageTk

from paths import (BASE, ROBOT_DIR, CONFIG_INI, LOGO_PATH, ACTIVE_MODEL,
                   ensure_dirs)
from version import __version__
from motion_table import COCO_CLASSES, coco_kr
import trainer
import yolo as yolo_mod
from object_actions import ActionEditor
from recognition_view import RecognitionView

PY = sys.executable
BG = "#f4f6fa"
HEADER_BG = "#1e2a4a"
ACCENT = "#1565c0"


def _launch(script):
    # 모듈은 robot/ 안에 있으므로 그 경로의 스크립트를 실행
    subprocess.Popen([PY, os.path.join(ROBOT_DIR, script)], cwd=BASE)


def _read_cfg():
    cfg = configparser.ConfigParser()
    try:
        cfg.read(CONFIG_INI, encoding="utf-8")
        s = cfg["SETTINGS"]
        port = s.get("last_port") or None
        cam = s.get("last_camera_index")
        return port, (cam if cam not in (None, "") else "0")
    except Exception:
        return None, "0"


def _validate_devices():
    """(ok, message). 저장된 포트가 실제 연결 목록에 있는지 확인."""
    port, cam = _read_cfg()
    if not port:
        return False, "포트가 설정되지 않았습니다. ‘장치 설정 열기’에서 선택하세요."
    avail = [p.device for p in list_ports.comports()]
    if port not in avail:
        return False, f"{port} 가 연결 목록에 없습니다. 로봇 전원/페어링 확인 후 다시 설정."
    return True, f"✓ 포트 {port} · 카메라 {cam} 확인됨"


class App:
    def __init__(self):
        ensure_dirs()
        self.root = tk.Tk()
        self.root.title(f"YOLOv5 휴머노이드 로봇  v{__version__}")
        self.root.geometry("880x840")
        self.root.configure(bg=BG)
        self._style()

        self.model = None
        self.model_label = None
        self._model_loading = False
        self._model_loaded = False
        self._model_failed = False
        self._coco_idx = 0
        self._showcase_count = 0
        self._dev_proc = None
        self._prev_tab = None
        self._wait_dlg = None
        self._train_proc = None
        self._train_before_mtime = 0
        # 자동 진행 옵션 (체크박스)
        self.auto_dev = tk.BooleanVar(value=True)    # 설정 후 자동 이동
        self.auto_yolo = tk.BooleanVar(value=False)  # 모델 준비 후 자동 이동

        self._header()

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_dev = self._tab_devices(self.nb)
        self.tab_train = self._tab_training(self.nb)
        self.tab_act = self._tab_actions(self.nb)
        self.rec_view = RecognitionView(self.nb)
        self.nb.add(self.tab_dev, text="  ①  ⚙ 포트·장치  ")
        self.nb.add(self.tab_train, text="  ②  🧠 로봇 학습  ")
        self.nb.add(self.tab_act, text="  🎯 객체 반응  ")
        self.nb.add(self.rec_view, text="  ④  ▶ 인식 시작  ")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(400, self._start_flow)        # 시퀀스 시작

    def _get_active_mtime(self):
        try:
            return os.path.getmtime(ACTIVE_MODEL) \
                if os.path.exists(ACTIVE_MODEL) else 0
        except Exception:
            return 0

    def _open_training(self):
        """로봇 학습 창(트레이너)을 별도 프로세스로 열고, 닫히면(뒤로) 모델 변경 시 재로드."""
        if self._train_proc is not None and self._train_proc.poll() is None:
            return
        self._train_before_mtime = self._get_active_mtime()
        self._train_proc = subprocess.Popen(
            [PY, os.path.join(ROBOT_DIR, "trainer.py")], cwd=BASE)
        self._watch_train_proc()

    def _watch_train_proc(self):
        if self._train_proc is not None and self._train_proc.poll() is None:
            self.root.after(700, self._watch_train_proc)
            return
        # 트레이너가 닫힘(뒤로) → active 모델이 바뀌었으면 다시 로드
        if self._get_active_mtime() != self._train_before_mtime:
            self.model_status.config(text="🔄 모델 변경 감지 — 다시 로드합니다...",
                                     fg="#ef6c00")
            self._reload_model()

    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", font=("Malgun Gothic", 12, "bold"),
                     padding=(18, 10), background="#dfe5f0")
        st.map("TNotebook.Tab", background=[("selected", ACCENT)],
               foreground=[("selected", "white")])
        st.configure("TFrame", background=BG)

    def _header(self):
        header = tk.Frame(self.root, bg=HEADER_BG, height=66)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="🤖  YOLOv5 휴머노이드 로봇 컨트롤",
                 font=("Malgun Gothic", 17, "bold"), fg="white",
                 bg=HEADER_BG).pack(side="left", padx=20)
        try:
            img = Image.open(LOGO_PATH)
            h = 46
            w = max(1, int(img.width * h / img.height))
            self._logo = ImageTk.PhotoImage(img.resize((w, h)))
            tk.Label(header, image=self._logo, bg=HEADER_BG).pack(
                side="right", padx=20)
        except Exception:
            tk.Label(header, text="MRT 라인코어 스마트",
                     font=("Malgun Gothic", 10), fg="#9fb3d8",
                     bg=HEADER_BG).pack(side="right", padx=20)
        ver = tk.Label(header, text=f"v{__version__}  (설명서)",
                       font=("Consolas", 9), fg="#9fb3d8", bg=HEADER_BG,
                       cursor="hand2")
        ver.pack(side="right", padx=4)
        ver.bind("<Button-1>", lambda e: self._show_manual())

        man = tk.Label(header, text="📖 매뉴얼", font=("Malgun Gothic", 10, "bold"),
                       fg="#ffd54f", bg=HEADER_BG, cursor="hand2")
        man.pack(side="right", padx=10)
        man.bind("<Button-1>", lambda e: self._show_pdf_manual())

    # ---------- 탭: 포트/장치 ----------
    def _tab_devices(self, nb):
        f = ttk.Frame(nb)
        tk.Label(f, text="① 포트 / 장치 확인", font=("Malgun Gothic", 16, "bold"),
                 bg=BG).pack(pady=(26, 6))
        self.dev_status = tk.Label(f, text="확인 중...",
                                   font=("Malgun Gothic", 12, "bold"),
                                   fg=ACCENT, bg=BG)
        self.dev_status.pack(pady=4)

        btns = tk.Frame(f, bg=BG); btns.pack(pady=16)
        tk.Button(btns, text="🔧 장치 설정 열기", font=("Malgun Gothic", 11, "bold"),
                  bg="#607d8b", fg="white", relief="flat", cursor="hand2",
                  height=2, width=18,
                  command=self._open_device_settings).pack(side="left", padx=6)
        tk.Button(btns, text="↻ 다시 확인", font=("Malgun Gothic", 11),
                  cursor="hand2", height=2, width=12,
                  command=self._check_devices).pack(side="left", padx=6)
        self.dev_next = tk.Button(
            btns, text="다음 → 로봇 학습 ▶", font=("Malgun Gothic", 11, "bold"),
            bg=ACCENT, fg="white", relief="flat", cursor="hand2", height=2,
            width=18, command=lambda: self.nb.select(self.tab_train))
        self.dev_next.pack(side="left", padx=6)
        tk.Checkbutton(f, text="설정 창 닫으면 3초 후 자동으로 다음 단계로",
                       variable=self.auto_dev, bg=BG,
                       font=("Malgun Gothic", 9)).pack(pady=(8, 0))
        return f

    # ---------- 탭: 로봇 학습 ----------
    def _tab_training(self, nb):
        f = ttk.Frame(nb)
        tk.Label(f, text="② 로봇 학습", font=("Malgun Gothic", 16, "bold"),
                 bg=BG).pack(pady=(26, 6))

        self.model_status = tk.Label(
            f, text="YOLOv5 모델 로딩 준비...", font=("Malgun Gothic", 12, "bold"),
            fg="#ef6c00", bg=BG)
        self.model_status.pack(pady=4)
        self.model_pb = ttk.Progressbar(f, mode="indeterminate", length=320)
        self.model_pb.pack(pady=6)
        # 식별 가능한 객체 — 로드된 모델의 클래스로 표시(교체/재로드 시 갱신)
        self._coco_header = tk.Label(f, text="식별 가능한 객체 (모델 클래스)",
                                     font=("Malgun Gothic", 9, "bold"),
                                     fg="#555", bg=BG)
        self._coco_header.pack()
        listwrap = tk.Frame(f, bg=BG); listwrap.pack(pady=(2, 6))
        self.coco_list = tk.Listbox(listwrap, font=("Consolas", 11), width=40,
                                    height=16, activestyle="none",
                                    highlightthickness=1, fg="#1565c0",
                                    selectbackground="#1565c0",
                                    selectforeground="white")
        csb = ttk.Scrollbar(listwrap, orient="vertical",
                            command=self.coco_list.yview)
        self.coco_list.configure(yscrollcommand=csb.set)
        csb.pack(side="right", fill="y")
        self.coco_list.pack(side="left")
        self._set_class_list(list(COCO_CLASSES))

        btns = tk.Frame(f, bg=BG); btns.pack(pady=18)
        tk.Button(btns, text="🧠 학습하기 (수집/학습/교체)",
                  font=("Malgun Gothic", 11, "bold"), bg="#6a1b9a", fg="white",
                  relief="flat", cursor="hand2", height=2, width=24,
                  command=self._open_training).pack(side="left", padx=6)
        self.train_next = tk.Button(
            btns, text="다음 → 인식 시작 ▶", font=("Malgun Gothic", 11, "bold"),
            bg="#9e9e9e", fg="white", relief="flat", height=2, width=18,
            state="disabled",
            command=lambda: self.nb.select(self.rec_view))
        self.train_next.pack(side="left", padx=6)

        tk.Checkbutton(f, text="모델 준비되면 자동으로 인식 시작 단계로 이동",
                       variable=self.auto_yolo, bg=BG,
                       font=("Malgun Gothic", 9)).pack(pady=(6, 0))
        tk.Label(f, text="※ 학습은 CPU라 느립니다. 클래스당 20~50장, 에폭 10~30 권장.",
                 font=("Malgun Gothic", 9), fg="#999", bg=BG).pack(pady=(8, 0))
        return f

    # ---------- 탭: 객체 반응 ----------
    def _tab_actions(self, nb):
        f = ttk.Frame(nb)
        editor = ActionEditor(f, class_names=trainer.load_classes())
        editor.pack(fill="both", expand=True)
        return f

    # ============================================================
    # 시퀀스 흐름
    # ============================================================
    def _start_flow(self):
        # 시작하면 설정창을 열어 기본 테스트부터 하고 가도록
        self._check_devices()
        self._open_device_settings()

    def _check_devices(self):
        ok, msg = _validate_devices()
        self.dev_status.config(text=msg, fg=("#2e7d32" if ok else "#c62828"))
        return ok

    def _open_device_settings(self):
        """장치 설정창(독립 프로세스)을 열고, 닫히면 재검증 후 진행."""
        if self._dev_proc is not None and self._dev_proc.poll() is None:
            return                                  # 이미 열려 있음
        # 인식이 포트를 잡고 있으면 먼저 반환(설정창 프로세스가 포트를 열 수 있게)
        try:
            self.rec_view.stop()
        except Exception:
            pass
        self.dev_status.config(text="🔧 장치 설정창에서 포트·카메라·마이크를 테스트하세요...",
                               fg="#ef6c00")
        self._dev_proc = subprocess.Popen(
            [PY, os.path.join(ROBOT_DIR, "port_selector.py")], cwd=BASE)
        self._show_wait_dialog()        # 메인 윈도 잠금 + 안내
        self._watch_device_proc()

    def _show_wait_dialog(self):
        if self._wait_dlg is not None:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("장치 및 로봇 설정 진행 중")
        dlg.configure(bg="white")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        tk.Label(dlg, text="🔧  장치 및 로봇 설정",
                 font=("Malgun Gothic", 14, "bold"), bg="white").pack(
            pady=(20, 6), padx=24)
        tk.Label(dlg, text="별도 설정 창에서 포트·카메라·마이크를 확인/테스트하세요.\n"
                 "설정을 마치고 그 창을 닫으면 자동으로 계속됩니다.",
                 font=("Malgun Gothic", 10), fg="#555", bg="white",
                 justify="center").pack(padx=24)
        pb = ttk.Progressbar(dlg, mode="indeterminate", length=320)
        pb.pack(pady=16); pb.start(12)
        tk.Label(dlg, text="⏳ 설정 창을 기다리는 중... (이 창은 잠금 상태)",
                 font=("Malgun Gothic", 9), fg="#ef6c00", bg="white").pack(
            pady=(0, 16))
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)   # 임의 닫기 방지
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 420) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 180) // 2
        dlg.geometry(f"420x180+{max(0, x)}+{max(0, y)}")
        dlg.lift()
        try:
            dlg.grab_set()              # 메인 윈도 조작 잠금
        except Exception:
            pass
        self._wait_dlg = dlg

    def _hide_wait_dialog(self):
        if self._wait_dlg is not None:
            try:
                self._wait_dlg.grab_release()
                self._wait_dlg.destroy()
            except Exception:
                pass
            self._wait_dlg = None

    def _watch_device_proc(self):
        if self._dev_proc is not None and self._dev_proc.poll() is None:
            self.root.after(500, self._watch_device_proc)
            return
        # 설정창이 닫힘 → 잠금 해제, 재검증
        self._hide_wait_dialog()
        if self._check_devices():
            if self.auto_dev.get():
                self.dev_status.config(
                    text=self.dev_status.cget("text") + "  ·  3초 후 자동 이동",
                    fg="#2e7d32")
                self.root.after(
                    3000, lambda: self._animate_press(
                        self.dev_next, lambda: self.nb.select(self.tab_train)))
            else:
                self.dev_status.config(
                    text=self.dev_status.cget("text")
                    + "  ·  ‘다음 → 로봇 학습’을 누르세요", fg="#2e7d32")

    def _animate_press(self, btn, then):
        """버튼이 '눌리는' 애니메이션 후 then() 실행."""
        try:
            obg = btn.cget("background")
            btn.config(relief="sunken", background="#0d47a1")
            self.root.after(110, lambda: btn.config(relief="raised"))
            self.root.after(240, lambda: (btn.config(relief="flat",
                                                     background=obg), then()))
        except Exception:
            then()

    def _on_tab_changed(self, _evt):
        try:
            current = self.nb.nametowidget(self.nb.select())
        except Exception:
            return
        # 인식은 탭을 벗어나도 백그라운드에서 계속 돈다(중지하지 않음).
        # 포트가 필요한 '장치 설정 열기' 때만 별도로 stop() 한다.
        # 객체 반응 탭을 벗어나면 인식의 매핑을 자동 새로고침
        if self._prev_tab is self.tab_act and current is not self.tab_act:
            try:
                self.rec_view.reload_mapping()
            except Exception:
                pass
        self._prev_tab = current

        if current is self.tab_train:
            self._load_model_async()
        elif current is self.rec_view:
            # 인식 탭에 오면 자동 시작 (체크박스로 on/off)
            if (not self.rec_view.running
                    and self.rec_view.auto_start.get()):
                self.root.after(250, self.rec_view.start)

    def _load_model_async(self):
        if self._model_loaded:
            # 이미 로드됨(되돌아온 경우) → 목록을 다시 보여줌
            try:
                self.coco_list.see(0)
            except Exception:
                pass
            return
        if self._model_loading:
            return
        self._model_loading = True
        self._model_failed = False
        self._coco_idx = 0
        self._showcase_count = 0
        self.model_status.config(text="⏳ YOLOv5 모델 로딩 중... 식별 가능한 객체:",
                                 fg="#ef6c00")
        self.model_pb.start(12)
        self._cycle_coco()                       # COCO 클래스 쭈루룩
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _cycle_coco(self):
        """로딩 중 리스트를 한 줄씩 하이라이트하며 자동 스크롤. (모델 준비+한 바퀴 후 종료)"""
        if self._model_failed:
            return
        n = len(COCO_CLASSES)
        try:
            idx = self._coco_idx % n
            self.coco_list.selection_clear(0, "end")
            self.coco_list.selection_set(idx)
            self.coco_list.see(idx)
        except Exception:
            return
        self._coco_idx += 1
        self._showcase_count += 1
        # 모델이 준비됐고 한 바퀴(80종) 다 보여줬으면 마무리
        if self._model_loaded and self._showcase_count >= n:
            self._finish_showcase()
            return
        self.root.after(70, self._cycle_coco)

    def _load_worker(self):
        try:
            m, lbl = yolo_mod.load_model()
            m.eval()
            yolo_mod.warmup(m)
            self.model, self.model_label = m, lbl
            self.root.after(0, self._on_model_loaded, True, lbl)
        except Exception as e:
            self.root.after(0, self._on_model_loaded, False, str(e))

    def _on_model_loaded(self, ok, info):
        self._model_loading = False
        self.model_pb.stop()
        if ok:
            self._model_loaded = True            # 쇼케이스가 한 바퀴 돌면 마무리됨
            self.rec_view.set_preloaded(self.model, self.model_label)
            self._loaded_info = info
        else:
            self._model_failed = True
            self.model_pb.pack_forget()
            self.model_status.config(text=f"✗ 모델 로드 실패: {info}", fg="#c62828")

    def _set_class_list(self, names):
        """식별 가능한 객체 리스트를 주어진 클래스명으로 채운다(번호+한글병기)."""
        self._class_names = list(names)
        try:
            self.coco_list.delete(0, "end")
            for i, name in enumerate(self._class_names):
                kr = coco_kr(name)
                self.coco_list.insert(
                    "end", f"{i + 1:2d}. {name}" + (f" ({kr})" if kr else ""))
        except Exception:
            pass

    def _model_names(self):
        try:
            n = self.model.names
            if isinstance(n, dict):
                return [n[k] for k in sorted(n)]
            return list(n)
        except Exception:
            return list(COCO_CLASSES)

    def _reload_model(self):
        """모델 교체 후 active 모델을 다시 불러오고 클래스 목록 갱신."""
        self._model_loaded = False
        self._model_loading = False
        self._model_failed = False
        self._coco_idx = 0
        self._showcase_count = 0
        self.train_next.config(state="disabled", bg="#9e9e9e")
        self._set_class_list(list(COCO_CLASSES))
        if not self.model_pb.winfo_ismapped():
            self.model_pb.pack(before=self._coco_header, pady=6)
        self._load_model_async()

    def _finish_showcase(self):
        self.model_pb.stop()
        self.model_pb.pack_forget()
        names = self._model_names()
        self._set_class_list(names)                 # 실제 모델 클래스로 갱신
        self.model_status.config(
            text=f"✓ 모델 준비 완료 — {getattr(self, '_loaded_info', '')} "
                 f"· {len(names)}종 식별 (목록 스크롤)",
            fg="#2e7d32")
        try:
            self.coco_list.see(0)
        except Exception:
            pass
        self.train_next.config(state="normal", bg=ACCENT)
        try:
            current = self.nb.nametowidget(self.nb.select())
        except Exception:
            current = None
        if current is self.tab_train and self.auto_yolo.get():
            self.root.after(700, lambda: self._animate_press(
                self.train_next, lambda: self.nb.select(self.rec_view)))

    def _show_manual(self):
        import manual
        manual.show_manual(self.root)

    def _show_pdf_manual(self):
        import pdf_viewer
        pdf_viewer.open_manual(self.root)

    def _on_close(self):
        self._hide_wait_dialog()
        try:
            self.rec_view.on_close()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
