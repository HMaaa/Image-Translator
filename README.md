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

## Windows exe로 만들기

Python이나 Tesseract 설치 없이 실행할 수 있는 단일 exe 파일을 만들 수 있습니다.
exe 안에 Tesseract OCR 엔진과 언어팩(한/영/일/중)이 모두 포함됩니다.

### 방법 1: GitHub Actions로 빌드 (권장 — Windows PC 불필요)

1. GitHub 저장소의 **Actions** 탭 → **Build Windows exe** 워크플로 선택
2. **Run workflow** 버튼 클릭
3. 빌드가 끝나면 실행 결과 페이지 하단의 **Artifacts**에서 `ImageTranslator-windows` 다운로드

`v1.0` 같은 태그를 푸시해도 자동으로 빌드됩니다.

### 방법 2: Windows PC에서 직접 빌드

```powershell
# 1. Tesseract 설치 (https://github.com/UB-Mannheim/tesseract/wiki, 한국어 언어팩 포함)
# 2. 설치 폴더를 프로젝트 루트에 tesseract\ 라는 이름으로 복사
Copy-Item "C:\Program Files\Tesseract-OCR" -Destination tesseract -Recurse

# 3. 빌드
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --name ImageTranslator --add-data "app/static;app/static" --add-data "tesseract;tesseract" desktop.py
```

`dist\ImageTranslator.exe`가 생성됩니다. 실행하면 서버가 켜지고 브라우저가 자동으로 열립니다.

- exe는 처음 실행 시 압축을 푸느라 몇 초 정도 걸릴 수 있습니다.
- OCR은 오프라인으로 동작하지만, **번역은 인터넷 연결이 필요**합니다.
- 실행 시 Windows Defender SmartScreen 경고가 뜨면 "추가 정보 → 실행"을 누르면 됩니다 (서명되지 않은 exe라서 나오는 경고입니다).

## 참고

- OCR 정확도는 이미지 품질에 크게 좌우됩니다. 해상도가 높고 글자가 선명한 이미지일수록 잘 인식됩니다.
- 번역은 Google 번역 무료 엔드포인트를 사용하므로 인터넷 연결이 필요합니다.
