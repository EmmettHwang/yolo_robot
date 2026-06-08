# coding: utf-8
"""
webview_window.py
=================
지정한 URL을 네이티브 웹뷰(Windows: Edge WebView2)로 띄우는 독립 실행 창.

앱에서 별도 프로세스로 실행한다(메인 윈도는 대기창으로 잠금).
사용:  python webview_window.py [URL] [제목]
"""

import sys


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://kdt2025.com"
    title = sys.argv[2] if len(sys.argv) > 2 else "KDT 2025"
    try:
        import webview
    except Exception as e:
        print(f"[webview] pywebview 미설치: {e}")
        # 폴백: 기본 브라우저로 열기
        import webbrowser
        webbrowser.open(url)
        return
    webview.create_window(title, url, width=1100, height=800)
    webview.start()


if __name__ == "__main__":
    main()
