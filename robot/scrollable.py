# coding: utf-8
"""
scrollable.py
=============
임의의 컨테이너(Tk/Toplevel/Frame) 안의 내용을 양방향 스크롤 가능하게 감싸는 헬퍼.

- 내용이 영역보다 커질 때만 스크롤바가 나타난다(가로·세로 둘 다).
- 마우스 휠: 세로 스크롤, Shift+휠: 가로 스크롤.

사용 예:
    from scrollable import make_scrollable
    body = make_scrollable(root)          # body 안에 위젯을 넣으면 됨
    ttk.Label(body, text="...").pack()
"""

import tkinter as tk
from tkinter import ttk


def fit_window(win, width, height, margin=90, center=True, parent=None):
    """창 크기를 화면 안에 들어오도록 제한해서 설정한다.

    내용이 화면보다 커도 스크롤로 볼 수 있으므로, 화면 밖으로 넘치지 않게 한다.
    parent 가 주어지면 그 창(부모/메인 윈도)의 중앙에 배치한다.
    """
    try:
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    except Exception:
        sw, sh = 1920, 1080
    w = min(width, sw - margin)
    h = min(height, sh - margin)
    if center:
        # 기본: 화면 중앙
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - 10)
        # 부모가 있으면 부모(메인 윈도) 중앙으로
        if parent is not None:
            try:
                parent.update_idletasks()
                px, py = parent.winfo_rootx(), parent.winfo_rooty()
                pw, ph = parent.winfo_width(), parent.winfo_height()
                if pw > 1 and ph > 1:
                    x = px + (pw - w) // 2
                    y = py + (ph - h) // 2
            except Exception:
                pass
        # 화면 밖으로 나가지 않게 보정
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        win.geometry(f"{w}x{h}+{x}+{y}")
    else:
        win.geometry(f"{w}x{h}")
    return w, h


def center_over(win, parent, margin=90):
    """이미 크기가 정해진 창을 부모(메인 윈도) 중앙에 위치시킨다."""
    try:
        win.update_idletasks()
        w = win.winfo_width() or win.winfo_reqwidth()
        h = win.winfo_height() or win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        if parent is not None:
            parent.update_idletasks()
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        else:
            x, y = (sw - w) // 2, (sh - h) // 2
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass


def make_scrollable(parent, bg=None):
    """parent 를 채우는 스크롤 영역을 만들고, 내용을 담을 inner Frame 을 반환한다.

    parent : Tk / Toplevel / Frame
    bg     : 캔버스 배경색(선택)
    """
    container = tk.Frame(parent)
    container.pack(fill="both", expand=True)
    container.grid_rowconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)

    canvas = tk.Canvas(container, highlightthickness=0)
    if bg:
        canvas.configure(bg=bg)
    vbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    hbar = ttk.Scrollbar(container, orient="horizontal", command=canvas.xview)

    def _vset(lo, hi):
        # 다 보이면 숨기고, 넘치면 보이게
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            vbar.grid_remove()
        else:
            vbar.grid()
        vbar.set(lo, hi)

    def _hset(lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            hbar.grid_remove()
        else:
            hbar.grid()
        hbar.set(lo, hi)

    canvas.configure(yscrollcommand=_vset, xscrollcommand=_hset)
    canvas.grid(row=0, column=0, sticky="nsew")
    vbar.grid(row=0, column=1, sticky="ns")
    hbar.grid(row=1, column=0, sticky="ew")
    vbar.grid_remove()
    hbar.grid_remove()

    inner = tk.Frame(canvas)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _sync(_=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        cw = canvas.winfo_width()
        req = inner.winfo_reqwidth()
        # 공간이 남으면 내용이 가로로 꽉 차게, 모자라면 가로 스크롤이 생기게
        canvas.itemconfigure(win_id, width=max(cw, req))

    inner.bind("<Configure>", _sync)
    canvas.bind("<Configure>", _sync)

    def _on_wheel(e):
        try:
            canvas.yview_scroll(int(-e.delta / 120), "units")
        except Exception:
            pass

    def _on_shift_wheel(e):
        try:
            canvas.xview_scroll(int(-e.delta / 120), "units")
        except Exception:
            pass

    # 커서가 영역 안에 있을 때만 휠을 연결(여러 창이 떠 있어도 충돌 없게)
    def _bind_wheel(_):
        canvas.bind_all("<MouseWheel>", _on_wheel)
        canvas.bind_all("<Shift-MouseWheel>", _on_shift_wheel)

    def _unbind_wheel(_):
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Shift-MouseWheel>")

    canvas.bind("<Enter>", _bind_wheel)
    canvas.bind("<Leave>", _unbind_wheel)

    return inner
