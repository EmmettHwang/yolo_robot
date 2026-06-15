# coding: utf-8
"""
port_selector.py
================
Zoom 스타일 장치 선택 UI.

기능:
- 시리얼 포트 자동 검색 + 새로고침
- 카메라 자동 검색 (pygrabber 설치 시 DirectShow 이름) + 라이브 미리보기
- 마이크 자동 검색 + 실시간 입력 레벨(VU) 표시
- 스피커 자동 검색 + 테스트 톤 재생
- 선택값 INI 저장 (다음 실행 시 복원)
- 진행바 모드(run_with_progress)로 후속 초기화까지 한 창에서 처리

사용 예 (다른 코드에서 import 해서 쓸 때):

    from port_selector import PortSelector

    sel = PortSelector(title="내 로봇 초기화", baudrate=115200)
    port = sel.run()                  # 확인 누르면 포트 문자열 반환
    print(sel.selected_camera_index)  # 0, 1, ...
    print(sel.selected_audio_in_name) # "Microphone (Realtek)"

또는 진행바까지 한 번에:

    def my_init(update):
        update("모델 로드 중...", "...", 50)
        ...

    sel = PortSelector()
    port = sel.run_with_progress(init_task=my_init)

추천 패키지 (선택):
    pip install pygrabber       # 카메라 실제 장치 이름 (Windows)
"""

import math
import os
import re
import time
import threading
import subprocess
import configparser
from typing import Callable, List, Optional, Tuple

import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, messagebox

from motion_table import motion_label, motion_name, ALL_MOTIONS
import paths

# ---- Optional dependencies (graceful fallback) ----
try:
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    _HAS_NUMPY = False

try:
    import sounddevice as sd
    _HAS_SD = True
except Exception:
    _HAS_SD = False

try:
    from pygrabber.dshow_graph import FilterGraph
    _HAS_PYGRABBER = True
except Exception:
    _HAS_PYGRABBER = False


# ============================================================
# 장치 검색 유틸
# ============================================================
def list_camera_devices(max_probe: int = 6) -> List[Tuple[int, str]]:
    """현재 시스템에서 사용 가능한 카메라 [(index, name), ...] 목록."""
    # 1) Windows + pygrabber: DirectShow 장치 이름
    if _HAS_PYGRABBER:
        try:
            names = FilterGraph().get_input_devices()
            if names:
                return [(i, n) for i, n in enumerate(names)]
        except Exception:
            pass
    # 2) Fallback: OpenCV로 직접 프로빙
    devices: List[Tuple[int, str]] = []
    if _HAS_CV2:
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else 0
        for i in range(max_probe):
            try:
                cap = cv2.VideoCapture(i, backend)
                if cap is not None and cap.isOpened():
                    devices.append((i, f"Camera {i}"))
                    cap.release()
            except Exception:
                pass
    return devices


try:
    import winreg
    _HAS_WINREG = True
except Exception:
    _HAS_WINREG = False


def bt_device_name(mac12: str) -> Optional[str]:
    """페어링된 블루투스 기기의 친숙한 이름(예: 'FB153 v1.0.0')을 레지스트리에서 조회."""
    if not (_HAS_WINREG and mac12):
        return None
    try:
        path = (r"SYSTEM\CurrentControlSet\Services\BTHPORT"
                r"\Parameters\Devices\%s" % mac12.lower())
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        val, _ = winreg.QueryValueEx(k, "Name")
        winreg.CloseKey(k)
        if isinstance(val, (bytes, bytearray)):
            return (val.split(b"\x00")[0].decode("utf-8", "ignore").strip()
                    or None)
        return str(val).strip() or None
    except Exception:
        return None


def _bt_remote_address(hwid: str) -> Optional[str]:
    """Bluetooth 시리얼 포트 hwid에서 상대 기기 주소(12 hex)를 추출.

    발신(outgoing) 포트는 페어링된 기기의 실제 주소가 들어있고,
    수신(incoming)/로컬 포트는 000000000000 처럼 비어 있다.
    Bluetooth 포트가 아니거나 주소가 없으면 None.
    """
    m = re.search(r"&0&([0-9A-Fa-f]{12})_", hwid or "")
    if not m:
        return None
    return m.group(1).upper()


def list_audio_devices() -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]]]:
    """(inputs, outputs) 형식의 [(index, name), ...] 두 리스트 반환.

    Windows는 같은 물리 장치를 호스트 API(MME/DirectSound/WASAPI/WDM-KS)마다
    중복으로 노출한다. Zoom처럼 깔끔하게 보이도록:
      - WDM-KS(저수준)는 제외
      - 같은 장치는 1개로 합치고, 잘리지 않은 가장 완전한 이름을 채택
    """
    inputs: List[Tuple[int, str]] = []
    outputs: List[Tuple[int, str]] = []
    if not _HAS_SD:
        return inputs, outputs
    try:
        devs = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return inputs, outputs

    def _is_virtual(name: str) -> bool:
        """실제 장치가 아닌 Windows 기본 라우팅용 가상 항목인지."""
        n = name.lower()
        bad = ("sound mapper", "사운드 매퍼",
               "primary sound", "주 사운드")
        return any(b in n for b in bad)

    def _merge(result: List[Tuple[int, str]], idx: int, name: str) -> None:
        n = name.strip()
        nn = n.replace(" ", "").lower()
        for j, (_, rname) in enumerate(result):
            rn = rname.replace(" ", "").lower()
            # MME는 이름을 31자에서 자르므로 prefix 일치도 같은 장치로 본다
            if nn == rn or nn.startswith(rn) or rn.startswith(nn):
                if len(n) > len(rname):     # 더 완전한 이름 + 그 인덱스로 교체
                    result[j] = (idx, n)
                return
        result.append((idx, n))

    try:
        for i, d in enumerate(devs):
            try:
                ha = hostapis[d["hostapi"]]["name"]
            except Exception:
                ha = ""
            if "WDM-KS" in ha:
                continue
            name = d.get("name", f"Device {i}")
            if _is_virtual(name):
                continue
            if d.get("max_input_channels", 0) > 0:
                _merge(inputs, i, name)
            if d.get("max_output_channels", 0) > 0:
                _merge(outputs, i, name)
    except Exception:
        pass
    return inputs, outputs


# ============================================================
# 메인 클래스
# ============================================================
class PortSelector:
    """Zoom-style 시리얼/카메라/오디오 장치 선택 UI."""

    PREVIEW_W = 320
    PREVIEW_H = 180
    PREVIEW_INTERVAL_MS = 33      # ~30 FPS UI 업데이트
    VU_INTERVAL_MS = 60

    def __init__(
        self,
        title: str = "장치 선택",
        baudrate: int = 115200,
        config_file: Optional[str] = None,
        width: int = 600,
        height: int = 980,
    ):
        self.title = title
        self.baudrate = baudrate
        self.width = width
        self.height = height

        if config_file is None:
            config_file = paths.CONFIG_INI
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        lasts = self._load_config()
        self.last_port = lasts["last_port"]
        self.last_camera_index = lasts["last_camera_index"]
        self.last_audio_in_index = lasts["last_audio_in_index"]
        self.last_audio_out_index = lasts["last_audio_out_index"]

        # ---- 결과 (확인 누르면 채워짐) ----
        self.selected_port: Optional[str] = None
        self.selected_camera_index: Optional[int] = None
        self.selected_camera_name: Optional[str] = None
        self.selected_audio_in_index: Optional[int] = None
        self.selected_audio_in_name: Optional[str] = None
        self.selected_audio_out_index: Optional[int] = None
        self.selected_audio_out_name: Optional[str] = None
        # ---- 기존 main.py 와의 호환용 ----
        self.selected_camera: Optional[str] = None         # str(index)
        self.selected_audio_in: Optional[str] = None       # name
        self.selected_audio_out: Optional[str] = None      # name

        # ---- 진행바 모드 ----
        self._init_task: Optional[Callable] = None
        self._init_error: Optional[BaseException] = None

        # ---- 위젯 핸들 ----
        self.root: Optional[tk.Tk] = None
        self._content: Optional[tk.Frame] = None
        self.port_combo: Optional[ttk.Combobox] = None
        self.bt_status: Optional[tk.Label] = None
        self.motion_spin: Optional[tk.Spinbox] = None
        self.motion_test_btn: Optional[ttk.Button] = None
        self.motion_test_status: Optional[tk.Label] = None
        self.cam_combo: Optional[ttk.Combobox] = None
        self.in_combo: Optional[ttk.Combobox] = None
        self.out_combo: Optional[ttk.Combobox] = None
        self.preview_canvas: Optional[tk.Canvas] = None
        self.preview_btn: Optional[ttk.Button] = None
        self.preview_status_label: Optional[tk.Label] = None
        self.vu_bar: Optional[ttk.Progressbar] = None
        self.vu_db_label: Optional[tk.Label] = None
        self.mic_test_btn: Optional[ttk.Button] = None
        self.mic_test_status: Optional[tk.Label] = None
        self.test_btn: Optional[ttk.Button] = None
        self.test_status_label: Optional[tk.Label] = None
        # 진행바 화면
        self.status_label: Optional[tk.Label] = None
        self.detail_label: Optional[tk.Label] = None
        self.progress: Optional[ttk.Progressbar] = None

        # ---- 데이터 ----
        self._ports: list = []
        self._cameras: List[Tuple[int, str]] = []
        self._audio_inputs: List[Tuple[int, str]] = []
        self._audio_outputs: List[Tuple[int, str]] = []

        # ---- 미리보기 스레드/상태 ----
        self._preview_cap = None
        self._preview_thread: Optional[threading.Thread] = None
        self._preview_stop = threading.Event()
        self._preview_frame = None
        self._preview_lock = threading.Lock()
        self._preview_after_id: Optional[str] = None
        self._preview_imgtk = None             # ImageTk 참조 유지
        self._preview_text_id: Optional[int] = None
        self._preview_image_id: Optional[int] = None

        # ---- 마이크 스트림/VU 상태 ----
        self._mic_stream = None
        self._mic_level = 0.0
        self._mic_lock = threading.Lock()
        self._vu_after_id: Optional[str] = None

        # ---- 테스트 톤 상태 ----
        self._test_after_id: Optional[str] = None

        # ---- 마이크 테스트(녹음→재생) 상태 ----
        self._mic_test_running = False

        # ---- 로봇 동작 테스트 상태 ----
        self._motion_test_running = False
        self._motion_test_cancel = threading.Event()
        self._motion_test_robot = None
        # ---- LED 테스트 상태 ----
        self._led_test_running = False
        self._led_cancel = threading.Event()
        self._pending_motion = None      # LED 중 동작 테스트로 끼워 보낼 모션
        self._pending_power = None        # LED 중 전원 켜기/끄기 예약(True/False)
        self.led_motion_var = None        # 'LED 중 이 동작 함께' 체크 변수
        self.led_test_btn = None
        self.led_test_status = None
        self._motormap_img = None

    # ============================================================
    # Config (INI)
    # ============================================================
    def _load_config(self) -> dict:
        result = {
            "last_port": None,
            "last_camera_index": None,
            "last_audio_in_index": None,
            "last_audio_out_index": None,
        }
        if not os.path.exists(self.config_file):
            return result
        try:
            self.config.read(self.config_file, encoding="utf-8")
        except Exception:
            return result
        if "SETTINGS" not in self.config:
            return result
        s = self.config["SETTINGS"]
        result["last_port"] = s.get("last_port") or None

        def _to_int(v):
            try:
                return int(v) if v not in (None, "") else None
            except Exception:
                return None

        result["last_camera_index"] = _to_int(s.get("last_camera_index"))
        result["last_audio_in_index"] = _to_int(s.get("last_audio_in_index"))
        result["last_audio_out_index"] = _to_int(s.get("last_audio_out_index"))
        return result

    def _save_config(self) -> None:
        if "SETTINGS" not in self.config:
            self.config.add_section("SETTINGS")
        s = self.config["SETTINGS"]
        if self.selected_port is not None:
            s["last_port"] = self.selected_port
        if self.selected_camera_index is not None:
            s["last_camera_index"] = str(self.selected_camera_index)
        if self.selected_camera_name:
            s["last_camera_name"] = str(self.selected_camera_name)
        if self.selected_audio_in_index is not None:
            s["last_audio_in_index"] = str(self.selected_audio_in_index)
        if self.selected_audio_out_index is not None:
            s["last_audio_out_index"] = str(self.selected_audio_out_index)
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                self.config.write(f)
        except Exception:
            pass

    # ============================================================
    # 윈도우
    # ============================================================
    def _center_window(self, window) -> None:
        ws, hs = window.winfo_screenwidth(), window.winfo_screenheight()
        try:
            from scrollable import env_center
            ec = env_center()
        except Exception:
            ec = None
        if ec:                                   # 메인 윈도 중앙(전달된 좌표)
            x = ec[0] - self.width // 2
            y = ec[1] - self.height // 2
        else:
            x = int((ws - self.width) / 2)
            y = int((hs - self.height) / 2)
        window.geometry(f"{self.width}x{self.height}+{int(x)}+{int(y)}")

    def _build_root(self) -> None:
        self.root = tk.Tk()
        self.root.title(self.title)
        # 화면보다 크면 화면 높이에 맞춰 줄이고(스크롤로 나머지 처리)
        sh = self.root.winfo_screenheight()
        eff_h = min(self.height, max(560, sh - 80))
        self.height = eff_h
        self.root.geometry(f"{self.width}x{self.height}")
        self.root.minsize(self.width, 560)
        self._center_window(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # 창을 최상단으로 + 포커스(다른 윈도 아래로 안 들어가게)
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(60, self.root.focus_force)
        except Exception:
            pass
        try:
            style = ttk.Style()
            if "vista" in style.theme_names():
                style.theme_use("vista")
            style.configure("Big.TButton", padding=(8, 6))
            style.configure("Ok.TButton", padding=(12, 8))
        except Exception:
            pass

    # ============================================================
    # 메인 패널 (Zoom 스타일)
    # ============================================================
    def _show_main_panel(self) -> None:
        for w in self.root.winfo_children():
            w.destroy()

        tk.Label(
            self.root,
            text=self.title,
            font=("Malgun Gothic", 14, "bold"),
            pady=12,
        ).pack(side="top", fill="x")

        # 하단 고정 버튼(스크롤되지 않음) — 먼저 bottom 에 배치해 항상 보이게
        self._build_buttons()

        # 본문은 양방향 스크롤 영역 안에 둔다(내용이 창보다 커도 끝까지 볼 수 있게)
        from scrollable import make_scrollable
        self._content = make_scrollable(self.root)

        self._build_port_section()
        self._build_camera_section()
        self._build_mic_section()
        self._build_speaker_section()

        # 초기 로딩
        self._refresh_ports()
        self._refresh_cameras()
        self._refresh_audio()
        # 마이크 VU 자동 시작
        self._restart_mic_stream()

    # ----------------- 시리얼 -----------------
    def _build_port_section(self) -> None:
        frame = ttk.LabelFrame(
            self._content, text=f"  시리얼 포트 ({self.baudrate} bps)  ",
            padding=10
        )
        frame.pack(fill="x", padx=15, pady=(4, 6))

        # --- 블루투스 페어링 안내/도우미 ---
        bt = tk.Frame(frame, bg="#e8f0fe"); bt.pack(fill="x", pady=(0, 8))
        tk.Label(
            bt, bg="#e8f0fe", fg="#1565c0", justify="left",
            font=("Malgun Gothic", 9),
            text=("ℹ 휴머노이드(FB153)는 처음 한 번만 Windows에서 블루투스 페어링하면 됩니다.\n"
                  "   1) 아래 '블루투스 설정 열기' → '장치 추가' → 'Bluetooth'\n"
                  "        → '알 수 없는 장치 또는 FB153' 선택\n"
                  "   2) PIN 0000 입력 후 앱으로 돌아와 '페어링 후 다시 검색'을 누르세요\n"
                  "        (자동으로 포트를 잡습니다)"),
        ).pack(anchor="w", padx=8, pady=(6, 2))
        tk.Label(
            bt, bg="#e8f0fe", fg="#c62828", justify="left",
            font=("Malgun Gothic", 9, "bold"),
            text=("②-2) ⚠ 블루투스 동글은 짝이 되는 로봇하고만 연결됩니다.\n"
                  "        다른 로봇을 쓰려면 그 로봇의 전용 동글을 사용하세요.\n"
                  "        (한 동글로 여러 로봇을 페어링하지 않습니다)"),
        ).pack(anchor="w", padx=8, pady=(0, 4))
        btn_bt = tk.Frame(bt, bg="#e8f0fe"); btn_bt.pack(anchor="w", padx=8,
                                                         pady=(0, 6))
        tk.Button(btn_bt, text="🔵  블루투스 설정 열기", bg="#1565c0", fg="white",
                  activebackground="#0d47a1", activeforeground="white",
                  relief="flat", cursor="hand2",
                  font=("Malgun Gothic", 9, "bold"),
                  command=self._open_bt_settings).pack(side="left", ipadx=6,
                                                       ipady=2)
        tk.Button(btn_bt, text="↻  페어링 후 다시 검색", bg="#2e7d32", fg="white",
                  activebackground="#1b5e20", activeforeground="white",
                  relief="flat", cursor="hand2",
                  font=("Malgun Gothic", 9, "bold"),
                  command=self._rescan_after_pairing).pack(side="left",
                                                           padx=(8, 0),
                                                           ipadx=6, ipady=2)
        self.bt_status = tk.Label(bt, bg="#e8f0fe", fg="#555",
                                  font=("Malgun Gothic", 9), justify="left")
        self.bt_status.pack(anchor="w", padx=8, pady=(0, 6))

        row = tk.Frame(frame); row.pack(fill="x")
        self.port_combo = ttk.Combobox(row, state="readonly")
        self.port_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="↻", width=3,
                   command=self._refresh_ports).pack(side="left", padx=(6, 0))

        # 모터맵 + 동작/LED 테스트
        test_row = tk.Frame(frame); test_row.pack(fill="x", pady=(10, 0))
        img_holder = tk.Frame(test_row, bg="#1e1e1e"); img_holder.pack(side="left")
        mm = self._load_motormap(150)
        if mm is not None:
            self._motormap_img = mm
            lbl = tk.Label(img_holder, image=mm, bg="#1e1e1e", cursor="hand2")
            lbl.pack(padx=4, pady=(4, 0))
            lbl.bind("<Button-1>", lambda e: self._show_motormap_full())
            tk.Label(img_holder, text="🔍 클릭하면 크게 보기", bg="#1e1e1e",
                     fg="#9fb3d8", font=("Malgun Gothic", 8),
                     cursor="hand2").pack(pady=(0, 4))
        else:
            cv = tk.Canvas(img_holder, width=72, height=88, bg="#1e1e1e",
                           highlightthickness=1, highlightbackground="#555")
            cv.pack(); self._draw_robot_icon(cv)

        ctrl = tk.Frame(test_row); ctrl.pack(side="left", padx=(12, 0), fill="y")
        mrow = tk.Frame(ctrl); mrow.pack(anchor="w", pady=(2, 4))
        tk.Label(mrow, text="모션", font=("Malgun Gothic", 9)).pack(side="left")
        # 번호 + 이름 함께 (직접 번호 입력도 가능)
        self.motion_combo = ttk.Combobox(
            mrow, width=22, values=[motion_label(n) for n in ALL_MOTIONS])
        self.motion_combo.set(motion_label(1))      # 기본: 1번(기본 자세)
        self.motion_combo.pack(side="left", padx=(6, 0))
        # 체크 시: LED 테스트가 도는 동안 위 모션을 사이클마다 함께 실행
        self.led_motion_var = tk.BooleanVar(value=False)
        tk.Checkbutton(mrow, text="LED 중 이 동작 함께",
                       variable=self.led_motion_var,
                       font=("Malgun Gothic", 8)).pack(side="left", padx=(6, 0))

        brow = tk.Frame(ctrl); brow.pack(anchor="w")
        self.motion_test_btn = ttk.Button(
            brow, text="🤖  동작 테스트", width=15,
            command=self._start_motion_test, style="Big.TButton",
        )
        self.motion_test_btn.pack(side="left")
        self.led_test_btn = ttk.Button(
            brow, text="🌈  LED 테스트", width=14,
            command=self._start_led_test, style="Big.TButton",
        )
        self.led_test_btn.pack(side="left", padx=(6, 0))

        # 전원 켜기/끄기 (기본)
        prow = tk.Frame(ctrl); prow.pack(anchor="w", pady=(6, 0))
        tk.Button(prow, text="🔌 전원 켜기", bg="#28a745", fg="white",
                  relief="flat", cursor="hand2", width=12,
                  font=("Malgun Gothic", 9, "bold"),
                  command=lambda: self._start_power(True)).pack(side="left")
        tk.Button(prow, text="⏻ 전원 끄기", bg="#c62828", fg="white",
                  relief="flat", cursor="hand2", width=12,
                  font=("Malgun Gothic", 9, "bold"),
                  command=lambda: self._start_power(False)).pack(
            side="left", padx=(6, 0))
        tk.Label(prow, text="(끄기: 앉은 뒤 토크 해제)",
                 font=("Malgun Gothic", 8), fg="#999").pack(side="left",
                                                            padx=(6, 0))

        self.motion_test_status = tk.Label(
            ctrl, text="포트가 맞는지 모르면 눌러보세요", fg="gray",
            font=("Malgun Gothic", 9), justify="left", wraplength=360,
        )
        self.motion_test_status.pack(anchor="w", pady=(6, 0))
        self.led_test_status = tk.Label(
            ctrl, text="", fg="gray", font=("Malgun Gothic", 9),
            justify="left", wraplength=360,
        )
        self.led_test_status.pack(anchor="w", pady=(2, 0))

    def _open_bt_settings(self) -> None:
        """Windows 블루투스 설정 화면을 연다. (장치 추가는 사용자가 진행)"""
        opened = False
        for cmd in (["explorer.exe", "ms-settings:bluetooth"],
                    ["cmd", "/c", "start", "", "ms-settings:bluetooth"]):
            try:
                subprocess.Popen(cmd)
                opened = True
                break
            except Exception:
                continue
        if not opened:
            try:
                os.startfile("ms-settings:bluetooth")   # 최후의 수단
                opened = True
            except Exception:
                opened = False
        if self.bt_status is not None:
            if opened:
                self.bt_status.config(
                    text="→ '장치 추가'에서 FB153 선택, PIN 0000 입력 후 "
                         "'페어링 후 다시 검색'을 누르세요.", fg="#1565c0")
            else:
                self.bt_status.config(
                    text="블루투스 설정을 열지 못했습니다. "
                         "직접 설정 > Bluetooth 및 장치에서 추가하세요.",
                    fg="#c62828")

    def _find_robot_port(self) -> Optional[str]:
        """페어링된 포트 중 FB153(휴머노이드)으로 보이는 포트 device 반환."""
        for p in self._ports:
            addr = _bt_remote_address(p.hwid)
            if addr and addr != "000000000000":
                name = (bt_device_name(addr) or "").upper()
                if "FB153" in name:
                    return p.device
        return None

    def _rescan_after_pairing(self) -> None:
        """페어링이 끝난 뒤 포트를 다시 검색하고 로봇을 자동으로 잡았는지 알린다."""
        self._refresh_ports()
        robot_port = self._find_robot_port()
        if self.bt_status is None:
            return
        if robot_port:
            self.bt_status.config(
                text="✓ 휴머노이드(FB153) 발견 — 아래 드롭다운에서 선택하세요",
                fg="#2e7d32")
        elif self._ports:
            self.bt_status.config(
                text="포트는 검색됐지만 FB153은 아직 안 보입니다. "
                     "페어링이 끝났는지 확인 후 다시 누르세요.", fg="#ef6c00")
        else:
            self.bt_status.config(
                text="검색된 포트가 없습니다. 페어링을 먼저 완료하세요 (PIN 0000).",
                fg="#c62828")

    def _show_motormap_full(self) -> None:
        """모터 맵 이미지를 큰 창으로 자세히 보여준다(화면에 맞춰 확대, 스크롤 지원)."""
        if not _HAS_PIL:
            return
        try:
            img = Image.open(paths.MOTORMAP_PATH)
        except Exception:
            return
        top = tk.Toplevel(self.root)
        top.title("모터 맵 — 자세히 보기")
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        w, h = img.width, img.height
        # 화면에 맞춰 확대(작으면 키우고, 너무 크면 줄임). 최대 4배.
        scale = min((sw - 140) / w, (sh - 200) / h, 4.0)
        if scale > 0 and abs(scale - 1.0) > 0.01:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        photo = ImageTk.PhotoImage(img)
        top._photo = photo                      # 참조 유지(GC 방지)

        from scrollable import make_scrollable, fit_window
        fit_window(top, img.width + 50, img.height + 90, parent=self.root)
        body = make_scrollable(top, bg="#1e1e1e")
        tk.Label(body, image=photo, bg="#1e1e1e").pack(padx=8, pady=8)
        tk.Button(body, text="닫기", width=12,
                  command=top.destroy).pack(pady=(0, 10))
        try:
            top.lift(); top.attributes("-topmost", True)
            top.after(60, top.focus_force)
        except Exception:
            pass

    def _load_motormap(self, target_h: int):
        """assets/motorMap.png 을 target_h 높이로 로드. 실패 시 None."""
        if not _HAS_PIL:
            return None
        try:
            img = Image.open(paths.MOTORMAP_PATH)
            w = max(1, int(img.width * target_h / img.height))
            return ImageTk.PhotoImage(img.resize((w, target_h)))
        except Exception:
            return None

    @staticmethod
    def _rainbow(h: float):
        """0~1 색상값 → (r,g,b) 0~255."""
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0)
        return int(r * 255), int(g * 255), int(b * 255)

    def _draw_robot_icon(self, cv: tk.Canvas) -> None:
        """외부 이미지 없이 간단한 로봇 일러스트를 그린다."""
        cv.create_line(36, 8, 36, 18, fill="#888", width=2)             # 안테나
        cv.create_oval(32, 2, 40, 10, fill="#ffd54f", outline="")       # 안테나 전구
        cv.create_rectangle(18, 18, 54, 46, fill="#cfd8dc",
                            outline="#607d8b", width=2)                 # 머리
        cv.create_oval(25, 28, 33, 36, fill="#2196f3", outline="")      # 왼눈
        cv.create_oval(39, 28, 47, 36, fill="#2196f3", outline="")      # 오른눈
        cv.create_rectangle(14, 48, 58, 82, fill="#90a4ae",
                            outline="#546e7a", width=2)                 # 몸통
        cv.create_rectangle(7, 52, 14, 76, fill="#90a4ae",
                            outline="#546e7a")                          # 왼팔
        cv.create_rectangle(58, 52, 65, 76, fill="#90a4ae",
                            outline="#546e7a")                          # 오른팔
        cv.create_rectangle(27, 58, 45, 72, fill="#37474f", outline="") # 가슴 패널

    def _selected_motion(self) -> int:
        """모션 콤보에서 번호 추출. 'N - 이름' 또는 직접 입력 숫자 모두 허용."""
        t = self.motion_combo.get().strip()
        try:
            if " - " in t:
                return int(t.split(" - ")[0])
            return int(t)
        except Exception:
            return 1

    def _start_motion_test(self) -> None:
        if self._motion_test_running:
            return
        # LED 테스트가 도는 중이면 같은 연결로 모션만 끼워 보낸다(포트 충돌 방지)
        if self._led_test_running:
            self._pending_motion = self._selected_motion()
            self.motion_test_status.config(
                text=f"LED 진행 중 — 모션 {self._pending_motion} 예약(곧 전송)",
                fg="#1565c0")
            return
        if not self._ports or self.port_combo.current() < 0:
            self.motion_test_status.config(text="시리얼 포트를 먼저 선택하세요",
                                           fg="#c62828")
            return
        port = self._ports[self.port_combo.current()].device
        motion = self._selected_motion()
        self._motion_test_running = True
        self._motion_test_cancel.clear()
        # 버튼을 '중지'로 전환 → 멈추고 바로 다음 포트 테스트 가능
        self.motion_test_btn.config(text="■  중지", command=self._stop_motion_test)
        self.motion_test_status.config(text=f"① {port} 여는 중...", fg="#555")
        threading.Thread(
            target=self._motion_test_worker, args=(port, motion), daemon=True
        ).start()

    def _stop_motion_test(self) -> None:
        """진행 중인 테스트를 중지. 블로킹된 전송도 포트를 닫아 즉시 깨운다."""
        self._motion_test_cancel.set()
        r = self._motion_test_robot
        if r is not None:
            try:
                r.close()
            except Exception:
                pass
        if self.motion_test_status is not None:
            self.motion_test_status.config(text="■ 중지 중...", fg="#c62828")

    def _reset_motion_test_btn(self) -> None:
        if self.motion_test_btn is not None:
            try:
                self.motion_test_btn.config(
                    text="🤖  동작 테스트", command=self._start_motion_test,
                    state="normal")
            except Exception:
                pass

    def _motion_test_worker(self, port: str, motion: int) -> None:
        robot = None
        cancel = self._motion_test_cancel
        try:
            from robot_controller import HumanoidRobot

            # ① 포트 열기 (블루투스는 무선 링크가 여기서 맺어진다)
            robot = HumanoidRobot(port, self.baudrate)
            robot.connect()
            self._motion_test_robot = robot

            if cancel.is_set():
                return
            if not robot.is_connected:
                self._ui(lambda: self.motion_test_status.config(
                    text=f"✗ {port} 를 열지 못했습니다.", fg="#c62828"))
                return

            # ② 포트 열림 = SW 연결 성공 (맞는 장치인지는 아직 모름)
            mname = motion_name(motion)
            self._ui(lambda: self.motion_test_status.config(
                text=f"② 포트 열림 ✓   모션 {motion} ({mname}) 전송 중...",
                fg="#1565c0"))

            ok = robot.send_motion(motion)   # write_timeout 으로 무한대기 방지
            if cancel.is_set():
                return
            if not ok:
                self._ui(lambda: self.motion_test_status.config(
                    text="✗ 전송 실패 — 로봇 전원/범위를 확인하거나 다른 포트로",
                    fg="#c62828"))
                return

            cancel.wait(1.5)                 # 중지 가능한 대기
            if not cancel.is_set():
                robot.send_motion(1)         # 기본 자세로 복귀
                cancel.wait(0.3)

            if cancel.is_set():
                return
            # ③ 결과 — 포트 열림 ≠ 로봇 동작. 눈으로 확인하라고 명시.
            msg = (f"③ 완료 ✓  (패킷 전송됨)\n"
                   f"   ▶ 로봇이 움직였으면 → 이 포트({port})가 맞습니다.\n"
                   f"   ▶ 안 움직였으면 → 다른 포트 골라 다시 테스트하세요.")
            self._ui(lambda m=msg: self.motion_test_status.config(
                text=m, fg="#2e7d32"))
        except Exception as e:
            if cancel.is_set():
                pass
            else:
                self._ui(lambda ex=e: self.motion_test_status.config(
                    text=f"✗ 실패: {ex}\n   (포트가 사용 중이거나 없는 포트일 수 있음)",
                    fg="#c62828"))
        finally:
            if robot is not None:
                try:
                    robot.close()
                except Exception:
                    pass
            self._motion_test_robot = None
            self._motion_test_running = False
            if cancel.is_set():
                self._ui(lambda: self.motion_test_status.config(
                    text="■ 중지됨 — 다른 포트를 골라 다시 테스트하세요",
                    fg="#c62828"))
            self._ui(self._reset_motion_test_btn)

    # ----------------- LED 테스트 (1~18 화려하게) -----------------
    def _start_led_test(self) -> None:
        if self._led_test_running:
            self._stop_led_test()
            return
        if self._motion_test_running:
            return
        if not self._ports or self.port_combo.current() < 0:
            self.led_test_status.config(text="시리얼 포트를 먼저 선택하세요",
                                        fg="#c62828")
            return
        port = self._ports[self.port_combo.current()].device
        self._led_test_running = True
        self._led_cancel.clear()
        self._pending_motion = None       # 이전 예약 모션 초기화
        self.led_test_btn.config(text="■  LED 중지")
        self.led_test_status.config(text="🌈 LED 테스트 시작...", fg="#1565c0")
        threading.Thread(target=self._led_test_worker, args=(port,),
                         daemon=True).start()

    def _stop_led_test(self) -> None:
        # 취소 신호만 보낸다. 포트를 여기서 닫으면 finally의 '모션 1 복귀'가
        # 전송 실패하므로, 워커 루프가 스스로 끝내고 복귀/정리하도록 둔다.
        self._led_cancel.set()

    def _drain_pending_motion(self, robot) -> None:
        """LED 중 예약된 모션/전원 명령을 (LED 스레드에서) 한 번 전송."""
        m = self._pending_motion
        if m is not None:
            self._pending_motion = None
            try:
                robot.send_motion(int(m))
                self._ui(lambda mm=m: self.motion_test_status.config(
                    text=f"LED 중 모션 {mm} 전송됨 ✓", fg="#2e7d32"))
            except Exception:
                pass

    # ---------- 전원 켜기/끄기 ----------
    def _start_power(self, on: bool) -> None:
        # 안전 전원은 시퀀스(앉기→7초→OFF / ON→일어서기)라 포트를 단독 사용
        if self._led_test_running or self._motion_test_running:
            self.motion_test_status.config(
                text="동작/LED 테스트 중지 후 전원 버튼을 사용하세요", fg="#c62828")
            return
        if not self._ports or self.port_combo.current() < 0:
            self.motion_test_status.config(text="시리얼 포트를 먼저 선택하세요",
                                           fg="#c62828")
            return
        port = self._ports[self.port_combo.current()].device
        threading.Thread(target=self._power_worker, args=(port, on),
                         daemon=True).start()

    def _power_worker(self, port: str, on: bool) -> None:
        """로봇제어의 safe_power 와 동일: 켜기=전원ON→일어서기, 끄기=앉기→7초→전원OFF."""
        robot = None
        try:
            from robot_controller import HumanoidRobot
            from motion_table import SAFE_SIT, SAFE_UP, POWER_OFF_HOLD
            try:
                import sound
            except Exception:
                sound = None
            robot = HumanoidRobot(port, self.baudrate)
            robot.connect()
            if not robot.is_connected:
                self._ui(lambda: self.motion_test_status.config(
                    text=f"✗ {port} 를 열지 못했습니다.", fg="#c62828"))
                return
            # 새로 연 BT 링크 안정화(로봇제어는 기존 연결 재사용이라 불필요).
            # 첫 패킷이 씹히지 않도록 잠깐 대기.
            time.sleep(0.6)
            if on:
                if sound:
                    sound.player.play_effect(sound.FX_POWER_ON)   # 전원 ON 효과음
                self._ui(lambda: self.motion_test_status.config(
                    text="🔌 전원 ON → 일어서는 중...", fg="#1565c0"))
                # 전원(토크) ON — 첫 패킷 씹힘 대비 2회 전송 후 토크 안정 대기
                robot.power(True)
                time.sleep(0.4)
                robot.power(True)
                time.sleep(0.6)                       # 토크 확실히 들어온 뒤
                robot.send_motion(SAFE_UP)            # 61 일어서기(2회로 확실히)
                time.sleep(0.4)
                robot.send_motion(SAFE_UP)
                self._ui(lambda: self.motion_test_status.config(
                    text="🔌 전원 켜짐 (일어서기)", fg="#2e7d32"))
            else:
                self._ui(lambda h=POWER_OFF_HOLD: self.motion_test_status.config(
                    text=f"⏻ 앉는 중... {h}초 뒤 전원 끔", fg="#1565c0"))
                # 앉기 — 씹힘 대비 2회 → 7초 → 전원 OFF 2회
                robot.send_motion(SAFE_SIT)           # 60 앉기
                time.sleep(0.4)
                robot.send_motion(SAFE_SIT)
                time.sleep(POWER_OFF_HOLD)            # 7초 대기
                robot.power(False)
                time.sleep(0.3)
                robot.power(False)                    # 전원(토크) OFF
                if sound:                             # 전원 꺼진 뒤 효과음
                    sound.player.play_effect(sound.FX_POWER_OFF)
                self._ui(lambda: self.motion_test_status.config(
                    text="⏻ 전원 꺼짐 (앉기 후 토크 OFF)", fg="#2e7d32"))
        except Exception as e:
            self._ui(lambda ex=e: self.motion_test_status.config(
                text=f"✗ 전원 명령 실패: {ex}", fg="#c62828"))
        finally:
            if robot is not None:
                try:
                    robot.close()
                except Exception:
                    pass

    def _led_test_worker(self, port: str) -> None:
        cancel = self._led_cancel
        robot = None
        ids = list(range(1, 19))
        groups = [("오른다리", [9, 7, 5, 3, 1]), ("왼다리", [10, 8, 6, 4, 2]),
                  ("오른팔", [11, 13, 15]), ("왼팔", [12, 14, 16]),
                  ("허리", [17]), ("머리", [18])]
        try:
            from robot_controller import HumanoidRobot
            robot = HumanoidRobot(port, self.baudrate)
            robot.connect()
            self._motion_test_robot = robot
            if not robot.is_connected:
                self._ui(lambda: self.led_test_status.config(
                    text=f"✗ {port} 를 열지 못했습니다.", fg="#c62828"))
                return

            # 시작: 동작 17 실행 (LED 테스트는 이 동작 중에 — 되면 같이, 안 되면 말고)
            robot.send_motion(17)
            self._ui(lambda: self.led_test_status.config(
                text="동작 17 실행 + LED 쇼 (멈출 때까지)", fg="#6a1b9a"))

            # 순차 점등 ID 순서: 오른쪽(홀) → 왼쪽(짝) → 허리 → 머리
            SEQ_ORDER = [1, 3, 5, 7, 9, 11, 13, 15,
                         2, 4, 6, 8, 10, 12, 14, 16, 17, 18]
            PALETTE = [(255, 0, 0), (0, 255, 0), (0, 128, 255),
                       (255, 200, 0), (255, 0, 255), (0, 255, 255),
                       (255, 255, 255)]
            FSTEPS = 6                          # 페이드 인 단계
            FDT = 0.2 / FSTEPS                  # 모터 1개당 페이드 인 ≈ 200ms
            cycle = 0
            # 멈춤 버튼 누를 때까지 계속 반복
            while not cancel.is_set():
                # ① 순차 점등: ID 순서로 한 모터씩 페이드 인(≈200ms) 후 켜진 채 유지.
                #    18개 다 켜지면 200ms 간격으로 3회 깜빡. 한 사이클마다 색 변경.
                cr, cg, cb = PALETTE[cycle % len(PALETTE)]
                cycle += 1
                # 체크 시: 이번 사이클에 선택 모션을 함께 실행
                if self.led_motion_var is not None and self.led_motion_var.get():
                    try:
                        msel = self._selected_motion()
                        robot.send_motion(msel)
                        self._ui(lambda m=msel: self.led_test_status.config(
                            text=f"① 모션 {m} 함께 실행 + 순차 점등", fg="#6a1b9a"))
                    except Exception:
                        pass
                for mid in SEQ_ORDER:
                    if cancel.is_set():
                        break
                    self._drain_pending_motion(robot)   # LED 중 모션 끼워 전송
                    self._ui(lambda m=mid: self.led_test_status.config(
                        text=f"① 순차 점등  ID {m}", fg="#1565c0"))
                    for s in range(1, FSTEPS + 1):       # 페이드 인(켜진 채 유지)
                        if cancel.is_set():
                            break
                        f = s / FSTEPS
                        robot.send_leds([(mid, int(cr * f), int(cg * f),
                                          int(cb * f))])
                        if cancel.wait(FDT):
                            break
                if cancel.is_set():
                    break
                # 18번까지 켜졌으면 고개(ID 18) 좌우 30도 흔들고 중앙 복귀
                self._ui(lambda: self.led_test_status.config(
                    text="① 고개 좌우 흔들기 ↔", fg="#6a1b9a"))
                for pos in (30, -30, 0):
                    if cancel.is_set():
                        break
                    robot.send_positions([(18, pos, 40)])   # 머리 위치 제어
                    if cancel.wait(0.45):
                        break
                if cancel.is_set():
                    break
                # 다 켜진 상태에서 200ms 간격 3회 깜빡
                self._ui(lambda: self.led_test_status.config(
                    text="① 전체 점등 → 깜빡 ✨", fg="#1565c0"))
                for _ in range(3):
                    if cancel.is_set():
                        break
                    robot.send_leds([(i, 0, 0, 0) for i in SEQ_ORDER])
                    if cancel.wait(0.2):
                        break
                    robot.send_leds([(i, cr, cg, cb) for i in SEQ_ORDER])
                    if cancel.wait(0.2):
                        break
                if cancel.is_set():
                    break
                robot.send_leds([(i, 0, 0, 0) for i in ids])   # 끄고 무지개로

                # ② 무지개: 페이드 인 → 천천히 회전 → 페이드 아웃 (확실하게)
                base = [(i, self._rainbow((i - 1) / 18.0)) for i in ids]
                STEPS = 18
                # 페이드 인 (어둡→밝)
                for s in range(1, STEPS + 1):
                    if cancel.is_set():
                        break
                    f = s / STEPS
                    robot.send_leds([(i, int(r * f), int(g * f), int(b * f))
                                     for i, (r, g, b) in base])
                    self._ui(lambda: self.led_test_status.config(
                        text="② 무지개 페이드 인 🌈", fg="#6a1b9a"))
                    if cancel.wait(0.06):
                        break
                # 천천히 한 바퀴 회전
                for t in range(18):
                    if cancel.is_set():
                        break
                    self._drain_pending_motion(robot)   # LED 중 모션 끼워 전송
                    leds = [(i,) + self._rainbow((i - 1) / 18.0 + t / 18.0)
                            for i in ids]
                    robot.send_leds(leds)
                    self._ui(lambda: self.led_test_status.config(
                        text="② 무지개 🌈 (멈춤 버튼으로 종료)", fg="#6a1b9a"))
                    if cancel.wait(0.12):
                        break
                # 페이드 아웃 (밝→어둡)
                for s in range(STEPS, -1, -1):
                    if cancel.is_set():
                        break
                    f = s / STEPS
                    robot.send_leds([(i, int(r * f), int(g * f), int(b * f))
                                     for i, (r, g, b) in base])
                    self._ui(lambda: self.led_test_status.config(
                        text="② 무지개 페이드 아웃 🌙", fg="#6a1b9a"))
                    if cancel.wait(0.06):
                        break
        except Exception as e:
            if not cancel.is_set():
                self._ui(lambda ex=e: self.led_test_status.config(
                    text=f"✗ 실패: {ex}", fg="#c62828"))
        finally:
            # 기본자세 복귀 보장: LED 전송 중 끊겨 포트가 닫혔으면 재연결해서라도 1번 전송
            try:
                if robot is None or not robot.is_connected:
                    from robot_controller import HumanoidRobot
                    robot = HumanoidRobot(port, self.baudrate)
                    robot.connect()
            except Exception:
                robot = None
            if robot is not None and robot.is_connected:
                try:
                    robot.send_leds([(i, 0, 0, 0) for i in range(1, 19)])
                    time.sleep(0.05)
                except Exception:
                    pass
                try:
                    robot.send_motion(1)        # 기본자세(1)로 복귀
                    time.sleep(0.2)
                    robot.send_motion(1)        # 한 번 더(전송 보장)
                    time.sleep(0.15)
                except Exception:
                    pass
                try:
                    robot.close()
                except Exception:
                    pass
            self._motion_test_robot = None
            self._led_test_running = False
            if cancel.is_set():
                self._ui(lambda: self.led_test_status.config(
                    text="■ LED 테스트 중지됨 (기본자세 복귀)", fg="#c62828"))
            self._ui(lambda: self.led_test_btn.config(text="🌈  LED 테스트")
                     if self.led_test_btn is not None else None)

    # ----------------- 카메라 -----------------
    def _build_camera_section(self) -> None:
        frame = ttk.LabelFrame(self._content, text="  카메라  ", padding=10)
        frame.pack(fill="x", padx=15, pady=6)

        row = tk.Frame(frame); row.pack(fill="x")
        self.cam_combo = ttk.Combobox(row, state="readonly")
        self.cam_combo.pack(side="left", fill="x", expand=True)
        self.cam_combo.bind("<<ComboboxSelected>>",
                            lambda e: self._on_camera_changed())
        ttk.Button(row, text="↻", width=3,
                   command=self._refresh_cameras).pack(side="left", padx=(6, 0))

        prev_row = tk.Frame(frame); prev_row.pack(fill="x", pady=(10, 0))
        self.preview_canvas = tk.Canvas(
            prev_row, width=self.PREVIEW_W, height=self.PREVIEW_H,
            bg="#1e1e1e", highlightthickness=1, highlightbackground="#555",
        )
        self.preview_canvas.pack(side="left")
        self._preview_image_id = self.preview_canvas.create_image(
            self.PREVIEW_W // 2, self.PREVIEW_H // 2, anchor="center"
        )
        self._preview_text_id = self.preview_canvas.create_text(
            self.PREVIEW_W // 2, self.PREVIEW_H // 2,
            text="(미리보기 정지됨)", fill="#aaaaaa",
            font=("Malgun Gothic", 10),
        )

        btn_col = tk.Frame(prev_row); btn_col.pack(side="left", padx=(12, 0), fill="y")
        self.preview_btn = ttk.Button(
            btn_col, text="▶  미리보기 시작", width=18,
            command=self._toggle_preview, style="Big.TButton",
        )
        self.preview_btn.pack(pady=(4, 6))
        self.preview_status_label = tk.Label(
            btn_col, text="", fg="gray", font=("Malgun Gothic", 9), justify="left"
        )
        self.preview_status_label.pack(anchor="w", pady=(8, 0))

        if not _HAS_CV2:
            self.preview_btn.config(state="disabled")
            self.preview_status_label.config(text="OpenCV(cv2) 미설치")
        elif not _HAS_PIL:
            self.preview_btn.config(state="disabled")
            self.preview_status_label.config(text="Pillow(PIL) 미설치")
        elif not _HAS_PYGRABBER:
            self.preview_status_label.config(
                text="ℹ pygrabber 설치 시\n  카메라 실제 이름 표시"
            )

    # ----------------- 마이크 -----------------
    def _build_mic_section(self) -> None:
        frame = ttk.LabelFrame(self._content, text="  마이크 (입력)  ", padding=10)
        frame.pack(fill="x", padx=15, pady=6)

        row = tk.Frame(frame); row.pack(fill="x")
        self.in_combo = ttk.Combobox(row, state="readonly")
        self.in_combo.pack(side="left", fill="x", expand=True)
        self.in_combo.bind("<<ComboboxSelected>>",
                           lambda e: self._restart_mic_stream())
        ttk.Button(row, text="↻", width=3,
                   command=self._refresh_audio).pack(side="left", padx=(6, 0))

        vu = tk.Frame(frame); vu.pack(fill="x", pady=(10, 2))
        tk.Label(vu, text="입력 레벨", width=8, anchor="w",
                 font=("Malgun Gothic", 9)).pack(side="left")
        self.vu_bar = ttk.Progressbar(
            vu, orient="horizontal", mode="determinate",
            maximum=100, length=380,
        )
        self.vu_bar.pack(side="left", fill="x", expand=True, padx=(4, 8))
        self.vu_db_label = tk.Label(
            vu, text="-∞ dB", width=8, anchor="e",
            font=("Consolas", 9), fg="#444"
        )
        self.vu_db_label.pack(side="left")

        # Zoom 스타일: 녹음 후 바로 재생해서 마이크가 잘 들어오는지 확인
        test_row = tk.Frame(frame); test_row.pack(fill="x", pady=(10, 2))
        self.mic_test_btn = ttk.Button(
            test_row, text="🎙  마이크 테스트 (녹음 후 재생)", width=26,
            command=self._start_mic_test, style="Big.TButton",
        )
        self.mic_test_btn.pack(side="left")
        self.mic_test_status = tk.Label(
            test_row, text="", fg="gray", font=("Malgun Gothic", 9)
        )
        self.mic_test_status.pack(side="left", padx=(10, 0))

        if not _HAS_SD:
            self.vu_db_label.config(text="sd 없음")
            self.vu_bar.state(["disabled"])
            self.mic_test_btn.config(state="disabled")
            self.mic_test_status.config(text="sounddevice 필요")
        elif not _HAS_NUMPY:
            self.mic_test_btn.config(state="disabled")
            self.mic_test_status.config(text="numpy 필요")

    # ----------------- 스피커 -----------------
    def _build_speaker_section(self) -> None:
        frame = ttk.LabelFrame(self._content, text="  스피커 (출력)  ", padding=10)
        frame.pack(fill="x", padx=15, pady=6)

        row = tk.Frame(frame); row.pack(fill="x")
        self.out_combo = ttk.Combobox(row, state="readonly")
        self.out_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="↻", width=3,
                   command=self._refresh_audio).pack(side="left", padx=(6, 0))

        test_row = tk.Frame(frame); test_row.pack(fill="x", pady=(10, 2))
        self.test_btn = ttk.Button(
            test_row, text="🔊  테스트 사운드 재생", width=22,
            command=self._play_test_tone, style="Big.TButton",
        )
        self.test_btn.pack(side="left")
        self.test_status_label = tk.Label(
            test_row, text="", fg="gray", font=("Malgun Gothic", 9)
        )
        self.test_status_label.pack(side="left", padx=(10, 0))

        if not (_HAS_SD and _HAS_NUMPY):
            self.test_btn.config(state="disabled")
            self.test_status_label.config(text="sounddevice + numpy 필요")

    # ----------------- 하단 버튼 -----------------
    def _build_buttons(self) -> None:
        bar = tk.Frame(self.root)
        bar.pack(side="bottom", fill="x", padx=15, pady=(16, 12))
        ttk.Button(bar, text="취소", width=12,
                   command=self._on_close).pack(side="right", padx=(8, 0))
        ok = tk.Button(
            bar, text="확인", width=16,
            bg="#28a745", fg="white",
            font=("Malgun Gothic", 10, "bold"),
            relief="flat",
            activebackground="#218838", activeforeground="white",
            command=self._on_select,
        )
        ok.pack(side="right")

    # ============================================================
    # 새로고침
    # ============================================================
    def _refresh_ports(self) -> None:
        self._ports = list(serial.tools.list_ports.comports())
        display = []
        robot_idx: Optional[int] = None
        for p in self._ports:
            label = f"{p.device} - {p.description}"
            addr = _bt_remote_address(p.hwid)
            if addr and addr != "000000000000":
                # 로봇(FB153)만 표시. 그 외 BT 기기는 표시하지 않음.
                name = (bt_device_name(addr) or "").upper()
                if "FB153" in name:
                    short = f"{addr[-4:-2]}:{addr[-2:]}"
                    label += f"   ★ 휴머노이드 (MAC {short})"
                    if robot_idx is None:
                        robot_idx = len(display)
            display.append(label)
        self.port_combo["values"] = display
        if not display:
            self.port_combo.set("(검색된 포트 없음)")
            return
        # 우선순위: 저장된 포트 → 로봇 추정 포트 → 첫 번째
        for i, p in enumerate(self._ports):
            if p.device == self.last_port:
                self.port_combo.current(i); return
        if robot_idx is not None:
            self.port_combo.current(robot_idx); return
        self.port_combo.current(0)

    def _refresh_cameras(self) -> None:
        self._stop_preview()
        self._cameras = list_camera_devices()
        display = [f"[{idx}]  {name}" for idx, name in self._cameras]
        self.cam_combo["values"] = display
        if not display:
            self.cam_combo.set("(검색된 카메라 없음)")
            return
        for i, (idx, _) in enumerate(self._cameras):
            if idx == self.last_camera_index:
                self.cam_combo.current(i); return
        self.cam_combo.current(0)

    def _refresh_audio(self) -> None:
        self._stop_mic_stream()
        self._audio_inputs, self._audio_outputs = list_audio_devices()

        in_disp = [f"[{idx}]  {name}" for idx, name in self._audio_inputs] \
                  or ["(검색된 입력 장치 없음)"]
        out_disp = [f"[{idx}]  {name}" for idx, name in self._audio_outputs] \
                   or ["(검색된 출력 장치 없음)"]
        self.in_combo["values"] = in_disp
        self.out_combo["values"] = out_disp

        # 입력 복원
        if self._audio_inputs:
            picked = 0
            for i, (idx, _) in enumerate(self._audio_inputs):
                if idx == self.last_audio_in_index:
                    picked = i; break
            self.in_combo.current(picked)
        else:
            self.in_combo.current(0)

        # 출력 복원
        if self._audio_outputs:
            picked = 0
            for i, (idx, _) in enumerate(self._audio_outputs):
                if idx == self.last_audio_out_index:
                    picked = i; break
            self.out_combo.current(picked)
        else:
            self.out_combo.current(0)

        if self._audio_inputs:
            self._restart_mic_stream()

    # ============================================================
    # 카메라 미리보기
    # ============================================================
    def _current_camera_index(self) -> Optional[int]:
        if not self.cam_combo:
            return None
        i = self.cam_combo.current()
        if i < 0 or i >= len(self._cameras):
            return None
        return self._cameras[i][0]

    def _on_camera_changed(self) -> None:
        # 미리보기 중에 카메라를 바꾸면 자동 재시작
        if self._preview_thread and self._preview_thread.is_alive():
            self._stop_preview()
            self._start_preview()

    def _toggle_preview(self) -> None:
        if self._preview_thread and self._preview_thread.is_alive():
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview(self) -> None:
        if not (_HAS_CV2 and _HAS_PIL):
            return
        idx = self._current_camera_index()
        if idx is None:
            self.preview_status_label.config(text="카메라 없음")
            return
        try:
            backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else 0
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                self.preview_status_label.config(text=f"열기 실패 (idx={idx})")
                return
        except Exception as e:
            self.preview_status_label.config(text=f"오류: {e}")
            return

        self._preview_cap = cap
        self._preview_stop.clear()
        self._preview_thread = threading.Thread(
            target=self._preview_worker, daemon=True
        )
        self._preview_thread.start()

        self.preview_btn.config(text="■  미리보기 정지")
        self.preview_status_label.config(text=f"카메라 #{idx} 실행 중")
        self.preview_canvas.itemconfig(self._preview_text_id, text="")
        self._schedule_preview_render()

    def _stop_preview(self) -> None:
        self._preview_stop.set()
        if self._preview_thread is not None:
            self._preview_thread.join(timeout=1.0)
        self._preview_thread = None

        if self._preview_cap is not None:
            try:
                self._preview_cap.release()
            except Exception:
                pass
            self._preview_cap = None

        if self._preview_after_id is not None and self.root is not None:
            try:
                self.root.after_cancel(self._preview_after_id)
            except Exception:
                pass
            self._preview_after_id = None

        with self._preview_lock:
            self._preview_frame = None
        self._preview_imgtk = None

        if self.preview_btn is not None:
            try:
                self.preview_btn.config(text="▶  미리보기 시작")
            except Exception:
                pass
        if self.preview_canvas is not None:
            try:
                self.preview_canvas.itemconfig(self._preview_image_id, image="")
                self.preview_canvas.itemconfig(
                    self._preview_text_id, text="(미리보기 정지됨)"
                )
            except Exception:
                pass
        if self.preview_status_label is not None:
            try:
                self.preview_status_label.config(text="")
            except Exception:
                pass

    def _preview_worker(self) -> None:
        cap = self._preview_cap
        while not self._preview_stop.is_set() and cap is not None:
            try:
                ok, frame = cap.read()
            except Exception:
                break
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                scale = min(self.PREVIEW_W / w, self.PREVIEW_H / h)
                new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                resized = cv2.resize(rgb, (new_w, new_h),
                                     interpolation=cv2.INTER_AREA)
            except Exception:
                continue
            with self._preview_lock:
                self._preview_frame = resized
            time.sleep(0.02)

    def _schedule_preview_render(self) -> None:
        if self.root is None:
            return
        self._render_preview_frame()
        self._preview_after_id = self.root.after(
            self.PREVIEW_INTERVAL_MS, self._schedule_preview_render
        )

    def _render_preview_frame(self) -> None:
        with self._preview_lock:
            frame = self._preview_frame
        if frame is None or self.preview_canvas is None:
            return
        try:
            img = Image.fromarray(frame)
            self._preview_imgtk = ImageTk.PhotoImage(img)
            self.preview_canvas.itemconfig(
                self._preview_image_id, image=self._preview_imgtk
            )
        except Exception:
            pass

    # ============================================================
    # 마이크 VU
    # ============================================================
    def _current_audio_in_index(self) -> Optional[int]:
        if not self.in_combo:
            return None
        i = self.in_combo.current()
        if i < 0 or i >= len(self._audio_inputs):
            return None
        return self._audio_inputs[i][0]

    def _restart_mic_stream(self) -> None:
        self._stop_mic_stream()
        if not _HAS_SD:
            return
        idx = self._current_audio_in_index()
        if idx is None:
            return
        try:
            info = sd.query_devices(idx)
            samplerate = int(info.get("default_samplerate") or 44100)
        except Exception:
            samplerate = 44100

        def callback(indata, frames, time_info, status):
            try:
                if _HAS_NUMPY:
                    rms = float(
                        np.sqrt(np.mean(indata.astype("float32") ** 2))
                    )
                else:
                    total, n = 0.0, 0
                    for v in indata:
                        for x in (v if hasattr(v, "__iter__") else [v]):
                            total += float(x) * float(x)
                            n += 1
                    rms = (total / max(n, 1)) ** 0.5
            except Exception:
                rms = 0.0
            with self._mic_lock:
                self._mic_level = rms

        try:
            blocksize = max(256, int(samplerate * 0.03))
            self._mic_stream = sd.InputStream(
                device=idx,
                channels=1,
                samplerate=samplerate,
                blocksize=blocksize,
                callback=callback,
            )
            self._mic_stream.start()
        except Exception:
            if self.vu_db_label is not None:
                self.vu_db_label.config(text="열기 실패")
            self._mic_stream = None
            return

        self._schedule_vu_update()

    def _stop_mic_stream(self) -> None:
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
            except Exception:
                pass
            try:
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None

        if self._vu_after_id is not None and self.root is not None:
            try:
                self.root.after_cancel(self._vu_after_id)
            except Exception:
                pass
            self._vu_after_id = None

        with self._mic_lock:
            self._mic_level = 0.0
        if self.vu_bar is not None:
            try:
                self.vu_bar["value"] = 0
            except Exception:
                pass
        if self.vu_db_label is not None:
            try:
                self.vu_db_label.config(text="-∞ dB")
            except Exception:
                pass

    def _schedule_vu_update(self) -> None:
        if self.root is None:
            return
        with self._mic_lock:
            level = self._mic_level

        # 0..1 RMS → 0..100 (×4 부스트, 시각적 가시성)
        pct = min(100, int(level * 400))
        if level > 1e-6:
            db = 20.0 * math.log10(level)
            db_text = f"{db:5.1f} dB"
            # 색상: 너무 작음(회색) / 보통(녹색) / 큼(주황)
            color = "#2e7d32" if db < -3 else "#ef6c00"
            if db < -40:
                color = "#888"
        else:
            db_text, color = "-∞ dB", "#888"

        if self.vu_bar is not None:
            self.vu_bar["value"] = pct
        if self.vu_db_label is not None:
            self.vu_db_label.config(text=db_text, fg=color)

        self._vu_after_id = self.root.after(
            self.VU_INTERVAL_MS, self._schedule_vu_update
        )

    # ============================================================
    # 마이크 테스트 (녹음 → 재생)  — Zoom 스타일
    # ============================================================
    def _ui(self, fn: Callable) -> None:
        """워커 스레드에서 UI를 안전하게 갱신."""
        try:
            if self.root is not None:
                self.root.after(0, fn)
        except Exception:
            pass

    def _start_mic_test(self) -> None:
        if not (_HAS_SD and _HAS_NUMPY) or self._mic_test_running:
            return
        in_idx = self._current_audio_in_index()
        if in_idx is None:
            self.mic_test_status.config(text="입력 장치 없음", fg="#c62828")
            return
        out_idx = self._current_audio_out_index()
        self._mic_test_running = True
        self.mic_test_btn.config(state="disabled")
        self.mic_test_status.config(text="● 녹음 중...  3", fg="#c62828")
        threading.Thread(
            target=self._mic_test_worker, args=(in_idx, out_idx), daemon=True
        ).start()

    def _mic_test_worker(self, in_idx: int, out_idx: Optional[int]) -> None:
        DUR = 3
        try:
            sr = int(sd.query_devices(in_idx).get("default_samplerate") or 44100)
        except Exception:
            sr = 44100

        frames: list = []

        def rec_callback(indata, n, t, status):
            # 녹음 데이터 저장 + 입력 레벨(VU) 갱신을 한 스트림에서 동시에
            frames.append(indata.copy())
            try:
                rms = float(np.sqrt(np.mean(indata.astype("float32") ** 2)))
            except Exception:
                rms = 0.0
            with self._mic_lock:
                self._mic_level = rms

        stream = None
        try:
            # 라이브 스트림 정지(장치 단독 점유). 대신 녹음 스트림이 레벨도 갱신.
            self._ui(self._stop_mic_stream)
            time.sleep(0.15)

            blocksize = max(256, int(sr * 0.03))
            stream = sd.InputStream(
                device=in_idx, channels=1, samplerate=sr,
                blocksize=blocksize, callback=rec_callback,
            )
            stream.start()
            # 녹음 중에도 레벨바가 움직이도록 VU 갱신 루프 재가동
            self._ui(self._schedule_vu_update)

            for left in range(DUR, 0, -1):
                self._ui(lambda l=left: self.mic_test_status.config(
                    text=f"● 녹음 중...  {l}", fg="#c62828"))
                time.sleep(1.0)

            stream.stop()
            stream.close()
            stream = None
            with self._mic_lock:        # 재생 중에는 레벨 0
                self._mic_level = 0.0

            rec = np.concatenate(frames, axis=0) if frames \
                else np.zeros((1, 1), dtype="float32")
            # 들리도록 음량 정규화
            peak = float(np.max(np.abs(rec))) if rec.size else 0.0
            if peak > 1e-4:
                rec = (rec / peak) * 0.9

            self._ui(lambda: self.mic_test_status.config(
                text="▶ 재생 중...", fg="#2e7d32"))
            sd.play(rec, samplerate=sr,
                    device=out_idx if out_idx is not None else None)
            sd.wait()
            self._ui(lambda: self.mic_test_status.config(
                text="✓ 완료 (들리면 정상)", fg="#2e7d32"))
        except Exception as e:
            self._ui(lambda ex=e: self.mic_test_status.config(
                text=f"실패: {ex}", fg="#c62828"))
        finally:
            if stream is not None:
                try:
                    stream.stop(); stream.close()
                except Exception:
                    pass
            self._mic_test_running = False
            self._ui(self._finish_mic_test)

    def _finish_mic_test(self) -> None:
        if self.mic_test_btn is not None:
            try:
                self.mic_test_btn.config(state="normal")
            except Exception:
                pass
        # 실시간 VU 재개
        self._restart_mic_stream()

    # ============================================================
    # 스피커 테스트
    # ============================================================
    def _current_audio_out_index(self) -> Optional[int]:
        if not self.out_combo:
            return None
        i = self.out_combo.current()
        if i < 0 or i >= len(self._audio_outputs):
            return None
        return self._audio_outputs[i][0]

    def _play_test_tone(self) -> None:
        if not (_HAS_SD and _HAS_NUMPY):
            return
        idx = self._current_audio_out_index()
        if idx is None:
            self.test_status_label.config(text="출력 장치 없음")
            return
        try:
            info = sd.query_devices(idx)
            samplerate = int(info.get("default_samplerate") or 44100)
        except Exception:
            samplerate = 44100

        try:
            sd.stop()
            dur = 0.8
            t = np.linspace(0, dur, int(samplerate * dur), endpoint=False)
            tone = 0.25 * np.sin(2 * np.pi * 660.0 * t)
            fade = max(1, int(samplerate * 0.04))
            env = np.ones_like(tone)
            env[:fade] = np.linspace(0, 1, fade)
            env[-fade:] = np.linspace(1, 0, fade)
            tone = (tone * env).astype("float32")
            sd.play(tone, samplerate=samplerate, device=idx)
            self.test_status_label.config(text=f"▶ 출력 [{idx}] 재생 중", fg="#2e7d32")
            if self._test_after_id is not None and self.root is not None:
                try:
                    self.root.after_cancel(self._test_after_id)
                except Exception:
                    pass
            if self.root is not None:
                self._test_after_id = self.root.after(
                    int(dur * 1000) + 100,
                    lambda: self.test_status_label.config(text="", fg="gray"),
                )
        except Exception as e:
            self.test_status_label.config(text=f"재생 실패: {e}", fg="#c62828")

    # ============================================================
    # 확인 / 닫기
    # ============================================================
    def _on_select(self) -> None:
        # 시리얼 포트는 필수
        if not self._ports or self.port_combo.current() < 0:
            messagebox.showwarning("경고", "시리얼 포트를 선택해주세요.")
            return
        pi = self.port_combo.current()
        self.selected_port = self._ports[pi].device

        ci = self.cam_combo.current() if self.cam_combo else -1
        if 0 <= ci < len(self._cameras):
            self.selected_camera_index, self.selected_camera_name = self._cameras[ci]
            self.selected_camera = str(self.selected_camera_index)

        ai = self.in_combo.current() if self.in_combo else -1
        if 0 <= ai < len(self._audio_inputs):
            self.selected_audio_in_index, self.selected_audio_in_name = self._audio_inputs[ai]
            self.selected_audio_in = self.selected_audio_in_name

        ao = self.out_combo.current() if self.out_combo else -1
        if 0 <= ao < len(self._audio_outputs):
            self.selected_audio_out_index, self.selected_audio_out_name = self._audio_outputs[ao]
            self.selected_audio_out = self.selected_audio_out_name

        self._save_config()
        self._cleanup_runtime()

        if self._init_task is None:
            self.root.destroy()
        else:
            self._show_progress()

    def _on_close(self) -> None:
        self._cleanup_runtime()
        try:
            if _HAS_SD:
                sd.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _cleanup_runtime(self) -> None:
        try:
            self._stop_preview()
        except Exception:
            pass
        try:
            self._stop_mic_stream()
        except Exception:
            pass

    # ============================================================
    # 진행바 화면
    # ============================================================
    def _show_progress(self) -> None:
        # 메인으로 넘어가기 전 미리보기 카메라를 확실히 반환(해제)한다.
        # 안 그러면 메인 쪽에서 같은 카메라를 못 열어 검은 화면이 날 수 있다.
        self._stop_preview()

        for w in self.root.winfo_children():
            w.destroy()

        wrap = tk.Frame(self.root); wrap.pack(expand=True, fill="both")
        self.status_label = tk.Label(
            wrap, text="준비 중...", font=("Malgun Gothic", 12, "bold")
        )
        self.status_label.pack(pady=(80, 8))
        self.progress = ttk.Progressbar(
            wrap, orient="horizontal", length=420, mode="determinate"
        )
        self.progress.pack(pady=10)
        self.detail_label = tk.Label(
            wrap, text="", fg="gray", font=("Malgun Gothic", 10)
        )
        self.detail_label.pack()

        threading.Thread(target=self._run_init_task, daemon=True).start()

    def _update_ui(self, msg: str, detail: str, val: int) -> None:
        def apply():
            if self.status_label is None:
                return
            try:
                self.status_label.config(text=msg)
                self.detail_label.config(text=detail)
                self.progress["value"] = val
            except Exception:
                pass
        try:
            self.root.after(0, apply)
        except Exception:
            pass

    def _run_init_task(self) -> None:
        try:
            self._init_task(self._update_ui)
            self._update_ui("준비 완료!", "메인 화면을 실행합니다.", 100)
            time.sleep(0.6)
            try:
                self.root.after(0, self.root.destroy)
            except Exception:
                pass
        except Exception as e:
            self._init_error = e
            try:
                self.root.after(
                    0,
                    lambda exc=e: messagebox.showerror("에러", f"초기화 실패: {exc}"),
                )
                self.root.after(80, self.root.destroy)
            except Exception:
                pass

    # ============================================================
    # 공개 API
    # ============================================================
    def run(self) -> Optional[str]:
        """장치 선택 창을 띄우고, 확인 시 선택된 시리얼 포트 문자열을 반환.
        취소/종료 시 None."""
        self._build_root()
        self._show_main_panel()
        self.root.mainloop()
        return self.selected_port

    def run_with_progress(self, init_task: Callable) -> Optional[str]:
        """선택 후 진행바 화면에서 init_task(update_fn)를 백그라운드로 실행.

        init_task : Callable[[Callable[[str,str,int], None]], None]
            (status_msg, detail, percent)를 받는 update 함수를 인자로 받는 함수.
        """
        self._init_task = init_task
        self._build_root()
        self._show_main_panel()
        self.root.mainloop()
        if self._init_error is not None:
            raise self._init_error
        return self.selected_port


# ============================================================
# 단독 실행 데모
# ============================================================
if __name__ == "__main__":
    print("[port_selector] 단독 실행 데모")
    print(f"  cv2={_HAS_CV2} PIL={_HAS_PIL} numpy={_HAS_NUMPY} "
          f"sounddevice={_HAS_SD} pygrabber={_HAS_PYGRABBER}")

    print("\n[port_selector] 시리얼 포트:")
    for p in serial.tools.list_ports.comports():
        print(f"  - {p.device} : {p.description}")
    print("\n[port_selector] 카메라:")
    for idx, name in list_camera_devices():
        print(f"  - [{idx}] {name}")
    in_devs, out_devs = list_audio_devices()
    print("\n[port_selector] 오디오 입력:")
    for idx, name in in_devs:
        print(f"  - [{idx}] {name}")
    print("\n[port_selector] 오디오 출력:")
    for idx, name in out_devs:
        print(f"  - [{idx}] {name}")

    print("\n[port_selector] UI를 띄웁니다. (취소하면 종료)")
    sel = PortSelector(title="장치 및 로봇 설정", baudrate=115200)
    port = sel.run()
    if port is None:
        print("[port_selector] 선택된 포트 없음.")
    else:
        print(f"[port_selector] 포트   : {port}")
        print(f"[port_selector] 카메라  : idx={sel.selected_camera_index} "
              f"name={sel.selected_camera_name}")
        print(f"[port_selector] 마이크  : idx={sel.selected_audio_in_index} "
              f"name={sel.selected_audio_in_name}")
        print(f"[port_selector] 스피커  : idx={sel.selected_audio_out_index} "
              f"name={sel.selected_audio_out_name}")
