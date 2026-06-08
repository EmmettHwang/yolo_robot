# coding: utf-8
"""
pdf_viewer.py
=============
라인코어 M 매뉴얼(assets/라인코어엠매뉴얼.pdf)을 앱에서 보여주는 뷰어.

- PyMuPDF(fitz)로 페이지를 이미지로 렌더링.
- 매뉴얼 2페이지의 '목차'를 파싱해 좌측에 트리로 표시 → 클릭하면 해당 페이지로 이동.
- 이전/다음, 페이지 이동, 확대/축소 지원.

(목차의 인쇄 페이지번호 = PDF 페이지 인덱스 + 1)
"""

import os
import re

import tkinter as tk
from tkinter import ttk, messagebox

from paths import ASSETS

MANUAL_PDF = os.path.join(ASSETS, "라인코어엠매뉴얼.pdf")

_TOC_RE = re.compile(r"^(.*?\S)\s*\.{2,}\s*(\d+)\s*$")
_TOP_RE = re.compile(r"^\d+\.\s")


def parse_toc(doc) -> list:
    """매뉴얼 2페이지(목차)에서 (제목, 인쇄페이지) 목록을 추출."""
    entries = []
    try:
        text = doc[1].get_text()           # PDF 2페이지 = index 1
    except Exception:
        return entries
    for line in text.splitlines():
        m = _TOC_RE.match(line.strip())
        if m:
            entries.append((m.group(1).strip(), int(m.group(2))))
    return entries


class PdfViewer(tk.Toplevel):
    def __init__(self, parent, path=MANUAL_PDF):
        super().__init__(parent)
        import fitz
        self._fitz = fitz
        self.title("📖 라인코어 M 매뉴얼")
        self.geometry("1040x780")
        self.doc = fitz.open(path)
        self.zoom = 1.5
        self.page = 0
        self._imgtk = None
        self.toc = parse_toc(self.doc)
        self._build()
        self._show_page(0)

    def _build(self):
        bar = tk.Frame(self, bg="#222"); bar.pack(fill="x")
        tk.Button(bar, text="◀ 이전", cursor="hand2",
                  command=self.prev).pack(side="left", padx=4, pady=4)
        tk.Button(bar, text="다음 ▶", cursor="hand2",
                  command=self.next).pack(side="left")
        self.page_var = tk.StringVar()
        tk.Label(bar, textvariable=self.page_var, bg="#222", fg="white",
                 font=("Malgun Gothic", 10)).pack(side="left", padx=12)
        tk.Button(bar, text="＋ 확대", cursor="hand2",
                  command=lambda: self.set_zoom(0.25)).pack(side="right", padx=4)
        tk.Button(bar, text="－ 축소", cursor="hand2",
                  command=lambda: self.set_zoom(-0.25)).pack(side="right")

        body = tk.Frame(self); body.pack(fill="both", expand=True)

        # 좌: 목차
        left = tk.Frame(body, width=300); left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="목 차 (클릭하면 이동)",
                 font=("Malgun Gothic", 11, "bold")).pack(anchor="w",
                                                          padx=8, pady=6)
        self.tree = ttk.Treeview(left, show="tree")
        tsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        last_top = ""
        for title, printed in self.toc:
            label = f"{title}   · {printed}p"
            if _TOP_RE.match(title):
                last_top = self.tree.insert("", "end", text=label,
                                            values=(printed,), open=True)
            else:
                self.tree.insert(last_top or "", "end", text=label,
                                 values=(printed,))
        self.tree.bind("<<TreeviewSelect>>", self._on_toc)

        # 우: 페이지 이미지(스크롤)
        right = tk.Frame(body); right.pack(side="left", fill="both",
                                           expand=True)
        self.canvas = tk.Canvas(right, bg="#5a5a5a", highlightthickness=0)
        vsb = ttk.Scrollbar(right, orient="vertical",
                            command=self.canvas.yview)
        hsb = ttk.Scrollbar(right, orient="horizontal",
                            command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.img_id = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind_all("<MouseWheel>", self._wheel)

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 * (e.delta // 120), "units")

    def _on_toc(self, _):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if vals:
            self._show_page(int(vals[0]) - 1)   # PDF index = 인쇄페이지 - 1

    def _show_page(self, idx):
        idx = max(0, min(self.doc.page_count - 1, idx))
        self.page = idx
        pix = self.doc[idx].get_pixmap(
            matrix=self._fitz.Matrix(self.zoom, self.zoom))
        from PIL import Image, ImageTk
        mode = "RGBA" if pix.alpha else "RGB"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        self._imgtk = ImageTk.PhotoImage(img)
        self.canvas.itemconfig(self.img_id, image=self._imgtk)
        self.canvas.configure(scrollregion=(0, 0, pix.width, pix.height))
        self.canvas.yview_moveto(0)
        self.canvas.xview_moveto(0)
        self.page_var.set(f"{idx + 1} / {self.doc.page_count} 페이지")

    def prev(self):
        self._show_page(self.page - 1)

    def next(self):
        self._show_page(self.page + 1)

    def set_zoom(self, d):
        self.zoom = max(0.5, min(3.0, self.zoom + d))
        self._show_page(self.page)

    def destroy(self):
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        try:
            self.doc.close()
        except Exception:
            pass
        super().destroy()


def open_manual(parent=None):
    if not os.path.exists(MANUAL_PDF):
        messagebox.showerror("오류", f"매뉴얼 PDF가 없습니다:\n{MANUAL_PDF}")
        return
    try:
        PdfViewer(parent)
    except Exception as e:
        messagebox.showerror("매뉴얼 열기 실패",
                             f"{e}\n(PyMuPDF 설치 필요: pip install pymupdf)")


if __name__ == "__main__":
    root = tk.Tk(); root.withdraw()
    open_manual(root)
    root.mainloop()
