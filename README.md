# Image-Translator

이미지를 업로드하면 텍스트만 추출(OCR)해서 번역해 주는 웹 애플리케이션입니다.

![동작 화면](docs/screenshot.png)

## 기능

- **이미지 업로드**: 클릭 선택, 드래그 앤 드롭, 클립보드 붙여넣기(Ctrl+V) 지원
- **텍스트 추출 (OCR)**: Tesseract 기반 — 한국어 / 영어 / 일본어 / 중국어(간체) 인식
- **번역**: Google 번역으로 한국어, 영어, 일본어, 중국어, 스페인어, 프랑스어, 독일어 지원
- 추출된 원문과 번역 결과를 나란히 보여주고, 복사 버튼 제공

## 설치

### 1. Tesseract OCR 설치

```bash
# Ubuntu / Debian
sudo apt-get install tesseract-ocr tesseract-ocr-kor tesseract-ocr-jpn tesseract-ocr-chi-sim

# macOS
brew install tesseract tesseract-lang

# Windows
# https://github.com/UB-Mannheim/tesseract/wiki 에서 설치 (설치 시 한국어 언어팩 선택)
```

### 2. Python 패키지 설치

```bash
pip install -r requirements.txt
```

## 실행

```bash
uvicorn app.main:app --port 8000
```

브라우저에서 http://127.0.0.1:8000 접속 후 이미지를 업로드하면 됩니다.

## API

UI 없이 직접 호출할 수도 있습니다.

```bash
curl -X POST http://127.0.0.1:8000/api/translate \
  -F "file=@image.png" \
  -F "ocr_lang=auto" \      # auto | kor | eng | jpn | chi_sim
  -F "target_lang=ko"       # ko | en | ja | zh-CN | es | fr | de ...
```

응답:

```json
{
  "extracted": "Hello, world!",
  "translated": "안녕, 세계!",
  "message": ""
}
```

## 참고

- OCR 정확도는 이미지 품질에 크게 좌우됩니다. 해상도가 높고 글자가 선명한 이미지일수록 잘 인식됩니다.
- 번역은 Google 번역 무료 엔드포인트를 사용하므로 인터넷 연결이 필요합니다.
