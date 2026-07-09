"""데스크톱(exe) 실행용 런처: 서버를 띄우고 기본 브라우저를 자동으로 연다."""

import socket
import threading
import webbrowser

import uvicorn

from app.main import app


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
