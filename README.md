# Image-Translator

이미지를 업로드하면 OpenAI(GPT) API가 이미지 속 텍스트를 인식·번역하고, **원본 텍스트 자리를 번역문으로 치환한 이미지**를 만들어 주는 웹 애플리케이션입니다.

![동작 화면](docs/screenshot.png)

## 동작 방식

이미지와 사용자 사전만 GPT에 보내면, GPT가 텍스트 블록별로 원문·번역·위치(바운딩 박스)를 한 번에 돌려줍니다.
받은 위치의 배경색·글자색을 추정해서 원문을 지우고 그 자리에 번역문을 그려 넣습니다. 별도의 OCR 엔진이 필요 없습니다.

## 기능

- **이미지 업로드**: 클릭 선택, 드래그 앤 드롭, 클립보드 붙여넣기(Ctrl+V) 지원
- **GPT 이미지 번역**: 이미지를 GPT가 직접 읽으므로 문맥을 반영한 자연스러운 번역
- **사용자 사전**: `원문=번역` 형식으로 용어를 등록하면 번역 시 반드시 해당 표기를 따릅니다 (고유명사, 브랜드명 등)
- **번역문 치환 이미지 생성**: 원본 스타일(배경색·글자색)을 유지한 채 번역문으로 교체, PNG 다운로드 가능
- 번역 대상 언어: 한국어, 영어, 일본어, 중국어, 스페인어, 프랑스어, 독일어
- API 키·모델·사용자 사전은 브라우저(localStorage)에만 저장되고 서버에 남지 않습니다

## 설치 및 실행

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

브라우저에서 http://127.0.0.1:8000 접속 후 OpenAI API 키를 입력하고 이미지를 업로드하면 됩니다.
API 키는 https://platform.openai.com/api-keys 에서 발급받을 수 있습니다.

## API

UI 없이 직접 호출할 수도 있습니다.

```bash
curl -X POST http://127.0.0.1:8000/api/translate \
  -F "file=@image.png" \
  -F "target_lang=ko" \               # ko | en | ja | zh-CN | es | fr | de ...
  -F "api_key=sk-..." \               # (필수) OpenAI API 키
  -F "model=gpt-5.5" \                # (선택) 모델명
  -F "glossary=Acme Corp=아크메"      # (선택) 사용자 사전, 한 줄에 하나
```

응답:

```json
{
  "extracted": "Hello, world!",
  "translated": "안녕, 세계!",
  "image": "data:image/png;base64,....",
  "engine": "OpenAI gpt-5.5",
  "message": ""
}
```

`image`는 번역문으로 치환된 이미지의 PNG 데이터 URI입니다.

## Windows exe로 만들기

Python 설치 없이 실행할 수 있는 단일 exe 파일을 만들 수 있습니다.

### 방법 1: GitHub Actions로 빌드 (권장 — Windows PC 불필요)

1. GitHub 저장소의 **Actions** 탭 → **Build Windows exe** 워크플로 선택
2. **Run workflow** 버튼 클릭
3. 빌드가 끝나면 실행 결과 페이지 하단의 **Artifacts**에서 `ImageTranslator-windows` 다운로드

`v1.0` 같은 태그를 푸시해도 자동으로 빌드됩니다.

### 방법 2: Windows PC에서 직접 빌드

```powershell
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --name ImageTranslator --add-data "app/static;app/static" --add-data "app/fonts;app/fonts" desktop.py
```

`dist\ImageTranslator.exe`가 생성됩니다. 실행하면 서버가 켜지고 브라우저가 자동으로 열립니다.

- exe는 처음 실행 시 압축을 푸느라 몇 초 정도 걸릴 수 있습니다.
- 실행 시 Windows Defender SmartScreen 경고가 뜨면 "추가 정보 → 실행"을 누르면 됩니다 (서명되지 않은 exe라서 나오는 경고입니다).

## 참고

- 번역은 OpenAI API를 호출하므로 인터넷 연결과 API 키가 필요합니다 (사용량만큼 과금).
- `OPENAI_BASE_URL` 환경변수로 API 베이스 URL을 바꿀 수 있습니다 (프록시/호환 서버용, 기본값 `https://api.openai.com/v1`).
- 텍스트 위치는 GPT가 추정하므로 픽셀 단위로 정확하지 않을 수 있습니다. 치환 위치가 어긋나면 더 큰(고성능) 모델을 사용해 보세요.
- 치환 렌더링은 단색에 가까운 배경에서 가장 자연스럽습니다. 사진처럼 복잡한 배경 위 텍스트는 배경색 추정이 어긋날 수 있습니다.
- 번역문 렌더링에는 Noto Serif KR 폰트(`app/fonts/`, SIL OFL 라이선스)를 사용합니다.
