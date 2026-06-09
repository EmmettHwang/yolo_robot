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
# 학습 후 결과 그래프: PR(정밀도-재현율) 커브만 크게 사용
PR_CURVE = os.path.join(os.path.dirname(RESULTS_PNG), "PR_curve.png")


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
    # patience: 성능 개선이 N에폭 동안 없으면 조기 종료(best는 항상 저장됨)
    patience = 10
    code = (
        "from ultralytics import YOLO; "
        "m = YOLO(r'%s'); "
        "m.train(data=r'%s', epochs=%d, imgsz=%d, batch=4, patience=%d, "
        "project=r'%s', name='custom', exist_ok=True, device='cpu', workers=0)"
        % (base, DATA_YAML, int(epochs), int(imgsz), patience, RUNS_DIR)
    )
    TAIL = 400                       # 이력 보존(스크롤). 바닥 고정은 JS가 처리
    lines = [f"학습 시작: {len(classes)}클래스 / {total}장, 최대 {epochs}에폭 "
             f"(개선 없으면 {patience}에폭 후 자동 종료)", ""]

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
            yield _tail(), None, _live_md(read_results_metrics())  # 실시간 지표
    proc.wait()
    if proc.returncode != 0:
        lines.append(f"✗ 학습 실패(코드 {proc.returncode})")
        yield _tail(), None, ""
        return
    m = read_results_metrics()
    graph = (PR_CURVE if os.path.exists(PR_CURVE)
             else (RESULTS_PNG if os.path.exists(RESULTS_PNG) else None))
    lines.append("✓ 학습 완료! ③ 내보내기 탭에서 모델을 받으세요.")
    yield _tail(), graph, _metrics_md(m)


def _pct(v):
    return f"{v*100:.1f}%" if isinstance(v, float) else "—"


def _live_md(m):
    """학습 중 실시간 지표(에폭마다 갱신). PR 곡선 그림은 완료 시에만."""
    if not m or m.get("mAP50") is None:
        return "⏳ 학습 준비/진행 중... (첫 에폭이 끝나면 지표가 표시됩니다)"
    return (f"### ⏳ 진행 중 — {m.get('epochs','?')}에폭째 (실시간)\n"
            f"| mAP@50 | mAP@50-95 | 정밀도 | 재현율 |\n"
            f"|---|---|---|---|\n"
            f"| **{_pct(m.get('mAP50'))}** | {_pct(m.get('mAP5095'))} | "
            f"{_pct(m.get('precision'))} | {_pct(m.get('recall'))} |\n"
            f"_정밀도-재현율(PR) 곡선 그림은 학습이 끝나면 아래에 표시됩니다._")


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


def _have_data():
    return sum(count_images(c) for c in load_classes()) > 0


def _have_model():
    return os.path.exists(BEST_WEIGHTS)


def build():
    with gr.Blocks(title="로봇 학습") as demo:
        gr.Markdown("# 🧠 로봇 학습\n"
                    "**① 데이터 모으기 → ② 학습하기 → ③ 내보내기** 순서로 진행하세요.\n"
                    "_데이터를 모아야 학습 탭이, 학습을 마쳐야 내보내기 탭이 열립니다._")

        with gr.Tab("① 데이터 모으기"):
            with gr.Row():
                with gr.Column():
                    cam = gr.Image(sources=["webcam"], type="numpy",
                                   label="카메라", height=320)
                    with gr.Row():
                        cls_in = gr.Textbox(label="무엇을 가르칠까요? (이름)",
                                            scale=2, placeholder="예: 내 로봇")
                        size_in = gr.Radio(SIZES, value=320, label="사진 크기")
                    cap_btn = gr.Button("📸 사진 찍기", variant="primary")
                    cap_status = gr.Markdown("")
                    gr.Markdown("같은 대상을 각도·거리를 바꿔 20~50장 찍으면 좋아요.")
                with gr.Column():
                    cls_dd = gr.Dropdown(_class_choices(), label="모은 것 보기",
                                         interactive=True)
                    gallery = gr.Gallery(label="모은 사진(최근 40장)",
                                         columns=4, height=320)
                    with gr.Row():
                        refresh_btn = gr.Button("↻ 새로고침")
                        del_btn = gr.Button("🗑 이 이름 지우기", variant="stop")
                    counts = gr.Markdown(_counts_md())

        with gr.Tab("② 학습하기", interactive=_have_data()) as tab2:
            with gr.Row():
                epochs_in = gr.Number(value=30, label="반복 횟수(에폭)",
                                      precision=0)
                imgsz_in = gr.Dropdown([str(s) for s in SIZES], value="320",
                                       label="사진 크기")
                train_btn = gr.Button("▶ 학습 시작", variant="primary")
            gr.Markdown("※ 시간이 좀 걸립니다. 처음엔 반복 10~30 정도로 해보세요.")
            train_log = gr.Textbox(label="진행 상황", lines=18, max_lines=18,
                                   autoscroll=True, elem_id="trainlog")
            result_md = gr.Markdown("")
            result_graph = gr.Image(label="정밀도-재현율(PR) 곡선", height=460)

        with gr.Tab("③ 내보내기", interactive=_have_model()) as tab3:
            gr.Markdown("학습한 모델을 **내려받아 로봇 PC에 넣으면** 인식에 사용됩니다.")
            name_in = gr.Textbox(value="내모델", label="모델 이름")
            exp_btn = gr.Button("📦 모델 만들기", variant="primary")
            exp_status = gr.Markdown("")
            exp_files = gr.File(label="⬇ 모델 파일 내려받기", file_count="multiple")

        # ---------- 이벤트 ----------
        def _gate2():
            return gr.update(interactive=_have_data())

        def _gate3():
            return gr.update(interactive=_have_model())

        cap_btn.click(capture, [cam, cls_in, size_in],
                      [cap_status, gallery, cls_dd]).then(
            _counts_md, None, counts).then(_gate2, None, tab2)
        cls_dd.change(show_gallery, cls_dd, gallery)
        refresh_btn.click(lambda: (gr.update(choices=_class_choices()),
                                   _counts_md()), None, [cls_dd, counts]).then(
            _gate2, None, tab2)
        del_btn.click(delete_selected_class, cls_dd,
                      [cls_dd, gallery, counts]).then(_gate2, None, tab2)
        train_btn.click(train, [epochs_in, imgsz_in],
                        [train_log, result_graph, result_md]).then(
            _gate3, None, tab3)
        exp_btn.click(export_apply, name_in, [exp_status, exp_files])

        # 앱 로드 시 초기화(클래스 보기/카운트 + 탭 잠금 상태)
        demo.load(init_view, None, [cls_dd, gallery, counts])
        demo.load(lambda: (_gate2(), _gate3()), None, [tab2, tab3])
        # 진행 로그를 항상 맨 아래로 고정(최신이 끝줄에 보이도록)
        demo.load(None, None, None, js="""
        () => {
          if (window.__logPin) return;
          window.__logPin = setInterval(() => {
            const ta = document.querySelector('#trainlog textarea');
            if (ta) ta.scrollTop = ta.scrollHeight;
          }, 250);
        }
        """)

    return demo


if __name__ == "__main__":
    host = os.getenv("TRAIN_HOST", "127.0.0.1")
    port = int(os.getenv("TRAIN_PORT", "7860"))
    local = host in ("127.0.0.1", "localhost")
    print(f"[train_app] 서버 시작: http://{host}:{port}  "
          f"(외부 접속은 http://<이 PC IP>:{port})")
    # 수집 이미지(dataset/)·결과 그래프(runs/)를 갤러리에서 보여주려면 경로 허용 필요
    build().launch(server_name=host, server_port=port, inbrowser=local,
                   allowed_paths=[ROOT])
