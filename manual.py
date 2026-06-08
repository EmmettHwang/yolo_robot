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
# 🤖 YOLOv5 휴머노이드 로봇 — 사용 설명서

버전 `{__version__}`

이 프로그램은 카메라로 객체를 인식해 휴머노이드 로봇을 동작시키고,
조이스틱·버튼으로 직접 조종하며, 직접 데이터를 모아 학습까지 할 수 있습니다.

---

## 1. 시작하면 이렇게 흘러갑니다

프로그램(`python main.py`)을 켜면 단계가 순서대로 진행됩니다.

- **① 포트·장치** : 장치 설정창이 자동으로 열립니다. 포트·카메라·마이크를 테스트하고 창을 닫으면, 이상이 없을 때 다음 단계로 자동 이동합니다.
- **② 로봇 학습** : YOLOv5 모델을 자동으로 불러옵니다(로딩 막대). 다 되면 인식 단계로 넘어갑니다.
- **🎯 객체 반응** : 어떤 객체를 보면 어떤 동작·소리를 낼지 미리 정합니다.
- **④ 인식 시작** : 실제로 카메라를 켜고 인식·조종을 합니다.

---

## 2. 포트·장치 설정

`장치 설정 열기`를 누르면 설정창이 뜹니다. 여기서:

- **시리얼(로봇) 포트** : 블루투스로 페어링된 로봇 포트를 고릅니다. `★ 페어링됨` 표시가 붙은 것이 로봇일 가능성이 높습니다.
- **동작 테스트** : 로봇 그림 옆 버튼으로 실제로 움직여 보고 맞는 포트인지 확인합니다.
- **카메라 / 마이크 / 스피커** : 미리보기, 마이크 녹음·재생, 테스트음으로 점검합니다.
- 선택값은 자동 저장되어 인식·학습에서 그대로 쓰입니다.

---

## 3. 객체 반응 지정

인식된 객체마다 **동작(모션)** 과 **소리**를 지정합니다.

- **객체 검색** 칸에 이름 일부를 치면 목록이 걸러집니다. (COCO 80종 지원)
- 객체·모션은 **중복 없이** 드롭다운에 나옵니다. (이미 쓴 것은 빠짐)
- 소리는 **음성 없음 / mp3 / TTS(읽기)** 중 선택합니다.
  - **mp3** : `assets/mp3` 폴더의 파일이 `파일명 | 제목 - 가수 (길이)` 로 보입니다.
  - **TTS** : 읽어줄 문장을 직접 입력합니다.
- 다 정했으면 **💾 저장**을 누릅니다.

---

## 4. 인식 화면

- **▶ 연결 & 시작** : 저장된 포트·카메라로 연결하고 인식을 시작합니다.
- **YOLO: ON/OFF** : 자동 인식을 켜고 끕니다. **YOLO가 켜져 있으면 수동 조작(조이스틱·버튼)은 잠깁니다.** 직접 조종하려면 OFF로 바꾸세요.
- **사운드: ON/OFF** : 동작 시 소리를 켜고 끕니다.
- **■ 동작 정지** : 진행 중인 동작을 멈추고 기본자세로 돌아옵니다.
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

## 5. 로봇 학습

`학습하기`를 누르면 별도 창이 열립니다.

- **데이터 수집** : 카메라로 객체를 비추고 클래스 이름을 정한 뒤 캡처합니다. (이미지 1장 = 객체 1개로 가정)
- **학습 시작** : 모은 데이터로 모델을 학습합니다. (CPU라 느리니 클래스당 20~50장, 에폭 10~30 권장)
- **모델 교체** : 학습 결과를 인식에 적용합니다.

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
