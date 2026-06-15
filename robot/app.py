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
import json
import threading
import configparser
import subprocess

import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox

import serial.tools.list_ports as list_ports
from PIL import Image, ImageTk

from paths import (BASE, ROBOT_DIR, CONFIG_INI, LOGO_PATH, ACTIVE_ONNX,
                   DATA_DIR, ensure_dirs)
from version import __version__
from motion_table import COCO_CLASSES, coco_kr
import trainer
import yolo as yolo_mod
from object_actions import ActionEditor
from block_editor import BlockEditor
from recognition_view import RecognitionView
import project

PY = sys.executable
WIN_STATE = os.path.join(DATA_DIR, "window.json")   # 메인 윈도 위치/크기 기억
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
        self.root.title(f"YOLO 기반 휴머노이드  ROBO COMMANDER  v{__version__}")
        self.root.minsize(1080, 640)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win_w = min(1180, sw)
        x = (sw - win_w) // 2
        # 지난번 종료한 가로 위치/너비는 기억(트리플 모니터)
        saved = self._load_win_geom()
        if saved:
            import re
            m = re.match(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", saved)
            if m:
                win_w = int(m.group(1))
                x = int(m.group(3))
        # 세로는 항상 화면 위아래로 꽉 채움(작업표시줄만 약간 여유)
        win_h = sh - 56
        self.root.geometry(f"{win_w}x{win_h}+{int(x)}+0")
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
        self._web_proc = None
        # 자동 진행 옵션 (체크박스)
        self.auto_dev = tk.BooleanVar(value=True)    # 설정 후 자동 이동
        self.auto_yolo = tk.BooleanVar(value=False)  # 모델 준비 후 자동 이동
        # 항상 위(코딩하면서 카메라를 볼 수 있게) — 기본 ON
        self.always_top = tk.BooleanVar(value=True)

        self._header()

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_dev = self._tab_devices(self.nb)
        self.tab_train = self._tab_training(self.nb)
        self.tab_act = self._tab_actions(self.nb)
        self.rec_view = RecognitionView(self.nb)
        self.nb.add(self.tab_dev, text="  ①  ⚙ 로봇장치설정  ")
        self.nb.add(self.tab_train, text="  ②  🧠 인공지능학습  ")
        self.nb.add(self.tab_act, text="  ③  🎯 인식및반응설정  ")
        self.nb.add(self.rec_view, text="  ④  ▶ 자율활동시작  ")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._cur_project = None                       # 현재 프로젝트 이름
        self._build_menu()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._apply_topmost()                          # 항상 위 적용
        self.root.after(400, self._start_flow)         # 시퀀스 시작

    # ============================================================
    # 프로젝트 메뉴 (인식및반응 설정을 폴더 단위로 저장/불러오기)
    # ============================================================
    def _build_menu(self):
        mbar = tk.Menu(self.root)
        pm = tk.Menu(mbar, tearoff=0)
        pm.add_command(label="새 프로젝트(비우기)", command=self._project_new)
        pm.add_separator()
        pm.add_command(label="프로젝트 저장          Ctrl+S",
                       command=self._project_save)
        pm.add_command(label="다른 이름으로 저장…",
                       command=self._project_save_as)
        pm.add_command(label="프로젝트 불러오기…      Ctrl+O",
                       command=self._project_open)
        pm.add_separator()
        pm.add_command(label="프로젝트 폴더 열기",
                       command=self._project_open_folder)
        mbar.add_cascade(label="📁 프로젝트", menu=pm)
        self.root.config(menu=mbar)
        self.root.bind_all("<Control-s>", lambda e: self._project_save())
        self.root.bind_all("<Control-o>", lambda e: self._project_open())

    def _refresh_all_action_tabs(self):
        """3개 하위 탭 + 자율활동 매핑을 현재 JSON으로 동기화."""
        for fn in (lambda: self.action_editor.reload(),
                   lambda: self.block_view.reload(),
                   self._refresh_python_code,
                   lambda: self.rec_view.reload_mapping()):
            try:
                fn()
            except Exception:
                pass

    def _flush_editors(self):
        """편집 중인 내용을 JSON에 먼저 저장(저장 직전 호출)."""
        try:
            cur = self._act_sub.nametowidget(self._act_sub.select())
            if cur is self._act_tab_table:
                self.action_editor._autosave()
        except Exception:
            pass

    def _set_project(self, name):
        self._cur_project = name
        base = f"YOLO 기반 휴머노이드  ROBO COMMANDER  v{__version__}"
        self.root.title(base + (f"   —   [{name}]" if name else ""))

    def _project_new(self):
        if not messagebox.askyesno(
                "새 프로젝트", "현재 인식및반응 설정을 모두 비웁니다. 계속할까요?"):
            return
        import object_actions
        object_actions.save_actions({})
        self._set_project(None)
        self._refresh_all_action_tabs()

    def _project_save(self):
        if not self._cur_project:
            return self._project_save_as()
        self._flush_editors()
        try:
            folder = project.save_project(self._cur_project)
            messagebox.showinfo("프로젝트 저장",
                                f"‘{self._cur_project}’ 저장 완료\n{folder}")
        except Exception as e:
            messagebox.showerror("프로젝트 저장 실패", str(e))

    def _project_save_as(self):
        name = simpledialog.askstring(
            "다른 이름으로 저장", "프로젝트 이름:",
            initialvalue=self._cur_project or "내프로젝트", parent=self.root)
        if not name:
            return
        self._flush_editors()
        try:
            folder = project.save_project(name)
            self._set_project(name)
            messagebox.showinfo("프로젝트 저장",
                                f"‘{name}’ 저장 완료\n{folder}")
        except Exception as e:
            messagebox.showerror("프로젝트 저장 실패", str(e))

    def _project_open(self):
        folder = filedialog.askdirectory(
            title="프로젝트 폴더 선택 (actions.json 이 든 폴더)",
            initialdir=project.projects_root())
        if not folder:
            return
        try:
            mapping = project.load_project(folder)
            project.apply_mapping(mapping)
            self._set_project(os.path.basename(folder.rstrip("/\\")))
            self._refresh_all_action_tabs()
            self.nb.select(self.tab_act)
            messagebox.showinfo(
                "프로젝트 불러오기",
                f"‘{self._cur_project}’ 불러오기 완료 ({len(mapping)}개 객체)")
        except Exception as e:
            messagebox.showerror("불러오기 실패", str(e))

    def _project_open_folder(self):
        try:
            os.startfile(project.projects_root())
        except Exception:
            pass

    # ---------- 항상 위(맨 앞) ----------
    def _apply_topmost(self):
        try:
            self.root.attributes("-topmost", bool(self.always_top.get()))
        except Exception:
            pass

    def _suspend_topmost(self):
        """자식/하위 프로세스 창(설정·웹뷰 등)이 가려지지 않도록 잠시 해제."""
        try:
            self.root.attributes("-topmost", False)
        except Exception:
            pass

    def _get_active_mtime(self):
        try:
            return os.path.getmtime(ACTIVE_ONNX) \
                if os.path.exists(ACTIVE_ONNX) else 0
        except Exception:
            return 0

    # ---------- 학습 웹앱(서버) 연결 ----------
    def _get_train_url(self):
        default = os.getenv("TRAIN_URL", "http://127.0.0.1:7860")
        try:
            with open(os.path.join(DATA_DIR, "train_url.txt"),
                      encoding="utf-8") as f:
                return f.read().strip() or default
        except Exception:
            return default

    def _save_train_url(self):
        url = (self.train_url_var.get() or "").strip()
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(os.path.join(DATA_DIR, "train_url.txt"), "w",
                      encoding="utf-8") as f:
                f.write(url)
            self.model_status.config(text=f"학습 웹앱 주소 저장: {url}",
                                     fg="#2e7d32")
        except Exception:
            pass

    def _open_train_web(self):
        """학습 웹앱(서버) 페이지를 웹뷰로 열고, 닫히면 모델 변경 감지→재로드."""
        if self._train_proc is not None and self._train_proc.poll() is None:
            return
        url = (self.train_url_var.get() or "").strip() or self._get_train_url()
        try:
            self.rec_view.stop()       # 인식이 잡은 카메라/포트 반환
        except Exception:
            pass
        self._train_before_mtime = self._get_active_mtime()
        self._suspend_topmost()
        self._train_proc = subprocess.Popen(
            [PY, os.path.join(ROBOT_DIR, "webview_window.py"),
             url, "학습 웹앱"], cwd=BASE, env=self._child_env())
        self._show_wait_dialog(
            title="학습 웹앱",
            heading="🌐  학습 웹앱(서버)",
            msg=("학습 웹앱에서 데이터 수집·학습·내보내기를 진행하세요.\n"
                 "끝나면 active.onnx·active.names 를 model/ 폴더에 넣고\n"
                 "이 창을 닫으면 자동으로 모델을 확인합니다."),
            waiting="⏳ 학습 웹앱 창을 기다리는 중... (이 창은 잠금 상태)")
        self._watch_train_proc()

    def _open_training(self):
        """(구) 로컬 학습 스튜디오 — 별도 프로세스로 열고, 닫히면 모델 변경 시 재로드."""
        if self._train_proc is not None and self._train_proc.poll() is None:
            return
        # 학습 스튜디오가 카메라를 쓰므로 인식이 잡은 포트/카메라를 먼저 반환
        try:
            self.rec_view.stop()
        except Exception:
            pass
        self._train_before_mtime = self._get_active_mtime()
        self._suspend_topmost()
        self._train_proc = subprocess.Popen(
            [PY, os.path.join(ROBOT_DIR, "trainer.py")], cwd=BASE,
            env=self._child_env())
        self._show_wait_dialog(
            title="로봇 학습 진행 중",
            heading="🧠  로봇 학습 스튜디오",
            msg=("별도 학습 스튜디오 창에서 데이터 수집·학습·모델 적용을 진행하세요.\n"
                 "마치고 그 창을 닫으면 자동으로 계속됩니다."),
            waiting="⏳ 학습 스튜디오를 기다리는 중... (이 창은 잠금 상태)")
        self._watch_train_proc()

    def _watch_train_proc(self):
        if self._train_proc is not None and self._train_proc.poll() is None:
            self.root.after(700, self._watch_train_proc)
            return
        # 트레이너가 닫힘(뒤로) → 잠금 해제 후, active 모델이 바뀌었으면 다시 로드
        self._hide_wait_dialog()
        self._apply_topmost()
        if self._get_active_mtime() != self._train_before_mtime:
            self.model_status.config(text="🔄 모델 변경 감지 — 다시 로드합니다...",
                                     fg="#ef6c00")
            self._reload_model()

    def _child_env(self):
        """서브프로세스 창이 메인 윈도 중앙에 뜨도록 중심 좌표를 환경변수로 전달."""
        env = os.environ.copy()
        try:
            self.root.update_idletasks()
            cx = self.root.winfo_rootx() + self.root.winfo_width() // 2
            cy = self.root.winfo_rooty() + self.root.winfo_height() // 2
            env["ROBO_CENTER"] = f"{cx},{cy}"
        except Exception:
            pass
        return env

    def _open_webview(self):
        """로고 클릭 → kdt2025.com 을 웹뷰(별도 프로세스)로 열고 메인 윈도 잠금."""
        if self._web_proc is not None and self._web_proc.poll() is None:
            return
        self._suspend_topmost()
        self._web_proc = subprocess.Popen(
            [PY, os.path.join(ROBOT_DIR, "webview_window.py"),
             "https://kdt2025.com", "KDT 2025"], cwd=BASE,
            env=self._child_env())
        self._show_wait_dialog(
            title="웹 페이지 보기",
            heading="🌐  KDT 2025  (kdt2025.com)",
            msg="웹 페이지를 웹뷰 창에서 보는 중입니다.\n"
                "창을 닫으면 자동으로 계속됩니다.",
            waiting="⏳ 웹 페이지 창을 기다리는 중... (이 창은 잠금 상태)")
        self._watch_web_proc()

    def _watch_web_proc(self):
        if self._web_proc is not None and self._web_proc.poll() is None:
            self.root.after(500, self._watch_web_proc)
            return
        self._hide_wait_dialog()
        self._apply_topmost()

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
        tk.Label(header, text="🤖  YOLO 기반 휴머노이드  ROBO COMMANDER",
                 font=("Malgun Gothic", 17, "bold"), fg="white",
                 bg=HEADER_BG).pack(side="left", padx=20)
        try:
            img = Image.open(LOGO_PATH)
            h = 46
            w = max(1, int(img.width * h / img.height))
            self._logo = ImageTk.PhotoImage(img.resize((w, h)))
            logo_lbl = tk.Label(header, image=self._logo, bg=HEADER_BG,
                                cursor="hand2")
            logo_lbl.pack(side="right", padx=20)
            logo_lbl.bind("<Button-1>", lambda e: self._open_webview())
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

        tk.Checkbutton(
            header, text="📌 항상 위", variable=self.always_top,
            command=self._apply_topmost, font=("Malgun Gothic", 9, "bold"),
            fg="#ffd54f", bg=HEADER_BG, selectcolor=HEADER_BG,
            activebackground=HEADER_BG, activeforeground="#ffd54f",
            highlightthickness=0, bd=0, cursor="hand2").pack(
            side="right", padx=10)

    # ---------- 탭: 포트/장치 ----------
    def _tab_devices(self, nb):
        f = ttk.Frame(nb)
        tk.Label(f, text="① 로봇장치설정", font=("Malgun Gothic", 16, "bold"),
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
            btns, text="다음 → 인공지능학습 ▶", font=("Malgun Gothic", 11, "bold"),
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
        tk.Label(f, text="② 인공지능학습", font=("Malgun Gothic", 16, "bold"),
                 bg=BG).pack(pady=(26, 6))

        self.model_status = tk.Label(
            f, text="cocoDataSet Class 로딩 준비...",
            font=("Malgun Gothic", 12, "bold"),
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

        # 학습 서버(웹앱) 주소
        urow = tk.Frame(f, bg=BG); urow.pack(pady=(4, 0))
        tk.Label(urow, text="학습 웹앱 주소:", font=("Malgun Gothic", 9),
                 bg=BG, fg="#555").pack(side="left")
        self.train_url_var = tk.StringVar(value=self._get_train_url())
        tk.Entry(urow, textvariable=self.train_url_var, width=30).pack(
            side="left", padx=(4, 4))
        tk.Button(urow, text="주소 저장", bg="#6a1b9a", fg="white",
                  relief="flat", cursor="hand2",
                  font=("Malgun Gothic", 9, "bold"),
                  command=self._save_train_url).pack(side="left", ipadx=4)

        btns = tk.Frame(f, bg=BG); btns.pack(pady=18)
        tk.Button(btns, text="🌐 학습 웹앱 열기",
                  font=("Malgun Gothic", 11, "bold"), bg="#6a1b9a", fg="white",
                  relief="flat", cursor="hand2", height=2, width=24,
                  command=self._open_train_web).pack(side="left", padx=6)
        self.train_next = tk.Button(
            btns, text="다음 → 자율활동시작 ▶", font=("Malgun Gothic", 11, "bold"),
            bg="#9e9e9e", fg="white", relief="flat", height=2, width=18,
            state="disabled",
            command=lambda: self.nb.select(self.rec_view))
        self.train_next.pack(side="left", padx=6)

        tk.Checkbutton(f, text="모델 준비되면 자동으로 자율활동시작 단계로 이동",
                       variable=self.auto_yolo, bg=BG,
                       font=("Malgun Gothic", 9)).pack(pady=(6, 0))
        tk.Label(f, text="※ 학습은 CPU라 느립니다. 클래스당 20~50장, 에폭 10~30 권장.",
                 font=("Malgun Gothic", 9), fg="#999", bg=BG).pack(pady=(8, 0))
        return f

    # ---------- 탭: 객체 반응 (표 / 블록 / 파이썬 3-탭) ----------
    def _tab_actions(self, nb):
        f = ttk.Frame(nb)
        sub = ttk.Notebook(f)
        sub.pack(fill="both", expand=True, padx=2, pady=2)

        # ③-1  액션스크립터 (기존 ActionEditor 표)
        tab_table = ttk.Frame(sub)
        self.action_editor = ActionEditor(
            tab_table, class_names=trainer.load_classes())
        self.action_editor.pack(fill="both", expand=True)
        sub.add(tab_table, text="  📋 액션스크립터  ")
        self._act_tab_table = tab_table

        # ③-2  블록 코딩 (캔버스 드래그형)
        tab_block = ttk.Frame(sub)
        self.block_view = BlockEditor(tab_block,
                                      on_change=self._on_block_change)
        self.block_view.pack(fill="both", expand=True)
        sub.add(tab_block, text="  🧩 블록 코딩  ")
        self._act_tab_block = tab_block

        # ③-3  AI 생성 파이썬 코드 (보기 전용, 탭 열 때 자동 생성)
        tab_py = ttk.Frame(sub)
        self._build_python_tab(tab_py)
        sub.add(tab_py, text="  🐍 AI 생성 파이썬 코드  ")

        self._act_sub = sub
        self._act_tab_py = tab_py
        self._act_prev = tab_table
        sub.bind("<<NotebookTabChanged>>", self._on_act_sub_changed)
        return f

    def _build_python_tab(self, parent):
        bar = tk.Frame(parent, bg=BG); bar.pack(fill="x", padx=8, pady=(8, 0))
        tk.Label(bar,
                 text="🐍 AI 생성 파이썬 코드  (보기 전용 · 액션스크립터/블록을 바꾸면 자동 갱신)",
                 font=("Malgun Gothic", 11, "bold"), bg=BG).pack(side="left")
        tk.Button(bar, text="📋 복사", cursor="hand2", relief="flat",
                  bg="#607d8b", fg="white",
                  command=self._copy_python_code).pack(side="right")
        tk.Button(bar, text="↻ 새로고침", cursor="hand2", relief="flat",
                  command=self._refresh_python_code).pack(side="right",
                                                          padx=(0, 6))
        wrap = tk.Frame(parent); wrap.pack(fill="both", expand=True,
                                           padx=8, pady=8)
        self.py_text = tk.Text(wrap, font=("Consolas", 11), wrap="none",
                               bg="#1e1e1e", fg="#dcdcdc", relief="flat",
                               insertbackground="#dcdcdc", padx=10, pady=8,
                               state="disabled")
        ysb = ttk.Scrollbar(wrap, orient="vertical",
                            command=self.py_text.yview)
        xsb = ttk.Scrollbar(wrap, orient="horizontal",
                            command=self.py_text.xview)
        self.py_text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.py_text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

    def _refresh_python_code(self):
        try:
            import code_gen
            src = code_gen.generate_python()
        except Exception as e:
            src = f"# 코드 생성 오류: {e}"
        try:
            self.py_text.config(state="normal")
            self.py_text.delete("1.0", "end")
            self.py_text.insert("1.0", src)
            self.py_text.config(state="disabled")
        except Exception:
            pass

    def _copy_python_code(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.py_text.get("1.0", "end-1c"))
        except Exception:
            pass

    def _on_block_change(self):
        # 블록 편집 → 파이썬 코드 즉시 갱신(보이는 중이면)
        try:
            self._refresh_python_code()
        except Exception:
            pass

    def _on_act_sub_changed(self, _evt):
        try:
            cur = self._act_sub.nametowidget(self._act_sub.select())
        except Exception:
            return
        prev = getattr(self, "_act_prev", None)
        # 떠나는 탭이 액션스크립터면 위젯 내용을 먼저 저장(JSON이 최신이 되도록).
        # 블록 편집기는 변경 즉시 저장하므로 따로 저장 불필요.
        if prev is self._act_tab_table:
            try:
                self.action_editor._autosave()
            except Exception:
                pass
        # 들어온 탭을 JSON에서 다시 읽어 동기화(단일 데이터 소스)
        if cur is self._act_tab_table:
            try:
                self.action_editor.reload()
            except Exception:
                pass
        elif cur is self._act_tab_block:
            try:
                self.block_view.reload()
            except Exception:
                pass
        elif cur is self._act_tab_py:
            self._refresh_python_code()
        self._act_prev = cur

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
        self._suspend_topmost()
        self._dev_proc = subprocess.Popen(
            [PY, os.path.join(ROBOT_DIR, "port_selector.py")], cwd=BASE,
            env=self._child_env())
        self._show_wait_dialog()        # 메인 윈도 잠금 + 안내
        self._watch_device_proc()

    def _show_wait_dialog(self, title="장치 및 로봇 설정 진행 중",
                          heading="🔧  장치 및 로봇 설정",
                          msg=("별도 설정 창에서 포트·카메라·마이크를 확인/테스트하세요.\n"
                               "설정을 마치고 그 창을 닫으면 자동으로 계속됩니다."),
                          waiting="⏳ 설정 창을 기다리는 중... (이 창은 잠금 상태)"):
        if self._wait_dlg is not None:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg="white")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        tk.Label(dlg, text=heading,
                 font=("Malgun Gothic", 14, "bold"), bg="white").pack(
            pady=(20, 6), padx=24)
        tk.Label(dlg, text=msg,
                 font=("Malgun Gothic", 10), fg="#555", bg="white",
                 justify="center").pack(padx=24)
        pb = ttk.Progressbar(dlg, mode="indeterminate", length=320)
        pb.pack(pady=16); pb.start(12)
        tk.Label(dlg, text=waiting,
                 font=("Malgun Gothic", 9), fg="#ef6c00", bg="white").pack(
            pady=(0, 16))
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)   # 임의 닫기 방지
        self.root.update_idletasks()
        # 메인 윈도 중앙(멀티모니터 음수 좌표도 그대로 — 0으로 클램프 금지)
        x = self.root.winfo_rootx() + (self.root.winfo_width() - 420) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - 180) // 2
        dlg.geometry(f"420x180+{int(x)}+{int(y)}")
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
        self._apply_topmost()
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
                    + "  ·  ‘다음 → 인공지능학습’을 누르세요", fg="#2e7d32")

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
            # 매핑 반영 + 렌더 루프 재가동(멈춤 방지)
            try:
                self.rec_view.on_show()
            except Exception:
                pass
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
        self.model_status.config(text="⏳ cocoDataSet Class 로딩중... 식별 가능한 객체:",
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

    def _load_win_geom(self):
        try:
            with open(WIN_STATE, encoding="utf-8") as f:
                return json.load(f).get("geometry") or None
        except Exception:
            return None

    def _save_win_geom(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(WIN_STATE, "w", encoding="utf-8") as f:
                json.dump({"geometry": self.root.geometry()}, f)
        except Exception:
            pass

    def _on_close(self):
        self._save_win_geom()        # 현재 위치/크기 기억
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
