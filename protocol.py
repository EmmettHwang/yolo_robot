# coding: utf-8
"""
protocol.py
===========
라인코어 스마트 LSC 프로토콜 패킷 빌더.
(assets/Protocols_1_3_7_2021_1007_라인코어스마트.pdf 기준)

패킷 구조:
  Header(4)        : FF FF 4C 53
  Dest Addr(2)     : 컨트롤러 주소 (브로드캐스트 = 00 00)
  Src Addr(2)      : 호스트 주소 (00 00)
  Statement(2)     : Type, Code
  Para Length(1)   : N
  Parameters(N)
  CheckSum(1)      : (SrcH + SrcL + Type + Code + Length + ΣPara) & 0xFF

Type:  0x10 GET / 0x20 SET / 0x30 EXECUTION / 0x40 Files
EXE Code: 1 PWR ON/OFF, 3 PosMove(Torq), 4 PosMove(Speed), 5 LED, 12 Motion
"""

import struct

HEADER = [0xFF, 0xFF, 0x4C, 0x53]

TYPE_GET = 0x10
TYPE_SET = 0x20
TYPE_EXE = 0x30
TYPE_FILE = 0x40

EXE_PWR = 1
EXE_POSMOVE_TORQ = 3
EXE_POSMOVE_SPEED = 4
EXE_LED = 5
EXE_MOTION = 12      # 0x0C

GET_NOWPOS = 5       # DATA GET: Get LSMs NowPosition


def build(type_, code, para, src=(0, 0), dest=(0, 0)) -> bytearray:
    """공통 패킷 빌드 + 체크섬."""
    para = [int(p) & 0xFF for p in para]
    length = len(para)
    chk = (src[0] + src[1] + type_ + code + length + sum(para)) & 0xFF
    body = [dest[0], dest[1], src[0], src[1], type_, code, length] + para
    return bytearray(HEADER + body + [chk])


# ---------- EXECUTION 패킷들 ----------
def motion(motion_number, start_delay=0, speed=100) -> bytearray:
    """Exe Motion: para = [모션번호, 시작지연(ms), 속도(%)]."""
    return build(TYPE_EXE, EXE_MOTION,
                 [motion_number & 0xFF, start_delay & 0xFF, speed & 0xFF])


def led(leds) -> bytearray:
    """Exe LSM LED Control: leds = [(id, r, g, b), ...]  → para = id,R,G,B × N."""
    para = []
    for jid, r, g, b in leds:
        para += [jid & 0xFF, r & 0xFF, g & 0xFF, b & 0xFF]
    return build(TYPE_EXE, EXE_LED, para)


def position(positions) -> bytearray:
    """Exe LSM PosMove(Torq): positions = [(id, pos_signed16, torque%), ...]
    → para = id, Torque, PosH, PosL × N. (위치는 부호있는 16비트)"""
    para = []
    for jid, pos, torque in positions:
        pos = max(-32768, min(32767, int(pos)))
        h, l = struct.pack(">h", pos)
        para += [jid & 0xFF, torque & 0xFF, h, l]
    return build(TYPE_EXE, EXE_POSMOVE_TORQ, para)


def power(on: bool) -> bytearray:
    """Exe LSM PWR ON/OFF: para = [0/1]."""
    return build(TYPE_EXE, EXE_PWR, [1 if on else 0])


# ---------- DATA GET ----------
def get_positions(ids) -> bytearray:
    """Get LSMs NowPosition 요청: para = [id1, id2, ...]."""
    return build(TYPE_GET, GET_NOWPOS, list(ids))


def parse_positions(data: bytes) -> dict:
    """응답 패킷에서 {id: 위치(signed16)} 추출. para = id,PosH,PosL × N."""
    res = {}
    if not data:
        return res
    i = data.find(b"\xff\xff\x4c\x53")
    if i < 0 or len(data) - i < 12:
        return res
    pkt = data[i:]
    length = pkt[10]
    para = pkt[11:11 + length]
    for j in range(0, len(para) - 2, 3):
        jid = para[j]
        pos = struct.unpack(">h", bytes(para[j + 1:j + 3]))[0]
        res[jid] = pos
    return res
