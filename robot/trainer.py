# coding: utf-8
"""
trainer.py
==========
로봇 학습: 데이터 수집 / 학습 / 모델 교체.

데이터 수집:
  - 실시간 카메라, 클래스 추가/삭제, 단발/연속 캡처
  - 저장 크기 선택(144/200/320/640, 정사각 리사이즈)
  - 수집된 데이터 썸네일 미리보기
  - 1이미지=1객체 가정 → 라벨은 전체 프레임 박스 자동 생성

학습:
  - yolov5/train.py 서브프로세스, 가중치=model/yolov5s.pt
  - 완료 후 best.pt 를 이름 지정해 ./model 폴더에 저장(+선택 시 active 적용)

모델 교체:
  - ./model 의 .pt 중 하나를 골라 active.pt 로 설정
"""

import os
import sys
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
_FONT = ("Malgun Gothic", 11)
_FONT_BIG = ("Malgun Gothic", 13, "bold")
SIZES = [144, 200, 320, 640]


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


# ============================================================
# 1) 데이터 수집
# ============================================================
class DataCollector:
    PREVIEW_W = 420
    PREVIEW_H = 320
    THUMB = 72

    def __init__(self):
        self.classes = load_classes()
        self.cap = None
        self.last_frame = None
        self.after_id = None
        self.cont_after = None
        self.continuous = False
        self.root = None
        self._thumbs = []

    def run(self):
        if not (_HAS_CV2 and _HAS_PIL):
            messagebox.showerror("오류", "opencv(cv2) / Pillow(PIL) 가 필요합니다.")
            return
        self.root = tk.Tk()
        self.root.title("데이터 수집")
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        tk.Label(self.root, text="데이터 수집", font=_FONT_BIG, pady=6).pack()

        # 클래스 줄
        crow = tk.Frame(self.root); crow.pack(fill="x", padx=12, pady=4)
        tk.Label(crow, text="클래스", font=_FONT).pack(side="left")
        self.class_var = tk.StringVar()
        self.class_combo = ttk.Combobox(crow, textvariable=self.class_var,
                                        values=self.classes, width=20)
        self.class_combo.pack(side="left", padx=(6, 4))
        self.class_combo.bind("<<ComboboxSelected>>",
                              lambda e: self._refresh_thumbs())
        tk.Button(crow, text="+ 추가", command=self._add_class).pack(side="left")
        tk.Button(crow, text="🗑 삭제", command=self._delete_class).pack(
            side="left", padx=(4, 0))
        if self.classes:
            self.class_combo.current(0)

        # 저장 크기 줄
        srow = tk.Frame(self.root); srow.pack(fill="x", padx=12, pady=2)
        tk.Label(srow, text="저장 크기", font=_FONT).pack(side="left")
        self.size_var = tk.IntVar(value=320)
        for s in SIZES:
            tk.Radiobutton(srow, text=f"{s}", variable=self.size_var,
                           value=s).pack(side="left")
        tk.Label(srow, text="px (정사각)", font=("Malgun Gothic", 9),
                 fg="#888").pack(side="left")

        body = tk.Frame(self.root); body.pack(fill="both", expand=True,
                                              padx=12, pady=4)
        # 좌: 미리보기 + 캡처
        left = tk.Frame(body); left.pack(side="left")
        self.canvas = tk.Canvas(left, width=self.PREVIEW_W,
                                height=self.PREVIEW_H, bg="#1e1e1e",
                                highlightthickness=1, highlightbackground="#555")
        self.canvas.pack()
        self.img_id = self.canvas.create_image(self.PREVIEW_W // 2,
                                               self.PREVIEW_H // 2,
                                               anchor="center")
        brow = tk.Frame(left); brow.pack(pady=6)
        tk.Button(brow, text="📸 캡처", font=_FONT_BIG, bg="#28a745",
                  fg="white", relief="flat", padx=12,
                  command=self._capture_once).pack(side="left", padx=4)
        self.cont_btn = tk.Button(brow, text="● 연속 캡처", font=_FONT_BIG,
                                  bg="#1565c0", fg="white", relief="flat",
                                  padx=12, command=self._toggle_continuous)
        self.cont_btn.pack(side="left", padx=4)
        self.count_label = tk.Label(left, text="", font=_FONT, fg="#1565c0")
        self.count_label.pack()

        # 우: 썸네일
        right = tk.Frame(body); right.pack(side="left", fill="both",
                                           expand=True, padx=(12, 0))
        tk.Label(right, text="수집된 데이터 (선택 클래스)",
                 font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
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

        tk.Button(self.root, text="닫기", font=_FONT, width=10,
                  command=self._close).pack(pady=(2, 10))

        self._open_cam()
        self._loop()
        self._update_count()
        self._refresh_thumbs()
        self.root.mainloop()

    # ---------- 카메라 ----------
    def _open_cam(self):
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
        if self.root is not None:
            self.after_id = self.root.after(33, self._loop)

    # ---------- 클래스 ----------
    def _cur_class(self):
        return self.class_var.get().strip()

    def _add_class(self):
        name = simpledialog.askstring("클래스 추가", "새 클래스 이름:",
                                      parent=self.root)
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
            self.cont_btn.config(text="● 연속 캡처", bg="#1565c0")
            if self.cont_after is not None:
                try:
                    self.root.after_cancel(self.cont_after)
                except Exception:
                    pass
                self.cont_after = None

    def _continuous_step(self):
        if not self.continuous:
            return
        self._capture_once()
        self.cont_after = self.root.after(400, self._continuous_step)

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

    def _close(self):
        self.continuous = False
        for aid in (self.after_id, self.cont_after):
            if aid is not None and self.root is not None:
                try:
                    self.root.after_cancel(aid)
                except Exception:
                    pass
        self.after_id = self.cont_after = None
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
# 2) 학습
# ============================================================
class TrainWindow:
    def __init__(self):
        self.root = None
        self.proc = None

    def run(self):
        self.root = tk.Tk()
        self.root.title("학습 시작")
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        tk.Label(self.root, text="모델 학습", font=_FONT_BIG, pady=8).pack()
        classes = load_classes()
        total = sum(count_images(c) for c in classes)
        tk.Label(self.root, text=f"클래스 {len(classes)}개 / 이미지 {total}장\n"
                 "※ CPU 학습이라 느립니다. 에폭을 작게 두세요.",
                 font=("Malgun Gothic", 9), fg="#555").pack()

        row = tk.Frame(self.root); row.pack(pady=4)
        tk.Label(row, text="에폭", font=_FONT).pack(side="left")
        self.epoch_var = tk.StringVar(value="30")
        tk.Spinbox(row, from_=1, to=300, width=6,
                   textvariable=self.epoch_var).pack(side="left", padx=(6, 12))
        tk.Label(row, text="이미지", font=_FONT).pack(side="left")
        self.img_var = tk.StringVar(value="320")
        ttk.Combobox(row, textvariable=self.img_var, width=6, state="readonly",
                     values=[str(s) for s in SIZES]).pack(side="left", padx=6)

        self.start_btn = tk.Button(self.root, text="▶ 학습 시작",
                                   font=_FONT_BIG, bg="#28a745", fg="white",
                                   relief="flat", padx=14, command=self._start)
        self.start_btn.pack(pady=8)
        self.log = tk.Text(self.root, width=86, height=18, bg="#1e1e1e",
                           fg="#d4d4d4", font=("Consolas", 9))
        self.log.pack(padx=12, pady=(0, 6))
        tk.Button(self.root, text="닫기", font=_FONT, width=10,
                  command=self._close).pack(pady=(0, 10))
        self.root.mainloop()

    def _append(self, text):
        def apply():
            try:
                self.log.insert("end", text); self.log.see("end")
            except Exception:
                pass
        if self.root is not None:
            try:
                self.root.after(0, apply)
            except Exception:
                pass

    def _start(self):
        classes = load_classes()
        total = sum(count_images(c) for c in classes)
        if not classes or total < 1:
            messagebox.showwarning("알림", "먼저 데이터를 수집하세요.")
            return
        if not os.path.exists(BASE_WEIGHTS):
            messagebox.showerror("오류", f"기본 가중치가 없습니다:\n{BASE_WEIGHTS}")
            return
        self.start_btn.config(state="disabled")
        try:
            epochs = int(self.epoch_var.get()); imgsz = int(self.img_var.get())
        except Exception:
            epochs, imgsz = 30, 320
        build_data_yaml()
        threading.Thread(target=self._worker, args=(epochs, imgsz),
                         daemon=True).start()

    def _worker(self, epochs, imgsz):
        # ultralytics 로 학습 (yolov5 클론 불필요). 로그 스트리밍 위해 서브프로세스로.
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
                if self.root is not None:
                    self.root.after(0, self._prompt_save)
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

    def _prompt_save(self):
        if os.path.exists(BEST_WEIGHTS):
            name = simpledialog.askstring(
                "모델 저장",
                "저장할 모델 이름 (./model 폴더, 취소=저장 안 함):",
                parent=self.root)
            if name:
                name = name.strip()
                if not name.endswith(".pt"):
                    name += ".pt"
                os.makedirs(MODELS_DIR, exist_ok=True)
                dst = os.path.join(MODELS_DIR, name)
                try:
                    shutil.copy(BEST_WEIGHTS, dst)
                    if messagebox.askyesno(
                            "모델 교체",
                            "이 모델을 인식에 바로 적용(active)할까요?"):
                        shutil.copy(dst, ACTIVE_MODEL)
                        set_active_name(name)        # 원본 이름 기록
                    messagebox.showinfo("완료",
                                        f"저장됨:\n{dst}\n학습 창을 닫습니다.")
                except Exception as e:
                    messagebox.showerror("오류", f"저장 실패: {e}")
        # 학습이 끝났으니 창을 닫고 메뉴로 복귀
        try:
            if self.root is not None:
                self.root.destroy()
                self.root = None
        except Exception:
            pass

    def _close(self):
        if self.proc is not None:
            if not messagebox.askyesno("확인", "학습 중입니다. 중단할까요?"):
                return
            try:
                self.proc.terminate()
            except Exception:
                pass
        if self.root is not None:
            self.root.destroy(); self.root = None


# ============================================================
# 3) 모델 교체 / 다운로드
# ============================================================
# 다운로드 가능한 기본 모델 (ultralytics)
DOWNLOADABLE = [
    "yolov5su", "yolov8n", "yolov8s", "yolov8m", "yolov8l",
    "yolo11n", "yolo11s", "yolo11m", "yolo11l",
]


class ModelManager:
    """기본 모델 다운로드 & 적용 + 내 model 폴더에서 선택 & 적용."""

    def run(self):
        self.root = tk.Tk()
        self.root.title("모델 교체 / 다운로드")
        self.root.geometry("480x360")
        tk.Label(self.root, text="🔄 모델 교체 / 다운로드", font=_FONT_BIG,
                 pady=8).pack()
        active = (get_active_name() or "active.pt") \
            if os.path.exists(ACTIVE_MODEL) else "없음(기본 yolov5s)"
        self.active_lbl = tk.Label(
            self.root, text=f"현재 적용(active): {active}",
            font=("Malgun Gothic", 9), fg="#777")
        self.active_lbl.pack()

        # 다운로드 섹션
        df = ttk.LabelFrame(self.root, text="  기본 모델 다운로드 & 적용  ")
        df.pack(fill="x", padx=12, pady=8)
        row = tk.Frame(df); row.pack(fill="x", padx=8, pady=8)
        tk.Label(row, text="모델", font=_FONT).pack(side="left")
        self.dl_var = tk.StringVar(value="yolov8s")
        ttk.Combobox(row, textvariable=self.dl_var, state="readonly",
                     width=14, values=DOWNLOADABLE).pack(side="left", padx=6)
        self.dl_btn = tk.Button(row, text="⬇ 다운로드 & 적용", bg="#1565c0",
                                fg="white", relief="flat", cursor="hand2",
                                command=self._download_apply)
        self.dl_btn.pack(side="left", padx=4)
        tk.Label(df, text="n/s/m/l = 크기(작음→큼, 클수록 정확·느림)",
                 font=("Malgun Gothic", 8), fg="#999").pack(anchor="w",
                                                            padx=10)

        # 폴더 선택 섹션
        pf = ttk.LabelFrame(self.root, text="  내 model 폴더에서 선택 & 적용  ")
        pf.pack(fill="x", padx=12, pady=8)
        tk.Button(pf, text="📁 model 폴더의 .pt 선택", cursor="hand2",
                  command=self._pick_apply).pack(padx=8, pady=8)

        self.status = tk.Label(self.root, text="", font=("Malgun Gothic", 10))
        self.status.pack(pady=4)
        tk.Button(self.root, text="닫기", font=_FONT, width=10,
                  command=self.root.destroy).pack(pady=(2, 10))
        self.root.mainloop()

    def _ui(self, fn):
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def _set_active_label(self):
        active = (get_active_name() or "active.pt") \
            if os.path.exists(ACTIVE_MODEL) else "없음"
        self.active_lbl.config(text=f"현재 적용(active): {active}")

    def _download_apply(self):
        name = self.dl_var.get().strip()
        if not name:
            return
        self.dl_btn.config(state="disabled")
        self.status.config(text=f"⏳ {name}.pt 다운로드 중...", fg="#ef6c00")
        threading.Thread(target=self._dl_worker, args=(name,),
                         daemon=True).start()

    def _dl_worker(self, name):
        fn = name + ".pt"
        try:
            from ultralytics import YOLO
            YOLO(fn)                       # 없으면 다운로드
            os.makedirs(MODELS_DIR, exist_ok=True)
            dst = os.path.join(MODELS_DIR, fn)
            if not os.path.exists(dst):
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
# 메뉴
# ============================================================
class TrainingMenu:
    def run(self):
        while True:
            choice = self._menu()
            if choice in (None, "back"):
                break
            if choice == "collect":
                DataCollector().run()
            elif choice == "train":
                TrainWindow().run()
            elif choice == "swap":
                ModelManager().run()

    def _menu(self):
        result = {"v": None}
        root = tk.Tk()
        root.title("로봇 학습")
        root.geometry("360x360")

        def pick(v):
            result["v"] = v; root.destroy()

        tk.Label(root, text="로봇 학습", font=("Malgun Gothic", 15, "bold"),
                 pady=16).pack()

        def big(text, cmd, color):
            return tk.Button(root, text=text, font=_FONT_BIG, bg=color,
                             fg="white", relief="flat", height=2, command=cmd)

        big("📷  데이터 수집", lambda: pick("collect"), "#1565c0").pack(
            fill="x", padx=30, pady=6)
        big("🧠  학습 시작", lambda: pick("train"), "#28a745").pack(
            fill="x", padx=30, pady=6)
        big("🔄  모델 교체", lambda: pick("swap"), "#ef6c00").pack(
            fill="x", padx=30, pady=6)
        tk.Button(root, text="← 뒤로", font=_FONT,
                  command=lambda: pick("back")).pack(pady=(14, 0))
        active = "있음" if os.path.exists(ACTIVE_MODEL) else "없음(기본)"
        tk.Label(root, text=f"현재 적용 모델(active): {active}",
                 font=("Malgun Gothic", 9), fg="#777").pack(pady=(10, 0))
        root.mainloop()
        return result["v"]


if __name__ == "__main__":
    TrainingMenu().run()
