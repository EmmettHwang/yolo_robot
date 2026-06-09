# coding: utf-8
"""
train_app.py  (gradio 브랜치, v4.x)
===================================
로컬 Gradio 학습 웹앱 — 런타임(인식) 앱과 분리된 학습 도구.

  ① 데이터 수집 : 브라우저 웹캠으로 캡처 → 클래스별 정사각 저장
  ② 학습        : ultralytics 학습(서브프로세스) + 실시간 로그 + 결과(mAP/그래프)
  ③ 적용/내보내기: best.pt → ONNX(active.onnx) 적용 + 다운로드(active.onnx/classes)

런타임 앱(OpenCV DNN)과의 계약: model/active.onnx + model/active.names

실행:  python robot/train_app.py   →  http://127.0.0.1:7860
무거운 의존성(torch/ultralytics)은 이 학습 도구에만 필요. 배포 exe엔 불필요.
"""

import os
import sys
import shutil
import subprocess

import cv2
import gradio as gr

from paths import (IMG_DIR, LBL_DIR, MODELS_DIR, BASE_WEIGHTS, DATA_YAML,
                   RUNS_DIR, BEST_WEIGHTS, ACTIVE_ONNX, ACTIVE_CLASSES)
from trainer import (load_classes, save_classes, list_images, count_images,
                     next_index, delete_class, build_data_yaml, _imwrite,
                     read_results_metrics, RESULTS_PNG, _fmt_dur, SIZES)
import export_onnx

PY = sys.executable


# ============================================================
# ① 데이터 수집
# ============================================================
def _class_choices():
    return load_classes()


def capture(img_rgb, cls, size):
    cls = (cls or "").strip()
    if img_rgb is None:
        return "웹캠 영상이 없습니다. 카메라를 허용하세요.", None, gr.update()
    if not cls:
        return "클래스 이름을 먼저 입력하세요.", None, gr.update()
    classes = load_classes()
    if cls not in classes:
        classes.append(cls)
        save_classes(classes)
    cls_id = classes.index(cls)
    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(LBL_DIR, exist_ok=True)
    n = next_index(cls)
    stem = f"{cls}_{n:04d}"
    size = int(size)
    bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    sq = cv2.resize(bgr, (size, size))
    if not _imwrite(os.path.join(IMG_DIR, stem + ".jpg"), sq):
        return "저장 실패", None, gr.update()
    with open(os.path.join(LBL_DIR, stem + ".txt"), "w") as f:
        f.write(f"{cls_id} 0.5 0.5 1.0 1.0\n")
    total = sum(count_images(c) for c in classes)
    status = f"✓ '{cls}' {count_images(cls)}장 (전체 {total}장)"
    return status, list_images(cls)[-40:], gr.update(choices=classes, value=cls)


def show_gallery(cls):
    if not cls:
        return None
    return list_images(cls)[-40:]


def init_view():
    """앱 로드 시 클래스 드롭다운/갤러리/카운트를 채운다(첫 클래스 미리 보기)."""
    classes = load_classes()
    first = classes[0] if classes else None
    return (gr.update(choices=classes, value=first),
            show_gallery(first), _counts_md())


def delete_selected_class(cls):
    if cls and cls in load_classes():
        delete_class(cls)
    classes = load_classes()
    return (gr.update(choices=classes, value=(classes[0] if classes else None)),
            None, _counts_md())


def _counts_md():
    classes = load_classes()
    if not classes:
        return "아직 수집된 데이터가 없습니다."
    rows = [f"- **{c}** : {count_images(c)}장" for c in classes]
    total = sum(count_images(c) for c in classes)
    return f"**총 {total}장 / {len(classes)}클래스**\n" + "\n".join(rows)


# ============================================================
# ② 학습
# ============================================================
def train(epochs, imgsz):
    classes = load_classes()
    total = sum(count_images(c) for c in classes)
    if total < 1 or not classes:
        yield "먼저 ① 데이터 수집에서 데이터를 모으세요.", None, ""
        return
    base = BASE_WEIGHTS if os.path.exists(BASE_WEIGHTS) else "yolov5su.pt"
    build_data_yaml()
    code = (
        "from ultralytics import YOLO; "
        "m = YOLO(r'%s'); "
        "m.train(data=r'%s', epochs=%d, imgsz=%d, batch=4, "
        "project=r'%s', name='custom', exist_ok=True, device='cpu', workers=0)"
        % (base, DATA_YAML, int(epochs), int(imgsz), RUNS_DIR)
    )
    TAIL = 200                       # 최근 N줄만 표시(아래쪽 최신 유지)
    lines = [f"학습 시작: {len(classes)}클래스 / {total}장, {epochs}에폭", ""]

    def _tail():
        return "\n".join(lines[-TAIL:])

    yield _tail(), None, ""
    proc = subprocess.Popen([PY, "-c", code], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            bufsize=1)
    for raw in proc.stdout:
        # ultralytics 진행바의 \r 처리: 마지막 조각만 한 줄로
        line = raw.replace("\r", "\n").rstrip("\n").split("\n")[-1]
        if line:
            lines.append(line)
            yield _tail(), None, ""
    proc.wait()
    if proc.returncode != 0:
        lines.append(f"✗ 학습 실패(코드 {proc.returncode})")
        yield _tail(), None, ""
        return
    m = read_results_metrics()
    graph = RESULTS_PNG if os.path.exists(RESULTS_PNG) else None
    lines.append(f"✓ 학습 완료. 결과: {BEST_WEIGHTS}")
    yield _tail(), graph, _metrics_md(m)


def _pct(v):
    return f"{v*100:.1f}%" if isinstance(v, float) else "—"


def _metrics_md(m):
    if not m:
        return "결과 지표를 읽지 못했습니다. 그래프로 확인하세요."
    verdict = ("👍 우수 — 적용해도 좋아요." if isinstance(m.get("mAP50"), float)
               and m["mAP50"] >= 0.8 else
               "🙂 쓸 만 — 데이터 더 모으면 개선." if isinstance(m.get("mAP50"), float)
               and m["mAP50"] >= 0.5 else
               "👎 낮음 — 데이터/에폭 늘려 재학습 권장.")
    return (f"### 📊 학습 결과 ({m.get('epochs','?')} 에폭)\n"
            f"| mAP@50 | mAP@50-95 | 정밀도 | 재현율 |\n"
            f"|---|---|---|---|\n"
            f"| **{_pct(m.get('mAP50'))}** | {_pct(m.get('mAP5095'))} | "
            f"{_pct(m.get('precision'))} | {_pct(m.get('recall'))} |\n\n{verdict}")


# ============================================================
# ③ 적용 / 내보내기
# ============================================================
def export_apply(name):
    if not os.path.exists(BEST_WEIGHTS):
        return "② 학습을 먼저 끝내세요(best.pt 없음).", None
    name = (name or "custom").strip()
    if not name.endswith(".pt"):
        name += ".pt"
    os.makedirs(MODELS_DIR, exist_ok=True)
    dst = os.path.join(MODELS_DIR, name)
    try:
        shutil.copy(BEST_WEIGHTS, dst)              # 학습 가중치 보관(best.pt 사본)
        names = export_onnx.apply_pt_as_active(dst, label=name)   # → active.onnx
    except Exception as e:
        return f"✗ 변환 실패: {e}", None
    # 다운로드: ONNX(추론용) + classes(클래스명) + .pt(원본 가중치/재학습용)
    files = [p for p in (ACTIVE_ONNX, ACTIVE_CLASSES, dst)
             if os.path.exists(p)]
    msg = (
        f"✓ 변환 완료 — **{name}**, 클래스 {len(names)}개\n\n"
        "**아래 3개 파일을 다운로드**하세요:\n"
        "- `active.onnx` — 인식(추론)용 모델\n"
        "- `active.names` — 클래스 이름 목록\n"
        f"- `{name}` — 학습 가중치(best.pt 사본, 재학습/재변환용)\n\n"
        "**📂 저장 위치**: 다운로드한 `active.onnx` + `active.names` 를 "
        "**런타임 PC의 `gradio/model/` 폴더**에 넣으세요. "
        "(`.pt` 는 보관용 — `model/` 에 같이 둬도 됩니다)\n"
        "그 뒤 인식 앱에서 **■ 정지 → ▶ 연결 & 시작** 하면 새 모델이 적용됩니다."
    )
    return msg, files


# ============================================================
# UI
# ============================================================
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build():
    with gr.Blocks(title="ROBO COMMANDER — 학습 웹앱") as demo:
        gr.Markdown("# 🧠 ROBO COMMANDER 학습 웹앱\n"
                    "데이터 수집 → 학습 → ONNX 내보내기. "
                    "결과(`active.onnx`)는 런타임 인식 앱이 그대로 사용합니다.")

        with gr.Tab("① 데이터 수집"):
            with gr.Row():
                with gr.Column():
                    cam = gr.Image(sources=["webcam"], type="numpy",
                                   label="웹캠", height=320)
                    with gr.Row():
                        cls_in = gr.Textbox(label="클래스 이름", scale=2,
                                            placeholder="예: my_robot")
                        size_in = gr.Radio(SIZES, value=320, label="저장 크기(px)")
                    cap_btn = gr.Button("📸 캡처", variant="primary")
                    cap_status = gr.Markdown("")
                with gr.Column():
                    cls_dd = gr.Dropdown(_class_choices(), label="클래스 보기",
                                         interactive=True)
                    gallery = gr.Gallery(label="수집된 데이터(최근 40)",
                                         columns=4, height=320)
                    with gr.Row():
                        refresh_btn = gr.Button("↻ 새로고침")
                        del_btn = gr.Button("🗑 클래스 삭제", variant="stop")
                    counts = gr.Markdown(_counts_md())

            cap_btn.click(capture, [cam, cls_in, size_in],
                          [cap_status, gallery, cls_dd]).then(
                _counts_md, None, counts)
            cls_dd.change(show_gallery, cls_dd, gallery)
            refresh_btn.click(lambda: (gr.update(choices=_class_choices()),
                                       _counts_md()), None, [cls_dd, counts])
            del_btn.click(delete_selected_class, cls_dd,
                          [cls_dd, gallery, counts])

        with gr.Tab("② 학습"):
            with gr.Row():
                epochs_in = gr.Number(value=30, label="에폭", precision=0)
                imgsz_in = gr.Dropdown([str(s) for s in SIZES], value="320",
                                       label="이미지 크기")
                train_btn = gr.Button("▶ 학습 시작", variant="primary")
            gr.Markdown("※ CPU 학습이라 느립니다. 클래스당 20~50장, 에폭 10~30 권장.")
            train_log = gr.Textbox(label="학습 로그", lines=16, max_lines=16,
                                   autoscroll=True)
            with gr.Row():
                result_graph = gr.Image(label="학습 곡선", height=300)
                result_md = gr.Markdown("")
            train_btn.click(train, [epochs_in, imgsz_in],
                            [train_log, result_graph, result_md])

        with gr.Tab("③ 적용 / 내보내기"):
            gr.Markdown("학습한 모델을 ONNX(`active.onnx`)로 변환해 인식에 적용하고, "
                        "파일로 내려받아 다른 PC로 옮길 수 있습니다.")
            name_in = gr.Textbox(value="custom", label="모델 이름")
            exp_btn = gr.Button("🚀 ONNX 변환 & 적용", variant="primary")
            exp_status = gr.Markdown("")
            exp_files = gr.File(label="⬇ 다운로드 (active.onnx · active.names · best.pt)",
                                file_count="multiple")
            exp_btn.click(export_apply, name_in, [exp_status, exp_files])

        # 앱 로드 시 클래스 보기/카운트 초기화
        demo.load(init_view, None, [cls_dd, gallery, counts])

    return demo


if __name__ == "__main__":
    build().launch(server_name="127.0.0.1", server_port=7860, inbrowser=True)
