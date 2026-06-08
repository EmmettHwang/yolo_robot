<div align="center">

# 🤖 YOLOv5 + Humanoid Robot Control

**버전: `2.3.20260609.0202`**

</div>

## 📌 버전 규칙

형식: `MAJOR.MINOR.날짜.시간` (예: `1.0.20260608.2353`)

| 구성 | 의미 |
|------|------|
| `MAJOR.MINOR` | 의미적 버전. 기능이 늘거나 바뀌면 수동으로 올림. **1.0 부터 시작** |
| `날짜(YYYYMMDD)` | 커밋/푸시한 날짜 |
| `시간(HHMM)` | 커밋/푸시한 시각 |

- 버전 값은 [version.py](version.py) 의 `__version__` 에 보관하며, 앱 헤더 우측에 표시된다.
- **커밋/푸시할 때마다 날짜·시간을 갱신**한다. 기능 변경이 크면 `MINOR`(또는 `MAJOR`)도 올린다.

### 변경 이력
| 버전 | 내용 |
|------|------|
| `2.3.20260609.0202` | 리소스 정리: 이미지 → image/, PDF → protocol/ 폴더로 이동(paths.py 경로 갱신) |
| `2.2.20260609.0155` | 장치설정 자동오픈이 루트 경로로 port_selector.py 실행하던 버그 수정(robot/ 경로로) |
| `2.1.20260609.0153` | 객체반응 지속시간 입력을 행 인라인('지속 [__] 초')으로 정렬, VS Code launch.json 추가 |
| `2.0.20260609.0146` | 추론/학습 엔진을 ultralytics로 전환(YOLOv5/v8/v11 호환, yolov5 클론 불필요). 'ultra' 브랜치 |
| `1.6.20260609.0138` | 구조 정리(모듈 robot/, main.py만 루트), 가중치 model/ 폴더, 데이터수집 개편(연속캡처·클래스 추가/삭제·썸네일·저장크기 144/200/320/640), 학습 후 best.pt 이름 지정해 model/ 저장·교체 |
| `1.5.20260609.0132` | LED 테스트 후 기본자세(모션1) 복귀 보장(전송 중 끊겨도 재연결해 1번 전송) |
| `1.4.20260609.0125` | 자동/수동 진행 체크박스(장치·YOLO·인식), 동작정지=즉시 모션1, LED테스트 후 모션1 복귀, 객체반응 지속시간(초)+동작종료감지 비활성표시, 인식 탭 복귀 딜레이 누적 제거 |
| `1.3.20260609.0113` | 장치 설정 창 진행 중 메인 윈도 잠금(대기 다이얼로그+프로그래스바) |
| `1.3.20260609.0108` | 포지션 수동 조절(토크 해제 후 손으로 돌리면 위치 읽어 표시, 프로토콜 Get NowPosition) |
| `1.2.20260609.0058` | 객체반응/인식에 객체 한글+번호 일관 표시, 동작정지=Ready 복귀+페이드인 LED, 설정 제목 '장치 및 로봇 설정' |
| `1.2.20260609.0053` | COCO 목록을 스크롤 리스트(80종 전체, 한글 번역 병기)로 표시, 탭 복귀 시에도 유지 |
| `1.2.20260609.0049` | 로봇 제어 LED/포지션 실시간 전송, 포지션 안전범위 ±100 제한(매뉴얼 기준), 토크 기본 40% |
| `1.2.20260609.0044` | 모델 로딩 중 COCO 클래스를 번호 붙여 10줄 스크롤 표시 |
| `1.2.20260609.0042` | LED 테스트: 동작17 실행→멈출 때까지 화려하게 반복→종료 시 동작1 복귀 |
| `1.2.20260609.0040` | mp3 반응 시 mp3 길이만큼 동작 지속(중지 전까지 안 끊음), 반응 중 새 트리거 차단, 동작중지 시 mp3도 정지 |
| `1.2.20260609.0032` | 안전 전원: 끄기=Safe Sit→7초→전원OFF, 켜기=전원ON→Safe Up |
| `1.2.20260609.0030` | 매뉴얼 PDF 뷰어(목차 클릭 이동), 인식 반응 LED 연출(페이드인→반짝→동작→페이드아웃→반짝), 모델 로딩 중 COCO 클래스 쇼케이스, 장치데모 모션 번호+이름, 동작버튼·객체반응 자동 저장 |
| `1.1.20260609.0017` | LSC 프로토콜 모듈, **LED 제어 + 포지션 제어 + 전원** 추가, 모터맵(18관절), 장치데모에 모터맵 이미지·LED 테스트(1~18), 탭 전환/장치설정 시 포트 반환 |
| `1.0.20260608.2357` | 인식 탭 진입 시 자동 시작, 동작 정지 시 모션 0 전송 |
| `1.0.20260608.2353` | 버전 체계 도입, 후진 시퀀스(9,11,10) 수정, YOLO중 수동조작 잠금, 동작 정지 버튼 |
| `1.0` (이전) | 모듈화 리팩터(탭 메인 윈도우/인식 뷰/조이스틱/4×4 그리드/객체반응/사운드/학습) |

<div align="center">

## yolo_robot 가상환경 활성화 안되는 문제 
그냥 답은 settings.json에 있다. 내용은 다음과 같이 작성 되면 된다. 예를 들어 가상환경이 yolo_robot 인경우 
{
  "python.defaultInterpreterPath": "d:\\miniconda3\\envs\\yolo_robot\\python.exe",
  "python.condaPath": "d:\\miniconda3\\Scripts\\conda.exe",
  "python.terminal.activateEnvironment": true,

  "terminal.integrated.defaultProfile.windows": "PowerShell (yolo_robot)",
  "terminal.integrated.profiles.windows": {
    "PowerShell (yolo_robot)": {
      "source": "PowerShell",
      "args": ["-NoExit", "-Command", "conda activate yolo_robot"]
    }
  }
}

### 모듈화 통합 시스템 (Modular Integration)

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg?logo=python&logoColor=white)]()
[![PyTorch](https://img.shields.io/badge/PyTorch-2.0+-EE4C2C.svg?logo=pytorch&logoColor=white)]()
[![YOLOv5](https://img.shields.io/badge/YOLOv5-Ultralytics-00FFFF.svg)]()
[![OpenCV](https://img.shields.io/badge/OpenCV-4.8+-5C3EE8.svg?logo=opencv&logoColor=white)]()
[![Serial](https://img.shields.io/badge/PySerial-3.5+-orange.svg)]()
[![License](https://img.shields.io/badge/License-AGPL--3.0-green.svg)]()

**실시간 객체 인식과 휴머노이드 모션 제어를 하나의 파이프라인으로**
*— 그러나 각 부품은 따로 떼어내 어디서든 재사용 가능하도록 —*

</div>

---

## 📌 프로젝트 소개

이 프로젝트는 다음 두 저장소의 **핵심 기능을 모듈로 분리**해 통합한 시스템입니다.

| 원본 저장소 | 가져온 핵심 | 모듈화된 위치 |
|:-----------|:-----------|:------------|
| 🎯 [`yolov5ReadTime`](https://github.com/EmmettHwang/yolov5ReadTime) | YOLOv5 실시간 객체 탐지 | `main.py` 메인 루프 |
| 🦾 [`robotControlWithTM`](https://github.com/EmmettHwang/robotControlWithTM) | 시리얼 포트 선택 UI | **`port_selector.py`** ⭐ |
| 🦾 [`robotControlWithTM`](https://github.com/EmmettHwang/robotControlWithTM) | 휴머노이드 모션 패킷 + 시퀀스 | **`robot_controller.py`** ⭐ |

> 💡 **모듈화의 이점**
> - 다른 프로젝트에서 `from port_selector import PortSelector` 한 줄로 재사용
> - YOLOv5 대신 **음성 인식 / 버튼 / 센서**로 트리거를 바꿔도 로봇 제어 로직은 그대로
> - 각 모듈을 **단독 실행**해서 디버깅 가능 (`python robot_controller.py`)

---

## 🗂️ 프로젝트 구조

```
project_root/
│
├── 🎛️  port_selector.py        # [모듈] 시리얼 포트 선택 UI
├── 🦾  robot_controller.py     # [모듈] 로봇 제어 + 시퀀스 관리
├── 🚀  main.py                  # YOLOv5 + 위 두 모듈 통합 실행 파일
│
├── 📋  requirements.txt
├── 📖  README.md
├── ⚙️  config.ini              # (자동 생성) 마지막 사용 포트 저장
│
└── 📦  yolov5/                 # ultralytics/yolov5 클론 폴더
    ├── hubconf.py
    ├── models/
    └── ...
```

---

## 🏗️ 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                          main.py                                │
│                                                                 │
│   ┌─────────────────┐       ┌──────────────────────────────┐    │
│   │  port_selector  │  →    │      robot_controller        │    │
│   │   .PortSelector │       │  HumanoidRobot               │    │
│   │                 │       │  MotionSequencer             │    │
│   └────────┬────────┘       └──────────────┬───────────────┘    │
│            ↓                               ↑                    │
│       선택된 COM 포트                  trigger(motion_id)        │
│            ↓                               ↑                    │
│   ┌────────────────────────────────────────┴───────────────┐    │
│   │              YOLOv5 (torch.hub)                        │    │
│   │   카메라 프레임 → 추론 → 라벨 → LABEL_TO_MOTION        │    │
│   └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                ↓
                        🤖 휴머노이드 로봇
                       (Serial 115200 bps)
```

---

## 📦 모듈 1 · `port_selector.py`

> tkinter 기반 시리얼 포트 선택 UI. 마지막 선택을 `config.ini`에 자동 저장.

### 🎨 UI 두 가지 모드

```
┌──────────────────────────────┐      ┌──────────────────────────────┐
│  🔌 포트 선택                 │      │  ⏳ 진행바 모드               │
├──────────────────────────────┤      ├──────────────────────────────┤
│                              │      │  1. 포트 연결 중...    20%    │
│  [COM3 - USB-SERIAL  ▼]      │      │  ████████░░░░░░░░░░░░░       │
│                              │  →   │                              │
│  [   확인   ]                │      │  2. 모델 로드 중...    55%   │
│                              │      │  ████████████████░░░░░       │
└──────────────────────────────┘      └──────────────────────────────┘
        run() 호출                       run_with_progress() 호출
```

### 💻 사용법

```python
from port_selector import PortSelector

# (A) 단순 포트 선택
selector = PortSelector(title="포트 선택", baudrate=115200)
port = selector.run()              # → "COM3" 또는 None

# (B) 포트 선택 + 후속 초기화 진행바
def my_init(update):
    update("모델 로드 중", "yolov5s 가중치", 50)
    # ... 무거운 작업 ...
    update("완료", "", 100)

port = PortSelector().run_with_progress(init_task=my_init)
```

### 🚀 단독 실행

```bash
python port_selector.py
```
> 시스템 포트를 콘솔에 나열 → 선택 UI 표시 → 진행바 데모까지 자동 진행

---

## 📦 모듈 2 · `robot_controller.py`

> 휴머노이드 패킷 전송 + 동작 시퀀스 관리. **두 클래스**로 분리되어 있습니다.

### 🦾 `HumanoidRobot` — 시리얼 연결 + 패킷 전송

```python
from robot_controller import HumanoidRobot

# 컨텍스트 매니저로 안전하게 사용
with HumanoidRobot("COM3", 115200) as robot:
    robot.send_motion(19)              # 모션 19번 전송

# 패킷만 미리 만들어서 검증
pkt = HumanoidRobot.build_packet(18)
print(' '.join(f'{b:02X}' for b in pkt))
# → FF FF 4C 53 00 00 00 00 30 0C 03 12 00 64 B5
```

### 🎬 `MotionSequencer` — 비차단 시퀀스 관리

자동 복귀 로직을 `MotionSequencer`가 알아서 처리합니다. **블로킹 sleep 없음.**

```python
from robot_controller import HumanoidRobot, MotionSequencer

robot = HumanoidRobot("COM3"); robot.connect()
seq = MotionSequencer(
    robot,
    return_motion=1,        # 복귀할 기본 자세
    action_hold_sec=7,      # 메인 동작 유지 시간
    return_hold_sec=3,      # 복귀 후 재감지까지 대기
)

while True:
    if some_event:
        seq.trigger(19)            # 시퀀스 시작 (busy면 자동 무시)

    seq.update()                   # 매 프레임 호출 → 타이머 진행
    print(seq.status_message)      # HUD용 한글 메시지
    if seq.is_busy: ...            # 외부 로직에서 상태 조회 가능
```

### 🔄 시퀀스 상태 머신

```
                         trigger(N)
        ┌─────────────────────────────────────┐
        │                                     ↓
   ┌─────────┐    7초 경과    ┌─────────────────────┐
   │  IDLE   │  ←─────────    │   ACTION (모션 N)   │
   │ (감지)  │                └──────────┬──────────┘
   └─────────┘                           │ send_motion(1)
        ↑                                ↓
        │     3초 경과       ┌─────────────────────┐
        └────────────────    │  RETURN (기본자세)  │
                             └─────────────────────┘
```

### 🚀 단독 실행

```bash
python robot_controller.py
```
> 모션 1/17/18/19/20번 패킷을 16진수로 출력 → 포트 선택 시 실제 모션 19 발사 + 복귀 시퀀스 실행

---

## 🚀 메인 실행 파일 · `main.py`

두 모듈을 `import`만 해서 YOLOv5와 결합한 얇은 레이어.

### 🎯 객체 → 모션 매핑 (수정 포인트)

```python
LABEL_TO_MOTION = {
    "person":     19,   # 👤 사람       → 인사
    "bottle":     18,   # 🍾 병         → 손흔들기
    "cell phone": 20,   # 📱 휴대폰     → 사용자 정의 20번
    # 자유롭게 추가:
    # "cup":      21,
    # "book":     22,
    # "laptop":   23,
}
```

> 🎓 **TIP**: YOLOv5는 [COCO 80 클래스](https://github.com/ultralytics/yolov5/blob/master/data/coco.yaml)를 인식합니다.
> 클래스 이름을 키로 두고 모션 번호만 매핑하면 끝.

### ⚙️ 주요 설정 옵션

| 변수 | 설명 | 기본값 |
|:-----|:----|:------:|
| `CONF_THRESHOLD` | 객체 인식 신뢰도 임계값 | `0.60` |
| `RETURN_MOTION` | 동작 후 복귀할 모션 번호 | `1` |
| `ACTION_HOLD_SEC` | 메인 동작 유지 시간(초) | `7` |
| `RETURN_HOLD_SEC` | 복귀 후 재감지까지 대기(초) | `3` |
| `BAUDRATE` | 시리얼 통신 속도 | `115200` |

### 🔁 동작 흐름

```
[1] 포트 선택 UI                      ← port_selector.PortSelector
        ↓
[2] YOLOv5 로드 + 카메라 활성화        ← run_with_progress의 init_task
        ↓
[3] 메인 루프 시작
        │
        ├─ YOLOv5 추론 ─→ 라벨 + 신뢰도 추출
        │                       ↓
        ├─ LABEL_TO_MOTION에 매핑된 객체인가?
        │       Yes  ──→  sequencer.trigger(N)   ← MotionSequencer
        │                                                 │
        │                                                 ↓
        │                                       [모션 N 패킷 전송]
        │                                                 ↓
        │                                          [7초 자동 대기]
        │                                                 ↓
        │                                       [모션 1 (복귀) 전송]
        │                                                 ↓
        │                                          [3초 자동 대기]
        │                                                 ↓
        └──────────────────────────────────  IDLE 복귀 (재감지 가능)
```

---

## 🛠️ 설치 가이드

### 1️⃣ 가상환경 생성 (Python 3.11 권장)

```bash
conda create -n yolo_robot python=3.11 -y
conda activate yolo_robot
```

### 2️⃣ YOLOv5 클론 및 의존성 설치

```bash
git clone https://github.com/ultralytics/yolov5.git
pip install -r yolov5/requirements.txt
```

### 3️⃣ 본 프로젝트 추가 의존성

```bash
pip install -r requirements.txt
```

> 🐧 **Linux 사용자**: tkinter가 기본 포함되지 않을 수 있습니다.
> ```bash
> sudo apt install python3-tk
> ```

---

## ▶️ 실행 방법

### 통합 실행 (권장)

```bash
python main.py
```

### 모듈 단독 실행 (디버깅 / 테스트용)

```bash
python port_selector.py        # 포트 선택 UI 데모
python robot_controller.py     # 패킷 빌드 + 모션 전송 데모
```

### 🎮 단축키

| 키 | 동작 |
|:--:|:----|
| `q` | 프로그램 종료 |
| `ESC` | 프로그램 종료 |

---

## 📡 하드웨어 통신 규격

`robotControlWithTM`의 패킷 규격을 그대로 따릅니다.

| 항목 | 값 |
|:----|:---|
| **Baudrate** | `115200 bps` |
| **패킷 크기** | `15 bytes` |
| **헤더** | `0xFF 0xFF 0x4C 0x53` |
| **모션 인덱스** | `byte[11]` |
| **체크섬** | `byte[6] ~ byte[13]` 합산 후 `& 0xFF` → `byte[14]` |

### 패킷 예시 (모션 19번)

```
┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
│ FF │ FF │ 4C │ 53 │ 00 │ 00 │ 00 │ 00 │ 30 │ 0C │ 03 │ 13 │ 00 │ 64 │ B6 │
├────┴────┴────┴────┼────┴────┴────┴────┼────┴────┼────┼────┼────┼────┤
│      Header       │    Reserved       │  Cmd    │ M  │  R │ S  │CRC │
└───────────────────┴───────────────────┴─────────┴────┴────┴────┴────┘
                                                  └─ 19 (0x13)
```

---

## 💡 다른 프로젝트에서 재사용하기

YOLOv5와 무관하게 **두 모듈만으로** 로봇을 제어할 수 있습니다.

### 예시 1 · 키보드로 로봇 조종

```python
from port_selector import PortSelector
from robot_controller import HumanoidRobot, MotionSequencer

port = PortSelector(baudrate=115200).run()
robot = HumanoidRobot(port); robot.connect()
seq = MotionSequencer(robot)

while True:
    cmd = input("모션 번호? ")
    if cmd.isdigit():
        seq.trigger(int(cmd))
    seq.update()
```

### 예시 2 · 음성 인식과 결합

```python
import speech_recognition as sr
from port_selector import PortSelector
from robot_controller import HumanoidRobot, MotionSequencer

VOICE_TO_MOTION = {"인사": 19, "손 흔들어": 18, "춤": 20}

port = PortSelector().run()
with HumanoidRobot(port) as robot:
    seq = MotionSequencer(robot)
    r = sr.Recognizer()
    while True:
        with sr.Microphone() as src:
            text = r.recognize_google(r.listen(src), language="ko-KR")
            for word, motion in VOICE_TO_MOTION.items():
                if word in text:
                    seq.trigger(motion)
                    break
        seq.update()
```

---

## 🔧 트러블슈팅

<details>
<summary><b>❌ 카메라가 인식되지 않을 때</b></summary>

```python
# main.py 안에서 카메라 인덱스 변경
ctx.camera = cv2.VideoCapture(0)   # 0, 1, 2 등 다른 번호 시도
```
</details>

<details>
<summary><b>❌ <code>PermissionError</code> — 시리얼 포트 점유 중</b></summary>

다른 프로그램(아두이노 IDE 시리얼 모니터, PuTTY 등)이 같은 COM 포트를 잡고 있는 경우입니다.
해당 프로그램을 종료한 뒤 다시 실행하세요.
</details>

<details>
<summary><b>❌ YOLOv5 모델 로드 실패</b></summary>

`yolov5/` 폴더가 프로젝트 루트에 있는지 확인:
```bash
ls yolov5/hubconf.py    # 이 파일이 보여야 정상
```
없다면 `git clone https://github.com/ultralytics/yolov5.git` 다시 실행.
</details>

<details>
<summary><b>❌ Linux에서 <code>ModuleNotFoundError: tkinter</code></b></summary>

```bash
sudo apt install python3-tk
```
</details>

<details>
<summary><b>⚡ 성능이 느릴 때</b></summary>

- YOLOv5 모델을 더 가볍게: `yolov5s` → `yolov5n`
- 카메라 해상도 낮추기: `cv2.CAP_PROP_FRAME_WIDTH/HEIGHT`
- 프레임 스킵 추가 (몇 프레임마다 한 번씩만 추론)
</details>

---

## 📚 참고 자료

- 🔗 [YOLOv5 공식 저장소](https://github.com/ultralytics/yolov5)
- 🔗 [yolov5ReadTime — 원본](https://github.com/EmmettHwang/yolov5ReadTime)
- 🔗 [robotControlWithTM — 원본](https://github.com/EmmettHwang/robotControlWithTM)
- 🔗 [PySerial 문서](https://pyserial.readthedocs.io/)
- 🔗 [OpenCV-Python 문서](https://docs.opencv.org/)

---

## 📝 라이선스

본 프로젝트는 YOLOv5의 **AGPL-3.0** 라이선스를 따릅니다.

---

<div align="center">

**🌟 만든이** · [@EmmettHwang](https://github.com/EmmettHwang)

*"AI의 눈으로 보고, 로봇의 몸으로 반응한다."*

</div>
