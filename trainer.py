# coding: utf-8
"""
trainer.py
==========
로봇 학습 메뉴: 데이터 수집 / 학습 시작 / 모델 교체.

전제(요청사항):
  - 데이터 수집은 카메라로 실시간 캡처
  - 1개 이미지에는 1개의 객체만 있다고 가정 → 라벨은 "전체 프레임 박스"로 자동 생성
    (YOLO 형식: <class_id> 0.5 0.5 1.0 1.0)

폴더 구조:
  dataset/
    images/train/<class>_0001.jpg
    labels/train/<class>_0001.txt
    classes.txt          # 클래스 이름 목록(줄 단위, 순서 = class_id)
    data.yaml            # 학습 시 자동 생성
  models/active.pt       # '모델 교체' 시 학습 결과(best.pt) 복사본 → 인식에서 사용
  runs/custom/weights/best.pt   # 학습 산출물
"""

import os
import sys
import threading
import subprocess
import configparser
import shutil

import tkinter as tk
from tkinter import ttk, messagebox

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


BASE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(BASE, "dataset")
IMG_DIR = os.path.join(DATASET, "images", "train")
LBL_DIR = os.path.join(DATASET, "labels", "train")
CLASSES_TXT = os.path.join(DATASET, "classes.txt")
DATA_YAML = os.path.join(DATASET, "data.yaml")
MODELS_DIR = os.path.join(BASE, "models")
ACTIVE_MODEL = os.path.join(MODELS_DIR, "active.pt")
YOLO_DIR = os.path.join(BASE, "yolov5")
BASE_WEIGHTS = os.path.join(BASE, "yolov5s.pt")
BEST_WEIGHTS = os.path.join(BASE, "runs", "custom", "weights", "best.pt")
PY = sys.executable

_FONT = ("Malgun Gothic", 11)
_FONT_BIG = ("Malgun Gothic", 13, "bold")


# ============================================================
# 클래스 목록 / 데이터셋 유틸
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


def count_images(cls: str) -> int:
    if not os.path.isdir(IMG_DIR):
        return 0
    pref = f"{cls}_"
    return len([n for n in os.listdir(IMG_DIR)
                if n.startswith(pref) and n.lower().endswith(".jpg")])


def camera_index() -> int:
    """config.ini(포트 설정에서 저장)에 기록된 카메라 인덱스. 없으면 0."""
    cfg = configparser.ConfigParser()
    try:
        cfg.read(os.path.join(BASE, "config.ini"), encoding="utf-8")
        v = cfg["SETTINGS"].get("last_camera_index")
        return int(v) if v not in (None, "") else 0
    except Exception:
        return 0


def build_data_yaml() -> str:
    classes = load_classes()
    os.makedirs(DATASET, exist_ok=True)
    names = "[" + ", ".join(f'"{c}"' for c in classes) + "]"
    with open(DATA_YAML, "w", encoding="utf-8") as f:
        f.write(f"path: {DATASET.replace(os.sep, '/')}\n")
        f.write("train: images/train\n")
        f.write("val: images/train\n")     # 데모: train을 val로 겸용
        f.write(f"nc: {len(classes)}\n")
        f.write(f"names: {names}\n")
    return DATA_YAML


# ============================================================
# 1) 데이터 수집 (실시간 카메라 캡처 + 자동 라벨)
# ============================================================
class DataCollector:
    PREVIEW_W = 480
    PREVIEW_H = 360

    def __init__(self):
        self.classes = load_classes()
        self.cap = None
        self.last_frame = None
        self.after_id = None
        self.root = None

    def run(self) -> None:
        if not (_HAS_CV2 and _HAS_PIL):
            messagebox.showerror("오류", "opencv(cv2) / Pillow(PIL) 가 필요합니다.")
            return

        self.root = tk.Tk()
        self.root.title("데이터 수집 — 실시간 캡처")
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        tk.Label(self.root, text="데이터 수집", font=_FONT_BIG, pady=8).pack()
        tk.Label(
            self.root,
            text="① 클래스 이름 입력 → ② 카메라에 객체 1개를 크게 비춤 → ③ 캡처\n"
                 "(이미지 1장 = 객체 1개로 가정, 라벨은 전체 프레임으로 자동 생성)",
            font=("Malgun Gothic", 9), fg="#555", justify="left",
        ).pack(pady=(0, 6))

        self.canvas = tk.Canvas(
            self.root, width=self.PREVIEW_W, height=self.PREVIEW_H,
            bg="#1e1e1e", highlightthickness=1, highlightbackground="#555",
        )
        self.canvas.pack(padx=12)
        self.img_id = self.canvas.create_image(
            self.PREVIEW_W // 2, self.PREVIEW_H // 2, anchor="center")

        row = tk.Frame(self.root); row.pack(fill="x", padx=12, pady=10)
        tk.Label(row, text="클래스", font=_FONT).pack(side="left")
        self.class_var = tk.StringVar()
        self.class_combo = ttk.Combobox(
            row, textvariable=self.class_var, values=self.classes, width=22)
        self.class_combo.pack(side="left", padx=(6, 0))
        if self.classes:
            self.class_combo.current(0)

        self.capture_btn = tk.Button(
            row, text="📸  캡처", font=_FONT_BIG, bg="#28a745", fg="white",
            relief="flat", padx=14, command=self._capture)
        self.capture_btn.pack(side="left", padx=(12, 0))

        self.count_label = tk.Label(self.root, text="", font=_FONT, fg="#1565c0")
        self.count_label.pack(pady=(0, 4))
        self._update_count()

        tk.Button(self.root, text="닫기", font=_FONT, width=10,
                  command=self._close).pack(pady=(4, 12))

        self._open_cam()
        self._loop()
        self.root.mainloop()

    def _open_cam(self) -> None:
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else 0
        self.cap = cv2.VideoCapture(camera_index(), backend)

    def _loop(self) -> None:
        if self.cap is not None:
            ok, frame = self.cap.read()
            if ok and frame is not None:
                self.last_frame = frame
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb = cv2.resize(rgb, (self.PREVIEW_W, self.PREVIEW_H))
                self.imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))
                self.canvas.itemconfig(self.img_id, image=self.imgtk)
        if self.root is not None:
            self.after_id = self.root.after(33, self._loop)

    def _capture(self) -> None:
        cls = self.class_var.get().strip()
        if not cls:
            messagebox.showwarning("알림", "클래스 이름을 입력하세요.")
            return
        if self.last_frame is None:
            messagebox.showwarning("알림", "카메라 프레임이 아직 없습니다.")
            return

        if cls not in self.classes:
            self.classes.append(cls)
            save_classes(self.classes)
            self.class_combo["values"] = self.classes

        cls_id = self.classes.index(cls)
        os.makedirs(IMG_DIR, exist_ok=True)
        os.makedirs(LBL_DIR, exist_ok=True)
        n = count_images(cls) + 1
        stem = f"{cls}_{n:04d}"
        cv2.imwrite(os.path.join(IMG_DIR, stem + ".jpg"), self.last_frame)
        with open(os.path.join(LBL_DIR, stem + ".txt"), "w") as f:
            # 1이미지 1객체 → 전체 프레임 박스
            f.write(f"{cls_id} 0.5 0.5 1.0 1.0\n")
        self._update_count()

    def _update_count(self) -> None:
        parts = [f"{c}: {count_images(c)}장" for c in self.classes]
        total = sum(count_images(c) for c in self.classes)
        txt = f"수집 현황 (총 {total}장)   " + "   ".join(parts) if parts \
            else "아직 수집된 데이터가 없습니다."
        self.count_label.config(text=txt)

    def _close(self) -> None:
        if self.after_id is not None and self.root is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        if self.root is not None:
            self.root.destroy()
            self.root = None


# ============================================================
# 2) 학습 시작 (yolov5/train.py 서브프로세스)
# ============================================================
class TrainWindow:
    def __init__(self):
        self.root = None
        self.proc = None

    def run(self) -> None:
        self.root = tk.Tk()
        self.root.title("학습 시작")
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        tk.Label(self.root, text="모델 학습", font=_FONT_BIG, pady=8).pack()

        classes = load_classes()
        total = sum(count_images(c) for c in classes)
        info = (f"클래스 {len(classes)}개 / 이미지 총 {total}장\n"
                f"※ CPU 학습이라 느립니다. 데모는 에폭을 작게 두세요.")
        tk.Label(self.root, text=info, font=("Malgun Gothic", 9),
                 fg="#555", justify="left").pack(pady=(0, 6))

        row = tk.Frame(self.root); row.pack(pady=4)
        tk.Label(row, text="에폭", font=_FONT).pack(side="left")
        self.epoch_var = tk.StringVar(value="30")
        tk.Spinbox(row, from_=1, to=300, width=6,
                   textvariable=self.epoch_var).pack(side="left", padx=(6, 12))
        tk.Label(row, text="이미지 크기", font=_FONT).pack(side="left")
        self.img_var = tk.StringVar(value="416")
        tk.Spinbox(row, from_=160, to=640, increment=32, width=6,
                   textvariable=self.img_var).pack(side="left", padx=(6, 0))

        self.start_btn = tk.Button(
            self.root, text="▶  학습 시작", font=_FONT_BIG, bg="#28a745",
            fg="white", relief="flat", padx=14, command=self._start)
        self.start_btn.pack(pady=8)

        self.log = tk.Text(self.root, width=86, height=20,
                           bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9))
        self.log.pack(padx=12, pady=(0, 6))

        tk.Button(self.root, text="닫기", font=_FONT, width=10,
                  command=self._close).pack(pady=(0, 12))

        self.root.mainloop()

    def _append(self, text: str) -> None:
        def apply():
            try:
                self.log.insert("end", text)
                self.log.see("end")
            except Exception:
                pass
        if self.root is not None:
            try:
                self.root.after(0, apply)
            except Exception:
                pass

    def _start(self) -> None:
        classes = load_classes()
        total = sum(count_images(c) for c in classes)
        if len(classes) < 1 or total < 1:
            messagebox.showwarning("알림", "먼저 데이터를 수집하세요.")
            return
        if len(classes) < 2:
            if not messagebox.askyesno(
                    "확인", "클래스가 1개뿐입니다. 그래도 학습할까요?"):
                return
        if not os.path.exists(BASE_WEIGHTS):
            messagebox.showerror("오류", f"가중치가 없습니다:\n{BASE_WEIGHTS}")
            return

        self.start_btn.config(state="disabled")
        try:
            epochs = int(self.epoch_var.get())
            imgsz = int(self.img_var.get())
        except Exception:
            epochs, imgsz = 30, 416

        build_data_yaml()
        threading.Thread(target=self._train_worker,
                         args=(epochs, imgsz), daemon=True).start()

    def _train_worker(self, epochs: int, imgsz: int) -> None:
        cmd = [
            PY, os.path.join(YOLO_DIR, "train.py"),
            "--img", str(imgsz), "--batch", "4", "--epochs", str(epochs),
            "--data", DATA_YAML, "--weights", BASE_WEIGHTS,
            "--project", os.path.join(BASE, "runs"), "--name", "custom",
            "--exist-ok", "--device", "cpu", "--workers", "0",
        ]
        self._append("학습 시작:\n  " + " ".join(cmd) + "\n\n")
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=YOLO_DIR, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1,
            )
            for line in self.proc.stdout:
                self._append(line)
            self.proc.wait()
            if self.proc.returncode == 0:
                self._append(f"\n✓ 학습 완료. 결과: {BEST_WEIGHTS}\n"
                             f"  → '모델 교체'로 인식에 적용하세요.\n")
            else:
                self._append(f"\n✗ 학습 실패 (코드 {self.proc.returncode})\n")
        except Exception as e:
            self._append(f"\n✗ 오류: {e}\n")
        finally:
            self.proc = None
            if self.root is not None:
                try:
                    self.root.after(
                        0, lambda: self.start_btn.config(state="normal"))
                except Exception:
                    pass

    def _close(self) -> None:
        if self.proc is not None:
            if not messagebox.askyesno("확인", "학습이 진행 중입니다. 중단할까요?"):
                return
            try:
                self.proc.terminate()
            except Exception:
                pass
        if self.root is not None:
            self.root.destroy()
            self.root = None


# ============================================================
# 3) 모델 교체 (best.pt → models/active.pt)
# ============================================================
def swap_model() -> None:
    if not os.path.exists(BEST_WEIGHTS):
        messagebox.showwarning(
            "알림", f"학습된 모델이 없습니다.\n먼저 학습을 완료하세요.\n({BEST_WEIGHTS})")
        return
    if not messagebox.askyesno(
            "확인", "학습된 모델(best.pt)을 인식용 모델로 교체할까요?"):
        return
    try:
        os.makedirs(MODELS_DIR, exist_ok=True)
        shutil.copy(BEST_WEIGHTS, ACTIVE_MODEL)
        messagebox.showinfo(
            "완료", f"교체 완료.\n인식 시작 시 이 모델을 사용합니다.\n{ACTIVE_MODEL}")
    except Exception as e:
        messagebox.showerror("오류", f"교체 실패: {e}")


# ============================================================
# 로봇 학습 메뉴
# ============================================================
class TrainingMenu:
    def run(self) -> None:
        while True:
            choice = self._menu()
            if choice in (None, "back"):
                break
            if choice == "collect":
                DataCollector().run()
            elif choice == "train":
                TrainWindow().run()
            elif choice == "swap":
                self._swap_with_root()

    def _menu(self):
        result = {"v": None}
        root = tk.Tk()
        root.title("로봇 학습")
        root.geometry("360x340")

        def pick(v):
            result["v"] = v
            root.destroy()

        tk.Label(root, text="로봇 학습", font=("Malgun Gothic", 15, "bold"),
                 pady=16).pack()

        def big(text, cmd, color):
            return tk.Button(root, text=text, font=_FONT_BIG, bg=color,
                             fg="white", relief="flat", height=2,
                             command=cmd)

        big("📷  데이터 수집", lambda: pick("collect"), "#1565c0").pack(
            fill="x", padx=30, pady=6)
        big("🧠  학습 시작", lambda: pick("train"), "#28a745").pack(
            fill="x", padx=30, pady=6)
        big("🔄  모델 교체", lambda: pick("swap"), "#ef6c00").pack(
            fill="x", padx=30, pady=6)
        tk.Button(root, text="← 뒤로", font=_FONT, command=lambda: pick("back")
                  ).pack(pady=(14, 0))

        active = "있음" if os.path.exists(ACTIVE_MODEL) else "없음(기본 모델 사용)"
        tk.Label(root, text=f"현재 교체된 모델: {active}",
                 font=("Malgun Gothic", 9), fg="#777").pack(pady=(10, 0))

        root.mainloop()
        return result["v"]

    def _swap_with_root(self) -> None:
        # messagebox는 부모 Tk가 필요하므로 임시 루트를 띄운다
        root = tk.Tk()
        root.withdraw()
        swap_model()
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    TrainingMenu().run()
