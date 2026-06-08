# coding: utf-8
"""
main.py
=======
진입점. 탭 메인 윈도우(app.App)를 실행한다.

구조는 모듈로 분리되어 있다:
  app.py             - 탭 메인 윈도우
  port_selector.py   - 포트/장치 설정 (독립 실행)
  trainer.py         - 로봇 학습 (독립 실행)
  recognition_view.py- 인식 화면 (카메라+조이스틱+4x4 그리드)
  object_actions.py  - 객체 class -> 동작/사운드 매핑
  motion.py / motion_table.py - 모션 엔진/테이블
  sound.py           - 음성없음/mp3/TTS
  joystick.py / motion_grid.py - 입력 위젯
  yolo.py / hangul.py / paths.py - 모델/한글렌더/경로
"""

from app import App

if __name__ == "__main__":
    App().run()
