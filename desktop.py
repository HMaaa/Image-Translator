"""데스크톱(exe) 실행용 런처: 서버를 띄우고 기본 브라우저를 자동으로 연다."""

import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path


def resource_path(rel: str) -> Path:
    """PyInstaller 번들 내부 리소스 경로 (개발 환경에서는 프로젝트 루트)."""
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if base else Path(__file__).parent) / rel


# 번들된 Tesseract가 있으면 그것을 사용 (없으면 시스템 설치본 사용)
import pytesseract  # noqa: E402

_bundled_tesseract = resource_path("tesseract/tesseract.exe")
if _bundled_tesseract.exists():
    pytesseract.pytesseract.tesseract_cmd = str(_bundled_tesseract)
    os.environ["TESSDATA_PREFIX"] = str(resource_path("tesseract/tessdata"))

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402


def find_free_port(preferred: int = 8000) -> int:
    for port in (preferred, 0):
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
        except OSError:
            continue
    raise RuntimeError("사용 가능한 포트를 찾지 못했습니다.")


def main() -> None:
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    print(f"이미지 번역기 실행 중: {url}")
    print("종료하려면 이 창을 닫거나 Ctrl+C를 누르세요.")
    threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
