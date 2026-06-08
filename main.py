# coding: utf-8
"""
main.py
=======
YOLOv5 실시간 객체 탐지 + 휴머노이드 로봇 제어 통합 앱.

구성:
  - 메인 메뉴      : 포트 설정 / 로봇 학습 / 인식 시작 / 종료
  - 포트/장치 설정 : port_selector.PortSelector
  - 로봇 학습      : trainer.TrainingMenu (데이터 수집 / 학습 / 모델 교체)
  - 인식 시작      : run_recognition() — 카메라 + YOLOv5 + 로봇 모션

탐지 정책:
  - 매 프레임 중 가장 confidence 높은 객체 1개만 기준으로 한다.
  - 직전에 동작을 일으킨 객체와 같으면 다시 동작하지 않는다.
  - 한 동작 후 복귀까지 시퀀스(딜레이)가 끝나야 다음 동작을 받는다.
"""

import os
import time

import cv2
import numpy as np
import torch
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageFont

from port_selector import PortSelector
from robot_controller import HumanoidRobot, MotionSequencer
import trainer


# ============================================================
# 사용자 설정
# ============================================================
BASE = os.path.dirname(os.path.abspath(__file__))
ACTIVE_MODEL = os.path.join(BASE, "models", "active.pt")

LABEL_TO_MOTION = {
    "person":     19,
    "bottle":     18,
    "cell phone": 20,
}

CONF_THRESHOLD = 0.60
RETURN_MOTION = 1
ACTION_HOLD_SEC = 7
RETURN_HOLD_SEC = 3
BAUDRATE = 115200

INFER_EVERY = 2        # N프레임마다 1회만 추론(레이턴시 완화)
INFER_SIZE = 320       # 추론 입력 해상도(작을수록 빠름)
PING_EVERY = 30        # N프레임마다 로봇 연결 점검


# ============================================================
# 한글 렌더링 (cv2.putText는 한글을 못 그려서 PIL 사용)
# ============================================================
_FONT_PATH = "C:/Windows/Fonts/malgun.ttf"
_font_cache = {}


def _font(size: int):
    f = _font_cache.get(size)
    if f is None:
        try:
            f = ImageFont.truetype(_FONT_PATH, size)
        except Exception:
            f = ImageFont.load_default()
        _font_cache[size] = f
    return f


def draw_texts(img_bgr, items):
    """BGR 이미지에 (텍스트, (x,y), 크기, (b,g,r)) 목록을 한 번에 그린다."""
    if not items:
        return img_bgr
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    for text, (x, y), size, color in items:
        draw.text((x, y), text, font=_font(size),
                  fill=(color[2], color[1], color[0]))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


_SPINNER = ["|", "/", "-", "\\"]


def _status_frame(text: str, n: int, w: int = 640, h: int = 360):
    img = np.full((h, w, 3), 30, dtype=np.uint8)
    spin = _SPINNER[n % len(_SPINNER)]
    return draw_texts(img, [
        (f"{spin}  {text}", (40, h // 2 - 18), 26, (0, 255, 255)),
        ("ESC / q : 종료", (40, h - 40), 18, (160, 160, 160)),
    ])


# ============================================================
# 초기화
# ============================================================
class AppContext:
    def __init__(self):
        self.robot = None
        self.model = None
        self.camera = None
        self.camera_index = None
        self.camera_name = None
        self.model_label = "기본(COCO)"


def load_model():
    """교체된 모델(models/active.pt)이 있으면 그것을, 없으면 기본 yolov5s."""
    if os.path.exists(ACTIVE_MODEL):
        m = torch.hub.load("./yolov5", "custom",
                           path=ACTIVE_MODEL, source="local")
        return m, "학습 모델(active.pt)"
    m = torch.hub.load("./yolov5", "yolov5s", pretrained=True, source="local")
    return m, "기본(COCO)"


def setup_all(ctx: AppContext) -> None:
    """포트 선택 UI를 띄우고, 그 흐름 안에서 모델/카메라까지 초기화."""
    selector = PortSelector(
        title="YOLOv5 + 휴머노이드 AI 초기화",
        baudrate=BAUDRATE,
    )

    def init_task(update):
        port = selector.selected_port

        # 1) 포트 연결
        update("1. 포트 연결 중...", f"{port} @ {BAUDRATE}bps", 15)
        ctx.robot = HumanoidRobot(port, BAUDRATE)
        ctx.robot.connect()
        time.sleep(0.3)

        # 2) 모델 로드
        update("2. YOLOv5 모델 로드 중...", "가중치 로딩", 45)
        ctx.model, ctx.model_label = load_model()
        ctx.model.eval()

        # 2.5) 예열 — 첫 추론 지연 흡수
        update("2. YOLOv5 예열 중...", "첫 추론 워밍업 (잠시만요)", 60)
        try:
            ctx.model(np.zeros((INFER_SIZE, INFER_SIZE, 3), dtype=np.uint8),
                      size=INFER_SIZE)
        except Exception:
            pass
        time.sleep(0.1)

        # 3) 카메라 (미리보기가 막 놓았을 수 있으니 재시도)
        cam_idx = selector.selected_camera_index
        if cam_idx is None:
            cam_idx = 0
        cam_name = selector.selected_camera_name or f"index {cam_idx}"

        update("3. 카메라 활성화 중...", f"{cam_name} 응답 대기", 75)
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else 0
        cam = None
        for attempt in range(5):
            cam = cv2.VideoCapture(cam_idx, backend)
            if cam.isOpened():
                break
            cam.release()
            update("3. 카메라 활성화 중...",
                   f"{cam_name} 재시도 {attempt + 1}/5", 75)
            time.sleep(0.4)
        if cam is None or not cam.isOpened():
            raise RuntimeError(f"카메라를 열 수 없습니다 (idx={cam_idx}).")
        ctx.camera = cam
        ctx.camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ctx.camera_index = cam_idx
        ctx.camera_name = cam_name
        for _ in range(5):              # DSHOW 첫 프레임 버림
            ctx.camera.read()
            time.sleep(0.03)

        update("4. 준비 완료", f"모델: {ctx.model_label}", 95)
        time.sleep(0.2)

    port = selector.run_with_progress(init_task=init_task)
    if port is None:
        raise RuntimeError("CANCELLED")


def _alert(title: str, msg: str) -> None:
    """OpenCV 창과 별개로 tk 알림창을 띄운다."""
    try:
        r = tk.Tk(); r.withdraw()
        messagebox.showwarning(title, msg)
        r.destroy()
    except Exception:
        print(f"[{title}] {msg}")


# ============================================================
# 인식 루프
# ============================================================
def run_recognition() -> str:
    """반환값:
        "menu"     → 정상 종료, 메인 메뉴로
        "reselect" → 로봇 끊김, 포트 선택부터 다시
        "cancel"   → 포트 선택 취소
    """
    ctx = AppContext()
    try:
        setup_all(ctx)
    except RuntimeError as e:
        if str(e) == "CANCELLED":
            return "cancel"
        _alert("초기화 실패", str(e))
        return "menu"

    sequencer = MotionSequencer(
        ctx.robot, return_motion=RETURN_MOTION,
        action_hold_sec=ACTION_HOLD_SEC, return_hold_sec=RETURN_HOLD_SEC,
    )

    win = "YOLOv5 Robot Control"
    cv2.namedWindow(win)
    cv2.imshow(win, _status_frame("AI 구동 준비 중...", 0))
    cv2.waitKey(1)
    print("[INFO] 인식 시작. 화면의 버튼으로 조작하세요.")

    # 화면 버튼 상태 + 마우스 클릭 처리
    ui = {"yolo_on": True, "quit": False, "btns": {}}

    def on_mouse(event, mx, my, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        for name, (x1, y1, x2, y2) in ui["btns"].items():
            if x1 <= mx <= x2 and y1 <= my <= y2:
                if name == "yolo":
                    ui["yolo_on"] = not ui["yolo_on"]
                elif name == "quit":
                    ui["quit"] = True

    cv2.setMouseCallback(win, on_mouse)

    last_acted = ""
    detections = np.empty((0, 6))
    running = True
    result = "menu"
    read_fail = 0
    spin = 0
    fcount = 0

    try:
        while running:
            ret, frame = ctx.camera.read()
            if not ret or frame is None:
                read_fail += 1; spin += 1
                if read_fail > 60:
                    print("[ERROR] 카메라 프레임 없음")
                    break
                cv2.imshow(win, _status_frame("카메라 신호 대기 중...", spin))
                if (cv2.waitKey(30) & 0xFF) in (27, ord("q")):
                    running = False
                continue
            read_fail = 0
            fcount += 1

            # ---- 로봇 연결 점검 ----
            if fcount % PING_EVERY == 0 and not ctx.robot.ping():
                result = "reselect"
                break

            # ---- YOLOv5 추론 (N프레임마다 1회) ----
            if ui["yolo_on"] and (fcount % INFER_EVERY == 0):
                img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = ctx.model(img_rgb, size=INFER_SIZE)
                detections = results.xyxy[0].cpu().numpy()
            elif not ui["yolo_on"]:
                detections = np.empty((0, 6))

            # ---- 가장 confidence 높은 객체 1개 ----
            top_label, top_conf = "", 0.0
            for det in detections:
                conf = float(det[4]); cls_id = int(det[5])
                if conf > top_conf:
                    top_conf = conf
                    top_label = ctx.model.names[cls_id]

            # ---- 박스 그리기 (직접 그려서 빠르게) ----
            box_texts = []
            for det in detections:
                x1, y1, x2, y2 = (int(det[0]), int(det[1]),
                                  int(det[2]), int(det[3]))
                conf = float(det[4]); name = ctx.model.names[int(det[5])]
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
                box_texts.append((f"{name} {conf*100:.0f}%",
                                  (x1 + 2, max(0, y1 - 22)), 16, (0, 255, 0)))

            # ---- 동작 트리거 (최고 1개 + 직전과 다를 때만) ----
            if (not sequencer.is_busy and top_label in LABEL_TO_MOTION
                    and top_conf >= CONF_THRESHOLD
                    and top_label != last_acted):
                motion = LABEL_TO_MOTION[top_label]
                if sequencer.trigger(motion):
                    last_acted = top_label
                    print(f"[ACTION] {top_label} {top_conf*100:.1f}% "
                          f"→ 모션 {motion}")
                elif not ctx.robot.is_connected:
                    result = "reselect"; break

            sequencer.update()
            if not ctx.robot.is_connected:      # 시퀀스 전송 중 끊김
                result = "reselect"; break

            # 객체가 사라지면(임계값 미만) 직전 기록 해제 → 다시 오면 재동작 허용
            if top_label == "" or top_conf < CONF_THRESHOLD:
                if not sequencer.is_busy:
                    last_acted = ""

            # ---- 화면 버튼 (우상단) ----
            w = frame.shape[1]
            bw, bh, gap = 150, 42, 10
            yb = (w - bw * 2 - gap * 2, gap, w - bw - gap * 2, gap + bh)
            qb = (w - bw - gap, gap, w - gap, gap + bh)
            ui["btns"] = {"yolo": yb, "quit": qb}
            yolo_on = ui["yolo_on"]
            yolo_color = (40, 160, 40) if yolo_on else (90, 90, 90)
            cv2.rectangle(frame, (yb[0], yb[1]), (yb[2], yb[3]),
                          yolo_color, -1)
            cv2.rectangle(frame, (yb[0], yb[1]), (yb[2], yb[3]),
                          (230, 230, 230), 1)
            cv2.rectangle(frame, (qb[0], qb[1]), (qb[2], qb[3]),
                          (40, 40, 200), -1)
            cv2.rectangle(frame, (qb[0], qb[1]), (qb[2], qb[3]),
                          (230, 230, 230), 1)

            # ---- HUD (한글) ----
            yolo_tag = "ON" if yolo_on else "OFF"
            hud = list(box_texts)
            hud += [
                (f"최고: {top_label} ({top_conf*100:.0f}%)" if top_label
                 else "최고: -", (15, 10), 22, (0, 255, 0)),
                (sequencer.status_message, (15, 40), 20, (0, 255, 255)),
                (f"직전 동작: {last_acted or '-'}   |   모델: {ctx.model_label}",
                 (15, 68), 16, (255, 210, 0)),
                # 버튼 라벨
                (f"YOLO {yolo_tag}", (yb[0] + 14, yb[1] + 9), 20, (255, 255, 255)),
                ("■ 종료", (qb[0] + 38, qb[1] + 9), 20, (255, 255, 255)),
            ]
            frame = draw_texts(frame, hud)

            cv2.imshow(win, frame)
            if ui["quit"]:
                running = False
            # 창이 갱신/마우스 이벤트를 처리하려면 waitKey 호출이 필요하다
            key = cv2.waitKey(1) & 0xFF
            if key == 27:          # ESC는 비상 종료용으로만 유지
                running = False
    finally:
        if ctx.robot is not None:
            ctx.robot.close()
        if ctx.camera is not None:
            ctx.camera.release()
        cv2.destroyAllWindows()
        print("[INFO] 인식 종료.")

    if result == "reselect":
        _alert("로봇 연결 끊김",
               "로봇과의 연결이 끊어졌습니다.\n포트를 다시 선택해 주세요.")
    return result


# ============================================================
# 메인 메뉴
# ============================================================
class MainMenu:
    def run(self):
        result = {"v": None}
        root = tk.Tk()
        root.title("YOLOv5 휴머노이드 로봇")
        root.geometry("400x420")

        def pick(v):
            result["v"] = v
            root.destroy()

        tk.Label(root, text="🤖  YOLOv5 휴머노이드 로봇",
                 font=("Malgun Gothic", 16, "bold"), pady=20).pack()

        def big(text, cmd, color):
            return tk.Button(root, text=text, font=("Malgun Gothic", 13, "bold"),
                             bg=color, fg="white", relief="flat", height=2,
                             command=cmd)

        big("⚙  포트 / 장치 설정", lambda: pick("port"), "#1565c0").pack(
            fill="x", padx=40, pady=8)
        big("🧠  로봇 학습", lambda: pick("train"), "#6a1b9a").pack(
            fill="x", padx=40, pady=8)
        big("▶  인식 시작", lambda: pick("recognize"), "#28a745").pack(
            fill="x", padx=40, pady=8)
        tk.Button(root, text="✕  종료", font=("Malgun Gothic", 11),
                  command=lambda: pick("exit")).pack(pady=(16, 0))

        root.protocol("WM_DELETE_WINDOW", lambda: pick("exit"))
        root.mainloop()
        return result["v"]


def main():
    while True:
        choice = MainMenu().run()
        if choice in (None, "exit"):
            break
        if choice == "port":
            PortSelector(title="포트 / 장치 설정", baudrate=BAUDRATE).run()
        elif choice == "train":
            trainer.TrainingMenu().run()
        elif choice == "recognize":
            # 로봇 끊김 시 포트 선택부터 다시 (reselect)
            while True:
                status = run_recognition()
                if status != "reselect":
                    break
    print("[INFO] 프로그램 종료.")


if __name__ == "__main__":
    main()
