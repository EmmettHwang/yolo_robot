# coding: utf-8
"""
motion_table.py
===============
로봇 모션 번호 ↔ 이름 테이블. (assets/모션테이블_라인코어스마트_2021.pdf 기준)

연속 동작:
  - 전진(Forward) : 2 → 3 → 4 반복
  - 후진(Backward): 9 → 10 → 11 반복
  각 모션 사이 500ms 딜레이.
"""

# 단일 모션 번호 → 표시 이름
MOTION_NAMES = {
    1: "Ready(기본자세)",
    2: "Forward ST", 3: "Forward Loop", 4: "Forward End",
    5: "Go Left(좌)", 6: "Go Right(우)",
    7: "Turn Left(좌회전)", 8: "Turn Right(우회전)",
    9: "Backward ST", 10: "Backward End", 11: "Backward Loop",
    12: "Left Forward(전진좌)", 13: "Right Forward(전진우)",
    14: "Getup F(앞기상)", 15: "Getup B(뒤기상)",
    16: "Lose(패배)", 17: "Win(승리)", 18: "Hi(인사)", 19: "Bow(절)",
    20: "Tumble F(앞구르기)", 21: "Tumble B(뒤구르기)",
    22: "Attack Ready", 23: "Defense", 24: "Fight Forward",
    25: "Fight Backward", 26: "Fight Left", 27: "Fight Right",
    28: "Fight Turn L", 29: "Fight Turn R",
    30: "Zap", 31: "Left Hook", 32: "Left Upper", 33: "Strait",
    34: "Right Hook", 35: "Right Upper", 36: "One-Two",
    37: "Fight Getup F", 38: "Fight Getup B",
    55: "Grip(잡기)", 56: "Laydown(놓기)",
    60: "Safe Sit", 61: "Safe Up",
    63: "오늘부터우리는-여자친구", 65: "블락비", 67: "트와이스-걸그룹",
    68: "Swing Head", 69: "Look Left", 70: "Look Right",
    71: "Push L Hand", 72: "Push R Hand", 73: "Twist", 74: "Foot Up",
}

# 연속(반복) 동작 시퀀스 — 실행 순서는 ST → Loop → End
#   전진 F: 2=ST, 3=Loop, 4=End  → [2, 3, 4]
#   후진 B: 9=ST, 11=Loop, 10=End → [9, 11, 10]
#     (후진은 번호순서가 ST,End,Loop라 [9,10,11]로 보내면 중간 End가 끼어 끊긴다)
FORWARD_SEQUENCE = [2, 3, 4]        # 전진 (ST→Loop→End)
BACKWARD_SEQUENCE = [9, 11, 10]     # 후진 (ST→Loop→End)
SEQUENCE_DELAY_MS = 200             # 동작 사이 딜레이

# 기본 자세
READY_MOTION = 1

# 안전 전원 시퀀스
SAFE_SIT = 60          # 전원 끄기 전 앉기
SAFE_UP = 61           # 전원 켠 뒤 일어서기
POWER_OFF_HOLD = 7.0   # Safe Sit 후 전원 끄기까지 대기(초)

# 인식 반응/드롭다운용 가상 코드(실제 모션 번호 아님) — 전원 시퀀스를 모션처럼 선택
PWR_ON = 1001          # 전원 켜기(전원 ON → 일어서기)
PWR_OFF = 1002         # 전원 끄기(앉기 → 7초 → 전원 OFF)
PWR_LABELS = {PWR_ON: "전원 켜기", PWR_OFF: "전원 끄기"}


def motion_name(idx: int) -> str:
    if idx in PWR_LABELS:
        return PWR_LABELS[idx]
    return MOTION_NAMES.get(idx, f"Motion {idx}")


def motion_label(idx: int) -> str:
    """드롭다운 표시용 'N - 이름'."""
    return f"{idx} - {motion_name(idx)}"


# 드롭다운용 전체 모션 목록(번호 오름차순)
ALL_MOTIONS = sorted(MOTION_NAMES.keys())


# ============================================================
# COCO 80 클래스 (기본 yolov5s 모델 class 이름) — 객체 반응 드롭다운용
# ============================================================
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag",
    "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]

# COCO 클래스 한글 번역
COCO_KR = {
    "person": "사람", "bicycle": "자전거", "car": "자동차",
    "motorcycle": "오토바이", "airplane": "비행기", "bus": "버스",
    "train": "기차", "truck": "트럭", "boat": "보트",
    "traffic light": "신호등", "fire hydrant": "소화전", "stop sign": "정지표지판",
    "parking meter": "주차미터기", "bench": "벤치", "bird": "새", "cat": "고양이",
    "dog": "개", "horse": "말", "sheep": "양", "cow": "소", "elephant": "코끼리",
    "bear": "곰", "zebra": "얼룩말", "giraffe": "기린", "backpack": "배낭",
    "umbrella": "우산", "handbag": "핸드백", "tie": "넥타이", "suitcase": "여행가방",
    "frisbee": "프리스비", "skis": "스키", "snowboard": "스노보드",
    "sports ball": "공", "kite": "연", "baseball bat": "야구방망이",
    "baseball glove": "야구글러브", "skateboard": "스케이트보드",
    "surfboard": "서핑보드", "tennis racket": "테니스라켓", "bottle": "병",
    "wine glass": "와인잔", "cup": "컵", "fork": "포크", "knife": "칼",
    "spoon": "숟가락", "bowl": "그릇", "banana": "바나나", "apple": "사과",
    "sandwich": "샌드위치", "orange": "오렌지", "broccoli": "브로콜리",
    "carrot": "당근", "hot dog": "핫도그", "pizza": "피자", "donut": "도넛",
    "cake": "케이크", "chair": "의자", "couch": "소파", "potted plant": "화분",
    "bed": "침대", "dining table": "식탁", "toilet": "변기", "tv": "TV",
    "laptop": "노트북", "mouse": "마우스", "remote": "리모컨", "keyboard": "키보드",
    "cell phone": "휴대폰", "microwave": "전자레인지", "oven": "오븐",
    "toaster": "토스터", "sink": "싱크대", "refrigerator": "냉장고", "book": "책",
    "clock": "시계", "vase": "꽃병", "scissors": "가위", "teddy bear": "곰인형",
    "hair drier": "헤어드라이어", "toothbrush": "칫솔",
}


def coco_kr(name: str) -> str:
    return COCO_KR.get(name, "")
