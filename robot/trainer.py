# coding: utf-8
"""
trainer.py
==========
로봇 학습 스튜디오 — 하나의 창에서 탭으로 순차 진행 (Teachable Machine 스타일).

  ① 데이터 수집 : 실시간 카메라, 클래스 추가/삭제, 단발/연속 캡처, 썸네일
  ② 학습        : ultralytics 로 학습(서브프로세스), 로그 스트리밍
  ③ 모델 적용   : best.pt 저장 / 기본 모델 다운로드 / 폴더에서 선택 → active 적용

상단에 ①→②→③ 스텝 인디케이터를 두어 진행 단계를 한눈에 보여준다.
"""

import os
import sys
import csv
import time
import shutil
import threading
import subprocess
import configparser

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

try:
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

from paths import (
    BASE, DATASET, IMG_DIR, LBL_DIR, CLASSES_TXT, DATA_YAML, MODELS_DIR,
    ACTIVE_MODEL, BASE_WEIGHTS, RUNS_DIR, BEST_WEIGHTS, CONFIG_INI,
    set_active_name, get_active_name,
)
import sound

PY = sys.executable
# 학습 결과 산출물 위치 (ultralytics: project=runs, name=custom)
RUN_DIR = os.path.join(RUNS_DIR, "custom")
RESULTS_CSV = os.path.join(RUN_DIR, "results.csv")
RESULTS_PNG = os.path.join(RUN_DIR, "results.png")

_FONT = ("Malgun Gothic", 11)
_FONT_BIG = ("Malgun Gothic", 13, "bold")
SIZES = [144, 200, 320, 640]

# 색상 테마
BG = "#f4f6fb"
HEADER_BG = "#1f2a44"
ACCENT = "#1565c0"
GREEN = "#28a745"
ORANGE = "#ef6c00"

# 다운로드 가능한 기본 모델 (ultralytics)
DOWNLOADABLE = [
    "yolov5su", "yolov8n", "yolov8s", "yolov8m", "yolov8l",
    "yolo11n", "yolo11s", "yolo11m", "yolo11l",
]


# ============================================================
# 데이터셋 유틸
# ============================================================
def load_classes() -> list:
    if not os.path.exists(CLASSES_TXT):
        return []
    try:
        with open(CLASSES_TXT, encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []


def save_classes(classes: list) -> None:
    os.makedirs(DATASET, exist_ok=True)
    with open(CLASSES_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(classes))


def _imwrite(path: str, img) -> bool:
    """Windows에서 한글/유니코드 경로 cv2.imwrite 실패를 우회해 저장."""
    try:
        ext = os.path.splitext(path)[1] or ".jpg"
        ok, buf = cv2.imencode(ext, img)
        if not ok:
            return False
        with open(path, "wb") as f:
            f.write(buf.tobytes())
        return True
    except Exception:
        return False


def imread_unicode(path):
    """유니코드 경로 안전 이미지 읽기 (썸네일/검증용)."""
    import numpy as np
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _class_of(filename: str) -> str:
    """'cls_0001.jpg' → 'cls' (마지막 _숫자 만 분리)."""
    stem = os.path.splitext(filename)[0]
    return stem.rsplit("_", 1)[0]


def list_images(cls: str) -> list:
    if not os.path.isdir(IMG_DIR):
        return []
    out = []
    for n in sorted(os.listdir(IMG_DIR)):
        if n.lower().endswith(".jpg") and _class_of(n) == cls:
            out.append(os.path.join(IMG_DIR, n))
    return out


def count_images(cls: str) -> int:
    return len(list_images(cls))


def next_index(cls: str) -> int:
    return count_images(cls) + 1


def reindex_labels() -> None:
    """현재 클래스 목록 기준으로 모든 라벨의 class_id를 다시 쓴다."""
    classes = load_classes()
    idx = {c: i for i, c in enumerate(classes)}
    os.makedirs(LBL_DIR, exist_ok=True)
    if not os.path.isdir(IMG_DIR):
        return
    for n in os.listdir(IMG_DIR):
        if not n.lower().endswith(".jpg"):
            continue
        cls = _class_of(n)
        if cls not in idx:
            continue
        stem = os.path.splitext(n)[0]
        with open(os.path.join(LBL_DIR, stem + ".txt"), "w") as f:
            f.write(f"{idx[cls]} 0.5 0.5 1.0 1.0\n")


def delete_class(cls: str) -> None:
    for d in (IMG_DIR, LBL_DIR):
        if os.path.isdir(d):
            for n in list(os.listdir(d)):
                if _class_of(n) == cls:
                    try:
                        os.remove(os.path.join(d, n))
                    except Exception:
                        pass
    save_classes([c for c in load_classes() if c != cls])
    reindex_labels()


def camera_index() -> int:
    cfg = configparser.ConfigParser()
    try:
        cfg.read(CONFIG_INI, encoding="utf-8")
        v = cfg["SETTINGS"].get("last_camera_index")
        return int(v) if v not in (None, "") else 0
    except Exception:
        return 0


def build_data_yaml() -> str:
    reindex_labels()
    classes = load_classes()
    os.makedirs(DATASET, exist_ok=True)
    names = "[" + ", ".join(f'"{c}"' for c in classes) + "]"
    with open(DATA_YAML, "w", encoding="utf-8") as f:
        f.write(f"path: {DATASET.replace(os.sep, '/')}\n")
        f.write("train: images/train\n")
        f.write("val: images/train\n")
        f.write(f"nc: {len(classes)}\n")
        f.write(f"names: {names}\n")
    return DATA_YAML


def _fmt_dur(sec):
    """초 → '1시간 02분 03초' / '2분 05초' / '8초' 형태."""
    sec = int(max(0, sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h:
        return f"{h}시간 {m:02d}분 {s:02d}초"
    if m:
        return f"{m}분 {s:02d}초"
    return f"{s}초"


def read_results_metrics():
    """results.csv 의 마지막 에폭에서 mAP/정밀도/재현율 등을 읽어 dict 로 반환.

    실패 시 빈 dict. 키: mAP50, mAP5095, precision, recall, epochs
    """
    if not os.path.exists(RESULTS_CSV):
        return {}
    try:
        with open(RESULTS_CSV, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return {}
        last = {k.strip(): v for k, v in rows[-1].items() if k is not None}

        def pick(must, excl=()):
            """키에 must 포함, excl 은 모두 미포함인 컬럼 값을 float 으로."""
            for key, val in last.items():
                kl = key.lower()
                if must in kl and not any(e in kl for e in excl):
                    try:
                        return float(val)
                    except Exception:
                        return None
            return None

        return {
            "mAP50": pick("map50", excl=("map50-95",)),
            "mAP5095": pick("map50-95"),
            "precision": pick("precision"),
            "recall": pick("recall"),
            "epochs": len(rows),
        }
    except Exception:
        return {}


# ============================================================
# 탭 1) 데이터 수집
# ============================================================
class CollectTab(ttk.Frame):
    PREVIEW_W = 420
    PREVIEW_H = 320
    THUMB = 72

    def __init__(self, master, studio):
        super().__init__(master)
        self.studio = studio
        self.classes = load_classes()
        self.cap = None
        self.last_frame = None
        self.after_id = None
        self.cont_after = None
        self.continuous = False
        self._thumbs = []
        self._build()

    def _build(self):
        if not (_HAS_CV2 and _HAS_PIL):
            tk.Label(self, text="opencv(cv2) / Pillow(PIL) 가 필요합니다.",
                     font=_FONT, fg="#c62828").pack(pady=40)
            return

        tk.Label(self, text="촬영할 객체를 카메라에 비추고 캡처하세요. "
                 "여러 클래스를 만들 수 있습니다.",
                 font=("Malgun Gothic", 10), fg="#555", bg=BG).pack(
            anchor="w", padx=14, pady=(10, 2))

        # 클래스 줄
        crow = tk.Frame(self, bg=BG); crow.pack(fill="x", padx=14, pady=4)
        tk.Label(crow, text="클래스", font=_FONT, bg=BG).pack(side="left")
        self.class_var = tk.StringVar()
        self.class_combo = ttk.Combobox(crow, textvariable=self.class_var,
                                        values=self.classes, width=20)
        self.class_combo.pack(side="left", padx=(6, 4))
        self.class_combo.bind("<<ComboboxSelected>>",
                              lambda e: self._refresh_thumbs())
        tk.Button(crow, text="+ 추가", cursor="hand2",
                  command=self._add_class).pack(side="left")
        tk.Button(crow, text="🗑 삭제", cursor="hand2",
                  command=self._delete_class).pack(side="left", padx=(4, 0))
        if self.classes:
            self.class_combo.current(0)

        # 저장 크기 줄
        srow = tk.Frame(self, bg=BG); srow.pack(fill="x", padx=14, pady=2)
        tk.Label(srow, text="저장 크기", font=_FONT, bg=BG).pack(side="left")
        self.size_var = tk.IntVar(value=320)
        for s in SIZES:
            tk.Radiobutton(srow, text=f"{s}", variable=self.size_var,
                           value=s, bg=BG).pack(side="left")
        tk.Label(srow, text="px (정사각)", font=("Malgun Gothic", 9),
                 fg="#888", bg=BG).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=4)
        # 좌: 미리보기 + 캡처
        left = tk.Frame(body, bg=BG); left.pack(side="left")
        self.canvas = tk.Canvas(left, width=self.PREVIEW_W,
                                height=self.PREVIEW_H, bg="#1e1e1e",
                                highlightthickness=1, highlightbackground="#555")
        self.canvas.pack()
        self.img_id = self.canvas.create_image(self.PREVIEW_W // 2,
                                               self.PREVIEW_H // 2,
                                               anchor="center")
        brow = tk.Frame(left, bg=BG); brow.pack(pady=6)
        tk.Button(brow, text="📸 캡처", font=_FONT_BIG, bg=GREEN,
                  fg="white", relief="flat", padx=12, cursor="hand2",
                  command=self._capture_once).pack(side="left", padx=4)
        self.cont_btn = tk.Button(brow, text="● 연속 캡처", font=_FONT_BIG,
                                  bg=ACCENT, fg="white", relief="flat",
                                  padx=12, cursor="hand2",
                                  command=self._toggle_continuous)
        self.cont_btn.pack(side="left", padx=4)
        self.count_label = tk.Label(left, text="", font=_FONT, fg=ACCENT,
                                    bg=BG)
        self.count_label.pack()

        # 우: 썸네일
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(right, text="수집된 데이터 (선택 클래스)",
                 font=("Malgun Gothic", 10, "bold"), bg=BG).pack(anchor="w")
        tw = tk.Frame(right); tw.pack(fill="both", expand=True)
        self.thumb_canvas = tk.Canvas(tw, width=320, bg="#fafafa",
                                      highlightthickness=1,
                                      highlightbackground="#ddd")
        tsb = ttk.Scrollbar(tw, orient="vertical",
                            command=self.thumb_canvas.yview)
        self.thumb_inner = tk.Frame(self.thumb_canvas, bg="#fafafa")
        self.thumb_inner.bind("<Configure>", lambda e: self.thumb_canvas.configure(
            scrollregion=self.thumb_canvas.bbox("all")))
        self.thumb_canvas.create_window((0, 0), window=self.thumb_inner,
                                        anchor="nw")
        self.thumb_canvas.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.thumb_canvas.pack(side="left", fill="both", expand=True)

        # 다음 단계
        nav = tk.Frame(self, bg=BG); nav.pack(fill="x", padx=14, pady=(2, 10))
        tk.Button(nav, text="다음: 학습 ▶", font=_FONT, bg=ACCENT, fg="white",
                  relief="flat", cursor="hand2", padx=14,
                  command=lambda: self.studio.goto("train")).pack(side="right")

    # ---------- 카메라 ----------
    def on_show(self):
        if not (_HAS_CV2 and _HAS_PIL):
            return
        self._open_cam()
        self._loop()
        self._update_count()
        self._refresh_thumbs()

    def on_hide(self):
        self._stop_continuous()
        if self.after_id is not None:
            try:
                self.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _open_cam(self):
        if self.cap is not None:
            return
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else 0
        self.cap = cv2.VideoCapture(camera_index(), backend)

    def _loop(self):
        if self.cap is not None:
            ok, frame = self.cap.read()
            if ok and frame is not None:
                self.last_frame = frame
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb = cv2.resize(rgb, (self.PREVIEW_W, self.PREVIEW_H))
                self.imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))
                self.canvas.itemconfig(self.img_id, image=self.imgtk)
            self.after_id = self.after(33, self._loop)

    # ---------- 클래스 ----------
    def _cur_class(self):
        return self.class_var.get().strip()

    def _add_class(self):
        name = simpledialog.askstring("클래스 추가", "새 클래스 이름:",
                                      parent=self.winfo_toplevel())
        if not name:
            return
        name = name.strip()
        if name and name not in self.classes:
            self.classes.append(name)
            save_classes(self.classes)
            self.class_combo["values"] = self.classes
            self.class_combo.set(name)
            self._update_count(); self._refresh_thumbs()

    def _delete_class(self):
        cls = self._cur_class()
        if not cls or cls not in self.classes:
            return
        if not messagebox.askyesno(
                "삭제 확인",
                f"‘{cls}’ 클래스와 수집 이미지({count_images(cls)}장)를 삭제할까요?"):
            return
        delete_class(cls)
        self.classes = load_classes()
        self.class_combo["values"] = self.classes
        self.class_combo.set(self.classes[0] if self.classes else "")
        self._update_count(); self._refresh_thumbs()

    # ---------- 캡처 ----------
    def _capture_once(self):
        cls = self._cur_class()
        if not cls:
            messagebox.showwarning("알림", "클래스를 입력/선택하세요.")
            return
        if self.last_frame is None:
            return
        if cls not in self.classes:
            self.classes.append(cls); save_classes(self.classes)
            self.class_combo["values"] = self.classes
        cls_id = self.classes.index(cls)
        os.makedirs(IMG_DIR, exist_ok=True); os.makedirs(LBL_DIR, exist_ok=True)
        n = next_index(cls)
        stem = f"{cls}_{n:04d}"
        size = int(self.size_var.get())
        img = cv2.resize(self.last_frame, (size, size))
        if not _imwrite(os.path.join(IMG_DIR, stem + ".jpg"), img):
            messagebox.showerror("저장 실패", "이미지 저장에 실패했습니다.")
            return
        with open(os.path.join(LBL_DIR, stem + ".txt"), "w") as f:
            f.write(f"{cls_id} 0.5 0.5 1.0 1.0\n")
        sound.player.play_effect(sound.FX_CAPTURE)   # 캡처음
        self._update_count(); self._refresh_thumbs()

    def _toggle_continuous(self):
        self.continuous = not self.continuous
        if self.continuous:
            self.cont_btn.config(text="■ 연속 중지", bg="#c62828")
            self._continuous_step()
        else:
            self._stop_continuous()

    def _stop_continuous(self):
        self.continuous = False
        if self.cont_btn is not None:
            try:
                self.cont_btn.config(text="● 연속 캡처", bg=ACCENT)
            except Exception:
                pass
        if self.cont_after is not None:
            try:
                self.after_cancel(self.cont_after)
            except Exception:
                pass
            self.cont_after = None

    def _continuous_step(self):
        if not self.continuous:
            return
        self._capture_once()
        self.cont_after = self.after(400, self._continuous_step)

    def _update_count(self):
        parts = [f"{c}:{count_images(c)}" for c in self.classes]
        total = sum(count_images(c) for c in self.classes)
        self.count_label.config(
            text=(f"총 {total}장   " + "  ".join(parts)) if parts
            else "아직 수집된 데이터가 없습니다.")

    # ---------- 썸네일 ----------
    def _refresh_thumbs(self):
        for w in self.thumb_inner.winfo_children():
            w.destroy()
        self._thumbs = []
        cls = self._cur_class()
        if not cls:
            return
        imgs = list_images(cls)[-40:]      # 최근 40장
        cols = 4
        for i, p in enumerate(imgs):
            try:
                im = Image.open(p)
                im.thumbnail((self.THUMB, self.THUMB))
                tk_im = ImageTk.PhotoImage(im)
            except Exception:
                continue
            self._thumbs.append(tk_im)
            lbl = tk.Label(self.thumb_inner, image=tk_im, bg="#fafafa")
            lbl.grid(row=i // cols, column=i % cols, padx=3, pady=3)


# ============================================================
# 탭 2) 학습
# ============================================================
class TrainTab(ttk.Frame):
    def __init__(self, master, studio):
        super().__init__(master)
        self.studio = studio
        self.proc = None
        self._build()

    def _build(self):
        tk.Label(self, text="수집한 데이터로 모델을 학습합니다. "
                 "CPU 학습이라 느리니 에폭을 작게 두세요.",
                 font=("Malgun Gothic", 10), fg="#555", bg=BG).pack(
            anchor="w", padx=14, pady=(10, 2))

        self.info = tk.Label(self, text="", font=("Malgun Gothic", 10, "bold"),
                             fg=ACCENT, bg=BG)
        self.info.pack(anchor="w", padx=14)

        row = tk.Frame(self, bg=BG); row.pack(fill="x", padx=14, pady=6)
        tk.Label(row, text="에폭", font=_FONT, bg=BG).pack(side="left")
        self.epoch_var = tk.StringVar(value="30")
        tk.Spinbox(row, from_=1, to=300, width=6,
                   textvariable=self.epoch_var).pack(side="left", padx=(6, 12))
        tk.Label(row, text="이미지", font=_FONT, bg=BG).pack(side="left")
        self.img_var = tk.StringVar(value="320")
        ttk.Combobox(row, textvariable=self.img_var, width=6, state="readonly",
                     values=[str(s) for s in SIZES]).pack(side="left", padx=6)
        self.start_btn = tk.Button(row, text="▶ 학습 시작", font=_FONT_BIG,
                                   bg=GREEN, fg="white", relief="flat",
                                   padx=14, cursor="hand2", command=self._start)
        self.start_btn.pack(side="left", padx=(12, 0))

        self.log = tk.Text(self, height=16, bg="#1e1e1e", fg="#d4d4d4",
                           font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=14, pady=(4, 6))

    def on_show(self):
        classes = load_classes()
        total = sum(count_images(c) for c in classes)
        self.info.config(text=f"클래스 {len(classes)}개 / 이미지 {total}장")

    def _append(self, text):
        def apply():
            try:
                self.log.insert("end", text); self.log.see("end")
            except Exception:
                pass
        try:
            self.after(0, apply)
        except Exception:
            pass

    def _start(self):
        classes = load_classes()
        total = sum(count_images(c) for c in classes)
        if not classes or total < 1:
            messagebox.showwarning("알림", "먼저 ① 데이터 수집에서 데이터를 모으세요.")
            return
        if not os.path.exists(BASE_WEIGHTS):
            messagebox.showerror("오류", f"기본 가중치가 없습니다:\n{BASE_WEIGHTS}\n"
                                 "③ 모델 적용에서 기본 모델을 먼저 다운로드하세요.")
            return
        self.start_btn.config(state="disabled")
        try:
            epochs = int(self.epoch_var.get()); imgsz = int(self.img_var.get())
        except Exception:
            epochs, imgsz = 30, 320
        build_data_yaml()
        self._t0 = time.time()
        self._elapsed = 0.0
        self._append("⏱ 학습 시작: " + time.strftime("%H:%M:%S") + "\n")
        threading.Thread(target=self._worker, args=(epochs, imgsz),
                         daemon=True).start()

    def _worker(self, epochs, imgsz):
        # ultralytics 로 학습. 로그 스트리밍 위해 서브프로세스로.
        code = (
            "from ultralytics import YOLO; "
            "m = YOLO(r'%s'); "
            "m.train(data=r'%s', epochs=%d, imgsz=%d, batch=4, "
            "project=r'%s', name='custom', exist_ok=True, "
            "device='cpu', workers=0)"
            % (BASE_WEIGHTS, DATA_YAML, epochs, imgsz, RUNS_DIR)
        )
        cmd = [PY, "-c", code]
        self._append("학습 시작(ultralytics):\n  " + code + "\n\n")
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=BASE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
            for line in self.proc.stdout:
                self._append(line)
            self.proc.wait()
            if self.proc.returncode == 0:
                self._append(f"\n✓ 학습 완료. 결과: {BEST_WEIGHTS}\n")
                self.after(0, self._show_results)
            else:
                self._append(f"\n✗ 학습 실패 (코드 {self.proc.returncode})\n")
        except Exception as e:
            self._append(f"\n✗ 오류: {e}\n")
        finally:
            self.proc = None
            try:
                self._elapsed = time.time() - getattr(self, "_t0", time.time())
                self._append(f"⏱ 총 소요 시간: {_fmt_dur(self._elapsed)}\n")
            except Exception:
                pass
            try:
                self.after(0, lambda: self.start_btn.config(state="normal"))
            except Exception:
                pass

    # ---------- 학습 결과 (성능 + 그래프) ----------
    def _show_results(self):
        """학습 곡선 그래프 + 최종 mAP/정밀도/재현율을 보여주고 저장/버리기 선택."""
        m = read_results_metrics()
        top = tk.Toplevel(self.winfo_toplevel())
        top.title("학습 결과 — 성능 확인")
        top.configure(bg=BG)
        from scrollable import make_scrollable, fit_window
        fit_window(top, 820, 760)
        body = make_scrollable(top, bg=BG)

        tk.Label(body, text="📊 학습 결과", font=("Malgun Gothic", 15, "bold"),
                 bg=BG).pack(pady=(12, 2))
        ep = m.get("epochs")
        el = getattr(self, "_elapsed", 0.0)
        sub = (f"{ep} 에폭 학습 완료" if ep else "학습 완료")
        if el:
            sub += f"   ·   ⏱ 총 {_fmt_dur(el)} 소요"
        tk.Label(body, text=sub, font=("Malgun Gothic", 10), fg="#555",
                 bg=BG).pack()

        # ----- 성능 지표 카드 -----
        cards = tk.Frame(body, bg=BG); cards.pack(pady=10)
        metrics = [
            ("mAP@50", m.get("mAP50"), "정확도(겹침 50%) — 핵심 지표"),
            ("mAP@50-95", m.get("mAP5095"), "더 엄격한 정확도"),
            ("정밀도(P)", m.get("precision"), "맞다고 한 것 중 실제 맞음"),
            ("재현율(R)", m.get("recall"), "실제 중 찾아낸 비율"),
        ]
        for i, (label, val, desc) in enumerate(metrics):
            self._metric_card(cards, label, val, desc, col=i)

        # mAP50 기준 한줄 평가
        verdict, vcolor = self._verdict(m.get("mAP50"))
        tk.Label(body, text=verdict, font=("Malgun Gothic", 11, "bold"),
                 fg=vcolor, bg=BG).pack(pady=(2, 8))

        # ----- 학습 곡선 그래프 -----
        if _HAS_PIL and os.path.exists(RESULTS_PNG):
            try:
                img = Image.open(RESULTS_PNG)
                maxw = 760
                if img.width > maxw:
                    h = int(img.height * maxw / img.width)
                    img = img.resize((maxw, h))
                photo = ImageTk.PhotoImage(img)
                top._graph = photo                  # 참조 유지
                tk.Label(body, image=photo, bg=BG).pack(padx=10, pady=6)
            except Exception:
                pass
        else:
            tk.Label(body, text="(학습 곡선 그래프(results.png)를 찾지 못했습니다)",
                     font=("Malgun Gothic", 9), fg="#999", bg=BG).pack(pady=6)

        # ----- 저장 / 버리기 -----
        btns = tk.Frame(body, bg=BG); btns.pack(pady=(8, 14))
        tk.Button(btns, text="💾 이 모델 저장", font=_FONT_BIG, bg=GREEN,
                  fg="white", relief="flat", cursor="hand2", padx=16, pady=4,
                  command=lambda: self._save_model(top)).pack(side="left",
                                                              padx=6)
        tk.Button(btns, text="🗑 버리기", font=_FONT_BIG, bg="#c62828",
                  fg="white", relief="flat", cursor="hand2", padx=16, pady=4,
                  command=lambda: self._discard(top)).pack(side="left", padx=6)
        tk.Button(btns, text="닫기", font=_FONT_BIG, bg="#607d8b",
                  fg="white", relief="flat", cursor="hand2", padx=16, pady=4,
                  command=top.destroy).pack(side="left", padx=6)

        try:
            top.transient(self.winfo_toplevel())
            top.lift(); top.attributes("-topmost", True)
            top.grab_set()                      # 다른 창 잠금(모달)
            top.after(60, top.focus_force)
        except Exception:
            pass

    def _metric_card(self, parent, label, val, desc, col):
        txt = f"{val*100:.1f}%" if isinstance(val, float) else "—"
        color = "#999"
        if isinstance(val, float):
            color = "#2e7d32" if val >= 0.8 else (ORANGE if val >= 0.5
                                                  else "#c62828")
        card = tk.Frame(parent, bg="white", highlightthickness=1,
                        highlightbackground="#dce3f0")
        card.grid(row=0, column=col, padx=6, ipadx=10, ipady=8, sticky="n")
        tk.Label(card, text=label, font=("Malgun Gothic", 10, "bold"),
                 fg="#555", bg="white").pack()
        tk.Label(card, text=txt, font=("Consolas", 20, "bold"), fg=color,
                 bg="white").pack()
        tk.Label(card, text=desc, font=("Malgun Gothic", 8), fg="#999",
                 bg="white", wraplength=150, justify="center").pack()

    @staticmethod
    def _verdict(map50):
        if not isinstance(map50, float):
            return "성능 지표를 읽지 못했습니다. 그래프로 직접 확인하세요.", "#999"
        if map50 >= 0.8:
            return "👍 우수합니다 — 저장해서 바로 써도 좋아요.", "#2e7d32"
        if map50 >= 0.5:
            return "🙂 쓸 만합니다 — 데이터를 더 모으면 더 좋아져요.", ORANGE
        return "👎 아직 낮습니다 — 데이터를 더 모으거나 에폭을 늘려 다시 학습하세요.", "#c62828"

    def _ask_model_name(self, parent):
        """./model 폴더의 기존 모델 목록을 보여주며 저장 이름을 입력받는다."""
        existing = []
        if os.path.isdir(MODELS_DIR):
            existing = sorted(f for f in os.listdir(MODELS_DIR)
                              if f.lower().endswith(".pt"))
        dlg = tk.Toplevel(parent)
        dlg.title("모델 저장 이름")
        dlg.configure(bg=BG)
        dlg.transient(parent)
        result = {"name": None}

        tk.Label(dlg, text="저장할 모델 이름 (./model 폴더)",
                 font=("Malgun Gothic", 12, "bold"), bg=BG).pack(
            padx=18, pady=(14, 6))

        if existing:
            tk.Label(dlg, text="이미 있는 모델 — 클릭하면 이름이 채워집니다 "
                     "(같은 이름으로 저장하면 덮어씀):",
                     font=("Malgun Gothic", 9), fg="#555", bg=BG).pack(
                anchor="w", padx=18)
            lbf = tk.Frame(dlg); lbf.pack(fill="x", padx=18, pady=(2, 4))
            lb = tk.Listbox(lbf, height=min(6, len(existing)),
                            font=("Consolas", 10))
            for f in existing:
                lb.insert("end", f)
            sb = ttk.Scrollbar(lbf, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            lb.pack(side="left", fill="x", expand=True)
            lb.bind("<<ListboxSelect>>",
                    lambda e: (var.set(lb.get(lb.curselection()[0]))
                               if lb.curselection() else None))
        else:
            tk.Label(dlg, text="(아직 저장된 모델이 없습니다)",
                     font=("Malgun Gothic", 9), fg="#999", bg=BG).pack(
                anchor="w", padx=18)

        var = tk.StringVar()
        ent = tk.Entry(dlg, textvariable=var, font=("Consolas", 12))
        ent.pack(fill="x", padx=18, pady=(8, 2))
        hint = tk.Label(dlg, text="", font=("Malgun Gothic", 9), bg=BG)
        hint.pack(anchor="w", padx=18)

        def _norm(n):
            n = n.strip()
            if n and not n.lower().endswith(".pt"):
                n += ".pt"
            return n

        def _on_change(*_):
            n = _norm(var.get())
            if n and n in existing:
                hint.config(text=f"⚠ '{n}' 이(가) 이미 있어요 — 저장 시 덮어씁니다.",
                            fg=ORANGE)
            else:
                hint.config(text="", fg="#555")
        var.trace_add("write", _on_change)

        def ok():
            n = _norm(var.get())
            if not n:
                hint.config(text="이름을 입력하세요.", fg="#c62828")
                return
            if n in existing and not messagebox.askyesno(
                    "덮어쓰기", f"'{n}' 을(를) 덮어쓸까요?", parent=dlg):
                return
            result["name"] = n
            dlg.destroy()

        bar = tk.Frame(dlg, bg=BG); bar.pack(fill="x", padx=18, pady=12)
        tk.Button(bar, text="취소", width=10,
                  command=dlg.destroy).pack(side="right")
        tk.Button(bar, text="저장", width=12, bg=GREEN, fg="white",
                  relief="flat", cursor="hand2",
                  command=ok).pack(side="right", padx=(0, 8))
        ent.bind("<Return>", lambda e: ok())

        dlg.update_idletasks()
        try:
            dlg.grab_set(); ent.focus_set()
            dlg.lift(); dlg.attributes("-topmost", True)
        except Exception:
            pass
        parent.wait_window(dlg)
        # 대화상자가 닫히며 부모(결과창)의 모달 잠금이 풀리므로 다시 건다
        try:
            if parent.winfo_exists():
                parent.grab_set()
        except Exception:
            pass
        return result["name"]

    def _save_model(self, top):
        if not os.path.exists(BEST_WEIGHTS):
            messagebox.showerror("오류", "저장할 모델(best.pt)을 찾지 못했습니다.")
            return
        name = self._ask_model_name(top)
        if not name:
            return
        if not name.lower().endswith(".pt"):
            name += ".pt"
        os.makedirs(MODELS_DIR, exist_ok=True)
        dst = os.path.join(MODELS_DIR, name)
        try:
            shutil.copy(BEST_WEIGHTS, dst)
            shutil.copy(dst, ACTIVE_MODEL)   # 저장과 동시에 인식에 바로 적용
            set_active_name(name)            # 원본 이름 기록
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {e}")
            return
        self._append(f"💾 저장·적용: {name}\n")
        try:
            top.destroy()
        except Exception:
            pass
        self.studio.goto("swap")

    def _discard(self, top):
        if not messagebox.askyesno(
                "버리기", "이 학습 결과를 저장하지 않고 버릴까요?"):
            return
        try:
            top.destroy()
        except Exception:
            pass
        self._append("• 학습 결과를 버렸습니다. 데이터를 보강해 다시 학습해 보세요.\n")

    def is_busy(self) -> bool:
        return self.proc is not None

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None


# ============================================================
# 탭 3) 모델 적용 / 다운로드
# ============================================================
class SwapTab(ttk.Frame):
    def __init__(self, master, studio):
        super().__init__(master)
        self.studio = studio
        self._build()

    def _build(self):
        tk.Label(self, text="학습한 모델이나 기본 모델을 인식에 적용(active)합니다.",
                 font=("Malgun Gothic", 10), fg="#555", bg=BG).pack(
            anchor="w", padx=14, pady=(10, 2))

        banner = tk.Frame(self, bg="#e8f5e9", highlightthickness=1,
                          highlightbackground="#a5d6a7")
        banner.pack(fill="x", padx=14, pady=(0, 8))
        self.active_lbl = tk.Label(banner, text="", font=("Malgun Gothic", 13,
                                                          "bold"),
                                   fg="#1b5e20", bg="#e8f5e9", anchor="w",
                                   justify="left")
        self.active_lbl.pack(fill="x", padx=12, pady=9)

        # 다운로드 섹션
        df = ttk.LabelFrame(self, text="  기본 모델 다운로드 & 적용  ")
        df.pack(fill="x", padx=14, pady=8)
        row = tk.Frame(df); row.pack(fill="x", padx=8, pady=8)
        tk.Label(row, text="모델", font=_FONT).pack(side="left")
        self.dl_var = tk.StringVar(value="yolov8s")
        ttk.Combobox(row, textvariable=self.dl_var, state="readonly",
                     width=14, values=DOWNLOADABLE).pack(side="left", padx=6)
        self.dl_btn = tk.Button(row, text="⬇ 다운로드 & 적용", bg=ACCENT,
                                fg="white", relief="flat", cursor="hand2",
                                command=self._download_apply)
        self.dl_btn.pack(side="left", padx=4)
        tk.Label(df, text="n/s/m/l = 크기(작음→큼, 클수록 정확·느림)",
                 font=("Malgun Gothic", 8), fg="#999").pack(anchor="w", padx=10,
                                                            pady=(0, 6))

        # 폴더 선택 섹션
        pf = ttk.LabelFrame(self, text="  내 model 폴더에서 선택 & 적용  ")
        pf.pack(fill="x", padx=14, pady=8)
        tk.Button(pf, text="📁 model 폴더의 커스텀 모델(.pt) 선택", cursor="hand2",
                  command=self._pick_apply).pack(padx=8, pady=8)

        self.status = tk.Label(self, text="", font=("Malgun Gothic", 10),
                               bg=BG)
        self.status.pack(pady=4)

        nav = tk.Frame(self, bg=BG); nav.pack(fill="x", padx=14, pady=(6, 12))
        tk.Button(nav, text="✓ 완료 (창 닫기)", font=_FONT, bg=GREEN,
                  fg="white", relief="flat", cursor="hand2", padx=14,
                  command=self.studio.close).pack(side="right")

    def on_show(self):
        self._set_active_label()

    def _ui(self, fn):
        try:
            self.after(0, fn)
        except Exception:
            pass

    def _set_active_label(self):
        if os.path.exists(ACTIVE_MODEL):
            active = get_active_name() or "active.pt"
            self.active_lbl.config(
                text=f"✅ 지금 인식에 적용된 모델:  {active}",
                fg="#1b5e20", bg="#e8f5e9")
            self.active_lbl.master.config(bg="#e8f5e9",
                                          highlightbackground="#a5d6a7")
        else:
            self.active_lbl.config(
                text="⚠ 적용된 모델 없음 — 기본 yolov5s 사용 중",
                fg="#7c5b00", bg="#fff8e1")
            self.active_lbl.master.config(bg="#fff8e1",
                                          highlightbackground="#ffe082")

    def _download_apply(self):
        name = self.dl_var.get().strip()
        if not name:
            return
        self.dl_btn.config(state="disabled")
        self.status.config(text=f"⏳ {name}.pt 다운로드 중...", fg=ORANGE)
        threading.Thread(target=self._dl_worker, args=(name,),
                         daemon=True).start()

    def _dl_worker(self, name):
        fn = name + ".pt"
        dst = os.path.join(MODELS_DIR, fn)
        try:
            os.makedirs(MODELS_DIR, exist_ok=True)
            if os.path.exists(dst):
                # 이미 model/ 에 있으면 다운로드하지 않고 바로 적용
                self._ui(lambda: self.status.config(
                    text=f"이미 있음 → 적용: {fn}", fg=ACCENT))
            else:
                from ultralytics import YOLO
                YOLO(fn)                   # 없을 때만 다운로드
                for d in (BASE, os.getcwd(), MODELS_DIR):
                    c = os.path.join(d, fn)
                    if os.path.exists(c):
                        if os.path.abspath(c) != os.path.abspath(dst):
                            shutil.move(c, dst)
                        break
            if os.path.exists(dst):
                shutil.copy(dst, ACTIVE_MODEL)
                set_active_name(fn)        # 원본 이름 기록
                self._ui(lambda: self.status.config(
                    text=f"✓ 적용됨: {fn} (인식에서 사용)", fg="#2e7d32"))
                self._ui(self._set_active_label)
            else:
                self._ui(lambda: self.status.config(
                    text="✗ 다운로드 파일을 찾지 못했습니다", fg="#c62828"))
        except Exception as e:
            self._ui(lambda ex=e: self.status.config(
                text=f"✗ 실패: {ex}", fg="#c62828"))
        finally:
            self._ui(lambda: self.dl_btn.config(state="normal"))

    def _pick_apply(self):
        os.makedirs(MODELS_DIR, exist_ok=True)
        path = filedialog.askopenfilename(
            title="인식에 적용할 모델 선택 (.pt)", initialdir=MODELS_DIR,
            filetypes=[("PyTorch 가중치", "*.pt")])
        if not path:
            return
        try:
            shutil.copy(path, ACTIVE_MODEL)
            set_active_name(os.path.basename(path))    # 원본 이름 기록
            self.status.config(text=f"✓ 적용됨: {os.path.basename(path)}",
                               fg="#2e7d32")
            self._set_active_label()
        except Exception as e:
            self.status.config(text=f"✗ 실패: {e}", fg="#c62828")


# ============================================================
# 학습 스튜디오 (하나의 창, 탭 + 스텝 인디케이터)
# ============================================================
class TrainingStudio(tk.Tk):
    STEPS = [("collect", "①", "데이터 수집"),
             ("train", "②", "학습"),
             ("swap", "③", "모델 적용")]

    def __init__(self):
        super().__init__()
        self.title("로봇 학습 스튜디오 — 수집 · 학습 · 적용")
        self.configure(bg=BG)
        from scrollable import fit_window
        fit_window(self, 980, 760)
        self.minsize(820, 600)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self._header()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.collect = CollectTab(self.nb, self)
        self.train = TrainTab(self.nb, self)
        self.swap = SwapTab(self.nb, self)
        self.nb.add(self.collect, text="  ①  📷 데이터 수집  ")
        self.nb.add(self.train, text="  ②  🧠 학습  ")
        self.nb.add(self.swap, text="  ③  🚀 모델 적용  ")
        self._tabs = {"collect": 0, "train": 1, "swap": 2}
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.after(120, lambda: self._on_tab_changed(None))  # 초기 진입 처리
        # 최상위로 올리기(메인 앱은 별도 프로세스에서 대기창으로 잠금)
        try:
            self.lift()
            self.attributes("-topmost", True)
            self.after(150, self.focus_force)
        except Exception:
            pass

    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", font=("Malgun Gothic", 11, "bold"),
                     padding=(16, 9), background="#dfe5f0")
        st.map("TNotebook.Tab", background=[("selected", ACCENT)],
               foreground=[("selected", "white")])
        st.configure("TFrame", background=BG)

    def _header(self):
        bar = tk.Frame(self, bg=HEADER_BG, height=58)
        bar.pack(fill="x"); bar.pack_propagate(False)
        tk.Label(bar, text="🧠  로봇 학습 스튜디오",
                 font=("Malgun Gothic", 15, "bold"), fg="white",
                 bg=HEADER_BG).pack(side="left", padx=18)
        # 스텝 인디케이터
        steps = tk.Frame(bar, bg=HEADER_BG); steps.pack(side="right", padx=14)
        self._step_lbls = {}
        for i, (key, num, name) in enumerate(self.STEPS):
            lbl = tk.Label(steps, text=f"{num} {name}",
                           font=("Malgun Gothic", 10, "bold"),
                           fg="#9fb3d8", bg=HEADER_BG, padx=10, pady=4)
            lbl.pack(side="left", padx=2)
            self._step_lbls[key] = lbl
            if i < len(self.STEPS) - 1:
                tk.Label(steps, text="→", fg="#5b6b8c",
                         bg=HEADER_BG).pack(side="left")

    def _update_steps(self, active_key):
        for key, lbl in self._step_lbls.items():
            if key == active_key:
                lbl.config(fg="white", bg=ACCENT)
            else:
                lbl.config(fg="#9fb3d8", bg=HEADER_BG)

    def goto(self, key):
        idx = self._tabs.get(key)
        if idx is not None:
            self.nb.select(idx)

    def _on_tab_changed(self, _event):
        try:
            cur = self.nb.index(self.nb.select())
        except Exception:
            return
        key = self.STEPS[cur][0]
        self._update_steps(key)
        # 카메라는 수집 탭에서만 동작
        if key == "collect":
            self.collect.on_show()
        else:
            self.collect.on_hide()
        if key == "train":
            self.train.on_show()
        elif key == "swap":
            self.swap.on_show()

    def close(self):
        if self.train.is_busy():
            if not messagebox.askyesno("확인", "학습 중입니다. 중단하고 닫을까요?"):
                return
            self.train.stop()
        try:
            self.collect.on_hide()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


# 하위 호환: 기존 이름으로도 스튜디오를 띄울 수 있게
class TrainingMenu:
    def run(self):
        TrainingStudio().mainloop()


if __name__ == "__main__":
    TrainingStudio().mainloop()
