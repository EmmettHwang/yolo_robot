# coding: utf-8
"""
main.py
=======
진입점. 실제 모듈들은 robot/ 폴더에 있고, 여기서 경로를 추가해 실행한다.

구조:
  main.py            - 진입점(루트)
  robot/             - 기능 모듈 모음
    app.py             탭 메인 윈도우
    port_selector.py   포트/장치 설정 (독립 실행)
    trainer.py         로봇 학습 (독립 실행)
    recognition_view.py 인식 화면
    robot_control_panel.py LED/포지션/전원 제어
    object_actions.py / motion.py / motion_table.py / motor_map.py
    sound.py / joystick.py / motion_grid.py
    protocol.py / robot_controller.py / yolo.py / hangul.py / paths.py
    pdf_viewer.py / manual.py / mp3_library.py / version.py
  model/             - 가중치(yolov5s.pt, active.pt, 학습 결과)
  assets/ dataset/ yolov5/ ...
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "robot"))

from app import App   # noqa: E402  (robot/ 경로 추가 후 import)

if __name__ == "__main__":
    App().run()
