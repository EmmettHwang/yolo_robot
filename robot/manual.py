# coding: utf-8
"""
manual.py
=========
사용 설명서(마크다운)를 tkinter Text 위젯에 예쁘게 렌더링해서 보여준다.
앱 헤더의 버전 라벨을 누르면 show_manual()이 호출된다.

경량 마크다운 렌더러: # / ## / ### 제목, - 불릿, **굵게**, `코드`, --- 구분선 지원.
(표 대신 불릿을 써서 깔끔하게 보이도록 설명서를 구성)
"""

import re
import tkinter as tk
from tkinter import ttk

from version import __version__

MANUAL_MD = f"""
# 🤖 YOLO 기반 휴머노이드 ROBO COMMANDER — 사용 설명서

버전 `{__version__}`

이 프로그램은 카메라로 객체를 인식해 휴머노이드 로봇을 동작시키고,
조이스틱·버튼으로 직접 조종하며, 직접 데이터를 모아 학습까지 할 수 있습니다.

---

## 1. 시작하면 이렇게 흘러갑니다

프로그램(`python main.py`)을 켜면 단계가 순서대로 진행됩니다.

- **① 로봇장치설정** : 장치 설정창이 자동으로 열립니다. 블루투스 페어링·포트·카메라·마이크를 테스트하고 창을 닫으면, 이상이 없을 때 다음 단계로 자동 이동합니다.
- **② 인공지능학습** : YOLO 모델을 자동으로 불러옵니다(로딩 막대). 다 되면 다음 단계로 넘어갑니다.
- **③ 인식및반응설정** : 어떤 객체를 보면 어떤 동작·소리를 낼지 미리 정합니다.
- **④ 자율활동시작** : 실제로 카메라를 켜고 인식·조종을 합니다.

---

## 2. 로봇장치설정

`장치 설정 열기`를 누르면 설정창이 뜹니다. 여기서:

- **블루투스 페어링 도우미** : `🔵 블루투스 설정 열기`로 Windows 설정을 열고, 휴머노이드(FB153)를 **PIN `0000`** 으로 페어링한 뒤 `↻ 페어링 후 다시 검색`을 누르면 포트를 자동으로 잡습니다.
- **시리얼(로봇) 포트** : FB153은 `★ 휴머노이드` 로 표시됩니다.
- **동작 테스트 / LED 테스트** : 로봇 그림(클릭하면 크게 보기) 옆 버튼으로 실제로 움직여 맞는 포트인지 확인합니다.
- **카메라 / 마이크 / 스피커** : 미리보기, 마이크 녹음·재생, 테스트음으로 점검합니다.
- 선택값은 자동 저장되어 인식·학습에서 그대로 쓰입니다.

---

## 3. 인식및반응설정 (객체 반응)

인식된 객체마다 **동작(모션)** 과 **소리**를 지정합니다. 객체 이름은 `1. person (사람)` 처럼 번호·한글이 함께 표시됩니다.

- **객체 검색** 칸에 이름 일부를 치면 목록이 걸러집니다. (COCO 80종 + 직접 수집 클래스)
- **＋ 서브 동작** : 한 객체에 (동작+소리) 스텝을 **최대 5개**까지 추가해 순서대로 실행합니다. `✕` 로 스텝/객체를 지웁니다.
- 소리는 **음성 없음 / mp3 / TTS(읽기) / random** 중 선택합니다.
  - **mp3** : `assets/mp3` 폴더의 파일이 `파일명 | 제목 - 가수 (길이)` 로 보입니다.
  - **TTS** : 읽어줄 문장을 직접 입력합니다.
  - **random** : 내장 로봇 효과음(다양한 소리)을 무작위로 냅니다.
- **지속(초)** 을 비우면 mp3 길이만큼 유지합니다.
- 변경은 자동 저장되며, 인식 화면의 `↻ 매핑 새로고침` 으로 즉시 반영됩니다.

---

## 4. 인식 화면

- **▶ 연결 & 시작** : 저장된 포트·카메라로 연결하고 인식을 시작합니다.
- **YOLO: ON/OFF** : 자동 인식을 켜고 끕니다. **YOLO가 켜져 있으면 수동 조작(조이스틱·버튼)은 잠깁니다.** 직접 조종하려면 OFF로 바꾸세요.
- **사운드: ON/OFF** : 동작 시 소리를 켜고 끕니다.
- **■ 동작 정지** : 진행 중인 동작을 멈추고 기본자세로 돌아옵니다("딱!" 효과음).
- **🎛 로봇 제어** : 누르면 동작 정지+YOLO OFF 후 제어판(LED/포지션/전원/**영점 보정**)이 모달로 열립니다.
  - **영점(오프셋) 보정** : `ZeroPose`(전 관절 0) → 관절별 오프셋(−12~+12, 슬라이더 실시간 적용) → `BasePose`(기본자세) 순으로 영점을 맞춥니다.
- 로봇 연결이 끊기면 알림이 뜨고 포트를 다시 고르도록 안내합니다.

### 조이스틱 (8방향)

방향을 누르고 있으면 그 동작이 반복됩니다. 놓으면 멈추고 기본자세로 돌아옵니다.

- **위** : 전진      - **아래** : 후진
- **좌 / 우** : 옆걸음      - **좌상/우상** : 전진 좌/우
- **좌하/우하** : 좌/우 회전

### 4×4 동작 버튼

- **좌클릭** : 그 동작 실행(+지정한 소리 재생)
- **우클릭** : 그 버튼에 **동작 + 소리**를 지정 (모두 드롭다운)
- **💾 저장** 으로 버튼 설정을 보관합니다.

---

## 5. 인공지능학습

`학습하기`를 누르면 **학습 스튜디오**(하나의 창, ①수집 → ②학습 → ③적용 탭)가 열립니다.

- **① 데이터 수집** : 카메라로 객체를 비추고 클래스 이름을 정한 뒤 캡처합니다. (이미지 1장 = 객체 1개로 가정)
- **② 학습** : 모은 데이터로 모델을 학습합니다. (CPU라 느리니 클래스당 20~50장, 에폭 10~30 권장) 학습이 끝나면 **총 소요 시간**과 함께 결과 창이 뜹니다.
  - 결과 창에 **학습 곡선 그래프 + mAP50/mAP50-95/정밀도/재현율**이 표시되어, 보고 **저장**하거나 **버릴** 수 있습니다.
- **③ 모델 적용** : 학습 모델·기본 모델을 인식에 적용(active)합니다. 현재 적용 모델은 초록 배너로 표시됩니다.

---

## 6. 동작 번호 메모

- 전진 = `2 → 3 → 4` 반복, 후진 = `9 → 11 → 10` 반복 (각 동작 사이 200ms)
- 인사 18, 절 19, 승리 17 … 전체 번호는 모션 테이블 PDF 참고

---

## 7. 버전 규칙

형식 `MAJOR.MINOR.날짜.시간` (예 `{__version__}`)

- `MAJOR.MINOR` : 기능이 바뀌면 올리는 의미적 버전 (1.0부터)
- `날짜.시간` : 커밋/푸시 시점. 헤더의 버전을 누르면 이 설명서가 열립니다.
"""


def _render(tw: tk.Text, md: str) -> None:
    tw.config(state="normal")
    tw.delete("1.0", "end")
    tw.tag_configure("h1", font=("Malgun Gothic", 19, "bold"),
                     foreground="#1e2a4a", spacing1=6, spacing3=10)
    tw.tag_configure("h2", font=("Malgun Gothic", 14, "bold"),
                     foreground="#1565c0", spacing1=12, spacing3=6)
    tw.tag_configure("h3", font=("Malgun Gothic", 12, "bold"),
                     foreground="#37474f", spacing1=8, spacing3=4)
    tw.tag_configure("body", font=("Malgun Gothic", 11), spacing3=4)
    tw.tag_configure("bullet", font=("Malgun Gothic", 11),
                     lmargin1=24, lmargin2=44, spacing3=3)
    tw.tag_configure("bold", font=("Malgun Gothic", 11, "bold"))
    tw.tag_configure("code", font=("Consolas", 10), background="#eef1f7")

    def inline(line, base):
        parts = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", line)
        for p in parts:
            if p.startswith("**") and p.endswith("**"):
                tw.insert("end", p[2:-2], (base, "bold"))
            elif p.startswith("`") and p.endswith("`"):
                tw.insert("end", p[1:-1], (base, "code"))
            else:
                tw.insert("end", p, base)
        tw.insert("end", "\n")

    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith("### "):
            inline(s[4:], "h3")
        elif s.startswith("## "):
            inline(s[3:], "h2")
        elif s.startswith("# "):
            inline(s[2:], "h1")
        elif s.strip() == "---":
            tw.insert("end", "─" * 60 + "\n", "body")
        elif s.lstrip().startswith(("- ", "* ")):
            indent = "    " if s.startswith(("  - ", "  * ")) else ""
            inline(indent + "• " + s.lstrip()[2:], "bullet")
        elif s.strip() == "":
            tw.insert("end", "\n")
        else:
            inline(s, "body")
    tw.config(state="disabled")


def show_manual(parent=None) -> None:
    top = tk.Toplevel(parent) if parent is not None else tk.Tk()
    top.title("사용 설명서")
    top.geometry("720x760")
    if parent is not None:
        top.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel")
                      else parent)

    wrap = tk.Frame(top, bg="white"); wrap.pack(fill="both", expand=True)
    tw = tk.Text(wrap, wrap="word", bg="white", relief="flat",
                 padx=24, pady=18, cursor="arrow")
    sb = ttk.Scrollbar(wrap, orient="vertical", command=tw.yview)
    tw.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tw.pack(side="left", fill="both", expand=True)
    _render(tw, MANUAL_MD)

    tk.Button(top, text="닫기", font=("Malgun Gothic", 10), cursor="hand2",
              command=top.destroy).pack(pady=8)


if __name__ == "__main__":
    show_manual()
    tk.mainloop()
