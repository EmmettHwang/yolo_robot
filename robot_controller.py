# coding: utf-8
"""
robot_controller.py
===================
휴머노이드 로봇 모션 제어 모듈.

robotControlWithTM 의 패킷 규격을 그대로 사용:
  - Baudrate     : 115200 bps (기본값)
  - Packet size  : 15 bytes
  - Header       : 0xFF 0xFF 0x4C 0x53
  - Motion index : byte[11]
  - Checksum     : byte[6]~byte[13] 합산 후 & 0xFF → byte[14]

크게 두 가지 클래스를 제공:

1) HumanoidRobot
   - 가장 단순한 래퍼. 시리얼 포트를 열고 send_motion(N) 으로 패킷 전송.

2) MotionSequencer
   - "메인 동작 → N초 대기 → 기본 자세 복귀 → M초 대기 → 다시 감지"
     같은 시퀀스 상태를 관리해주는 헬퍼. 비차단(non-blocking) 방식.

사용 예 (다른 코드에서 import 해서 쓸 때):

    from robot_controller import HumanoidRobot, MotionSequencer

    robot = HumanoidRobot("COM3", 115200)
    robot.connect()

    sequencer = MotionSequencer(robot, return_motion=1,
                                action_hold_sec=7, return_hold_sec=3)

    # 메인 루프 안에서:
    if some_event:
        sequencer.trigger(19)        # 모션 19 발사 (시퀀스 시작)

    sequencer.update()                # 매 프레임마다 호출 → 자동 복귀 처리
    print(sequencer.status_message)   # 화면 표시용

이 파일을 직접 실행하면 (python robot_controller.py) 콘솔에서
포트 선택 → 모션 번호 입력 → 전송하는 인터랙티브 데모가 동작합니다.
"""

import time
from typing import Optional

import serial


# ============================================================
# 1. HumanoidRobot : 시리얼 연결 + 패킷 전송
# ============================================================
class HumanoidRobot:
    """휴머노이드 로봇 시리얼 제어 래퍼.

    Parameters
    ----------
    port : str
        시리얼 포트 이름 (예: 'COM3', '/dev/ttyUSB0').
    baudrate : int
        통신 속도. 기본 115200.
    timeout : float
        시리얼 read timeout (sec).
    """

    PACKET_SIZE = 15
    HEADER = [0xFF, 0xFF, 0x4C, 0x53]

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0,
                 write_timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        # write_timeout: 블루투스 등에서 무선 링크가 끊기면 write가 영원히
        # 멈출 수 있다. 타임아웃을 줘서 무한 대기를 막는다.
        self.write_timeout = write_timeout
        self.ser: Optional[serial.Serial] = None

    # ---------- 연결 / 해제 ----------
    def connect(self) -> None:
        """시리얼 포트를 연다. 이미 열려 있으면 무시."""
        if self.ser is not None and self.ser.is_open:
            return
        self.ser = serial.Serial(
            self.port, self.baudrate,
            timeout=self.timeout, write_timeout=self.write_timeout,
        )

    def close(self) -> None:
        """포트를 안전하게 닫는다."""
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
        self.ser = None

    @property
    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def ping(self) -> bool:
        """포트가 살아있는지 가볍게 확인. 끊겼으면 정리 후 False.

        블루투스 로봇이 꺼지거나 범위를 벗어나면 포트 접근 시 예외가 난다.
        모션을 보내지 않고도 연결 상태를 주기적으로 점검할 수 있다.
        """
        if not self.is_connected:
            return False
        try:
            _ = self.ser.in_waiting      # 끊긴 포트면 예외 발생
            return True
        except Exception:
            self.close()
            return False

    # ---------- 패킷 ----------
    @classmethod
    def build_packet(cls, motion_index: int) -> bytearray:
        """모션 인덱스를 받아 15바이트 패킷(체크섬 포함)을 생성한다."""
        if not (0 <= motion_index <= 0xFF):
            raise ValueError(f"motion_index 범위 오류: {motion_index} (0~255)")

        packet = [
            0xFF, 0xFF, 0x4C, 0x53, 0x00, 0x00, 0x00, 0x00,
            0x30, 0x0C, 0x03, motion_index, 0x00, 100, 0x00,
        ]
        # checksum: byte[6]~byte[13] 합산
        chk = 0
        for i in range(6, 14):
            chk = (chk + packet[i]) & 0xFF
        packet[14] = chk
        return bytearray(packet)

    # ---------- 전송 ----------
    def send_motion(self, motion_index: int) -> bool:
        """주어진 모션 인덱스를 실행하는 패킷을 전송한다.
        성공 시 True, 포트가 닫혀 있어 못 보낸 경우 False."""
        if not self.is_connected:
            return False
        packet = self.build_packet(motion_index)
        try:
            self.ser.write(packet)
            self.ser.flush()
        except Exception:
            # write_timeout 초과/무선 링크 끊김 → 무한 대기 대신 포트 정리 후 실패
            self.close()
            return False
        return True

    # ---------- 컨텍스트 매니저 ----------
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ============================================================
# 2. MotionSequencer : 비차단 시퀀스 관리
# ============================================================
class MotionSequencer:
    """메인 동작 → 일정 시간 대기 → 기본 자세 복귀 → 일정 시간 대기 → 재감지
    구조를 비차단(non-blocking) 방식으로 관리하는 헬퍼.

    메인 루프에서 매 프레임 update() 를 호출하면, 내부 타이머에 따라
    자동으로 복귀 패킷을 보내고 상태를 갱신한다.

    Parameters
    ----------
    robot : HumanoidRobot
        실제 패킷 전송을 담당하는 로봇 객체.
    return_motion : int
        메인 동작 후 복귀할 기본 자세 모션 번호. 기본 1번.
    action_hold_sec : float
        메인 동작 유지 시간(초).
    return_hold_sec : float
        복귀 후 재감지까지 대기 시간(초).
    """

    # 내부 상태
    STATE_IDLE = 0       # 감지/명령 대기
    STATE_ACTION = 1     # 메인 모션 실행 중
    STATE_RETURN = 2     # 복귀 모션 실행 중

    def __init__(
        self,
        robot: HumanoidRobot,
        return_motion: int = 1,
        action_hold_sec: float = 7.0,
        return_hold_sec: float = 3.0,
    ):
        self.robot = robot
        self.return_motion = return_motion
        self.action_hold_sec = action_hold_sec
        self.return_hold_sec = return_hold_sec

        self._state = self.STATE_IDLE
        self._t0 = 0.0
        self._current_motion = 0

    # ---------- 외부에서 보는 상태 ----------
    @property
    def is_busy(self) -> bool:
        """현재 시퀀스를 실행 중인지 (= 새 trigger를 받지 않아야 하는지)."""
        return self._state != self.STATE_IDLE

    @property
    def status_message(self) -> str:
        """HUD/콘솔에 띄우기 좋은 한글 상태 문자열."""
        now = time.time()
        if self._state == self.STATE_IDLE:
            return "상태: 감지 중"
        if self._state == self.STATE_ACTION:
            remain = max(0, int(self.action_hold_sec - (now - self._t0)))
            return f"동작 중({self._current_motion}번)... {remain}초 뒤 복귀"
        if self._state == self.STATE_RETURN:
            remain = max(0, int(self.return_hold_sec - (now - self._t0)))
            return f"복귀 중({self.return_motion}번)... {remain}초 뒤 감지"
        return ""

    # ---------- 트리거 / 업데이트 ----------
    def trigger(self, motion_index: int) -> bool:
        """새 모션을 발사한다. 시퀀스 진행 중이면 무시하고 False 반환."""
        if self.is_busy:
            return False
        ok = self.robot.send_motion(motion_index)
        if not ok:
            return False
        self._current_motion = motion_index
        self._state = self.STATE_ACTION
        self._t0 = time.time()
        return True

    def update(self) -> None:
        """메인 루프에서 매 프레임 호출. 타이머에 따라 복귀 패킷을 자동 전송한다."""
        now = time.time()
        if self._state == self.STATE_ACTION:
            if (now - self._t0) >= self.action_hold_sec:
                self.robot.send_motion(self.return_motion)
                self._state = self.STATE_RETURN
                self._t0 = time.time()
        elif self._state == self.STATE_RETURN:
            if (now - self._t0) >= self.return_hold_sec:
                self._state = self.STATE_IDLE
                self._current_motion = 0

    def reset(self) -> None:
        """강제로 IDLE 상태로 되돌린다 (포트 끊김 등 비상 시)."""
        self._state = self.STATE_IDLE
        self._current_motion = 0


# ============================================================
# 단독 실행 데모
# ============================================================
if __name__ == "__main__":
    import serial.tools.list_ports

    print("[robot_controller] 단독 실행 데모")
    print("[robot_controller] 사용 가능한 포트:")
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("  (감지된 포트가 없습니다. 데모는 가짜 패킷 출력만 진행합니다.)")
    else:
        for i, p in enumerate(ports):
            print(f"  [{i}] {p.device} : {p.description}")

    # 1) 패킷 빌드 결과 미리보기 (포트 없어도 되는 부분)
    print("\n[robot_controller] 패킷 빌드 예시:")
    for m in (1, 17, 18, 19, 20):
        pkt = HumanoidRobot.build_packet(m)
        print(f"  motion {m:3d} → {' '.join(f'{b:02X}' for b in pkt)}")

    # 2) 실제 포트가 있으면 인터랙티브 전송 데모
    if ports:
        try:
            sel = input(
                "\n전송 데모를 진행할 포트 번호를 입력 (Enter 누르면 건너뜀): "
            ).strip()
        except EOFError:
            sel = ""
        if sel.isdigit() and 0 <= int(sel) < len(ports):
            chosen = ports[int(sel)].device
            print(f"[robot_controller] {chosen} 연결 시도...")
            with HumanoidRobot(chosen, 115200) as robot:
                seq = MotionSequencer(
                    robot, return_motion=1,
                    action_hold_sec=3, return_hold_sec=2,  # 데모용으로 짧게
                )

                # 모션 19 발사 후 시퀀스가 끝날 때까지 update 루프
                print("[robot_controller] 모션 19 발사 → 자동 복귀 시퀀스 시작")
                seq.trigger(19)
                while seq.is_busy:
                    seq.update()
                    print(f"  {seq.status_message}", end="\r")
                    time.sleep(0.2)
                print("\n[robot_controller] 시퀀스 완료.")
        else:
            print("[robot_controller] 전송 데모 건너뜀.")
    print("[robot_controller] 데모 종료.")
