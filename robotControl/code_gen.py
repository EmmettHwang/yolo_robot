# coding: utf-8
"""
code_gen.py
===========
인식및반응 매핑(object_actions JSON) → 읽기 좋은 파이썬 코드 생성.

블록코딩 ③-③ '파이썬 코드' 탭에서 보여 주는 용도(읽기 전용).
표 코딩 / 블록 코딩과 **같은 데이터**(steps: motion/sound/duration/repeat/cond)
를 그대로 코드 형태로 펼쳐 보여 준다.

생성 코드는 설명용이며, 실제 실행 엔진(MotionRunner)과 1:1로 대응한다:
  robot.motion(n) · robot.power_on()/power_off() · robot.voice_chat()
  sound.play_mp3(...) · sound.speak(...) · sound.play_random()
  wait(sec)
"""

import os

from motion_table import motion_name, coco_kr, PWR_ON, PWR_OFF, VOICE_CHAT
import sound as snd
import object_actions

# ❓ 조건 키 → (파이썬 식, 주석)
_COND_PY = {
    "always": (None, None),
    "conf90": ("conf >= 0.90", "신뢰도 90%↑"),
    "conf70": ("conf >= 0.70", "신뢰도 70%↑"),
    "rand50": ("random() < 0.50", "확률 50%"),
    "rand30": ("random() < 0.30", "확률 30%"),
    "count2": ("count >= 2", "같은 객체 2개↑"),
    "count3": ("count >= 3", "같은 객체 3개↑"),
    "day": ("6 <= hour() < 18", "낮(06–18시)"),
    "night": ("not (6 <= hour() < 18)", "밤(18–06시)"),
}

_HEADER = '''# -*- coding: utf-8 -*-
# ════════════════════════════════════════════════════════════════
#  자동 생성된 반응 프로그램   (인식및반응설정 → 표 / 블록 코딩에서 생성)
#  이 코드는 "보기 전용"입니다 — 표나 블록을 바꾸면 자동으로 다시 생성됩니다.
# ════════════════════════════════════════════════════════════════
#  robot.motion(n)      n번 모션 실행          sound.speak("말")   읽어 주기(TTS)
#  robot.power_on()     전원 켜기(일어서기)     sound.play_mp3(...) mp3 재생
#  robot.power_off()    전원 끄기(앉기)         sound.play_random() 랜덤 로봇음
#  robot.voice_chat()   음성 대화              wait(초)            잠시 대기


def on_detect(label, conf, count):
    """객체를 인식할 때마다 호출 — label(이름) · conf(신뢰도) · count(같은 객체 수)."""
'''


def _motion_call(motion):
    """모션 번호 → robot.* 호출 코드 + 주석."""
    if motion == PWR_ON:
        return "robot.power_on()", "전원 켜기"
    if motion == PWR_OFF:
        return "robot.power_off()", "전원 끄기"
    if motion == VOICE_CHAT:
        return "robot.voice_chat()", "음성 대화"
    return f"robot.motion({motion})", motion_name(int(motion))


def _sound_call(kind, value):
    """사운드 종류/값 → sound.* 호출 코드(없으면 None)."""
    if kind == snd.MP3 and value:
        return f'sound.play_mp3("{os.path.basename(value)}")'
    if kind == snd.TTS and value:
        safe = value.replace('\\', '\\\\').replace('"', '\\"')
        return f'sound.speak("{safe}")'
    if kind == snd.RANDOM:
        return "sound.play_random()"
    return None


def _emit_step(step, indent):
    """스텝 1개 → 코드 줄 리스트(조건 if + 반복 for 포함)."""
    pad = "    " * indent
    body = []          # 조건/반복 안쪽에 들어갈 실제 동작 줄
    motion = step.get("motion")
    if motion:
        call, cmt = _motion_call(int(motion))
        body.append((call, cmt))
    scall = _sound_call(step.get("sound_kind", snd.NONE),
                        step.get("sound_value", ""))
    if scall:
        body.append((scall, None))
    dur = step.get("duration")
    if dur:
        body.append((f"wait({_fmt_num(dur)})", None))
    if not body:
        return []

    # 반복(🔁) → for 래퍼
    rep = int(step.get("repeat", 1) or 1)
    inner_indent = indent
    wrappers = []
    cond = step.get("cond", "always")
    expr, ccmt = _COND_PY.get(cond, (None, None))
    if expr:
        wrappers.append((f"if {expr}:", ccmt))
        inner_indent += 1
    if rep > 1:
        wrappers.append((f"for _ in range({rep}):", "🔁 반복"))
        inner_indent += 1

    lines = []
    cur = indent
    for text, cmt in wrappers:
        p = "    " * cur
        lines.append(f"{p}{text}" + (f"   # {cmt}" if cmt else ""))
        cur += 1
    bp = "    " * inner_indent
    for call, cmt in body:
        lines.append(f"{bp}{call}" + (f"   # {cmt}" if cmt else ""))
    return lines


def _fmt_num(n):
    f = float(n)
    return str(int(f)) if f == int(f) else str(f)


def generate_python(mapping=None) -> str:
    """매핑 전체 → 파이썬 소스 문자열."""
    if mapping is None:
        mapping = object_actions.load_actions()
    out = [_HEADER.rstrip("\n")]
    if not mapping:
        out.append("    pass    # 아직 등록된 반응이 없습니다.")
        return "\n".join(out) + "\n"

    first = True
    for label, act in mapping.items():
        steps = object_actions.steps_of(act)
        if not steps:
            continue
        kr = coco_kr(label)
        cmt = f"   # {kr}" if kr else ""
        kw = "if" if first else "elif"
        first = False
        out.append("")
        out.append(f'    {kw} label == "{label}":{cmt}')
        emitted = False
        for st in steps:
            for ln in _emit_step(st, indent=2):
                out.append(ln)
                emitted = True
        if not emitted:
            out.append("        pass")
    if first:        # 유효한 스텝이 하나도 없었음
        out.append("    pass    # 아직 등록된 반응이 없습니다.")
    return "\n".join(out) + "\n"
