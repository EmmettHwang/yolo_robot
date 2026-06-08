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
    55: "Grip(잡기)", 56: "Laydown(눕기)",
    60: "Safe Sit", 61: "Safe Up",
    63: "Dance KPop", 65: "Dance Boy", 67: "Dance Girl",
    68: "Swing Head", 69: "Look Left", 70: "Look Right",
    71: "Push L Hand", 72: "Push R Hand", 73: "Twist", 74: "Foot Up",
}

# 연속(반복) 동작 시퀀스
FORWARD_SEQUENCE = [2, 3, 4]        # 전진
BACKWARD_SEQUENCE = [9, 10, 11]     # 후진
SEQUENCE_DELAY_MS = 500             # 동작 사이 딜레이

# 기본 자세
READY_MOTION = 1


def motion_name(idx: int) -> str:
    return MOTION_NAMES.get(idx, f"Motion {idx}")
