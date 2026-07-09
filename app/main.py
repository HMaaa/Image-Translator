"""이미지 업로드 → 텍스트 추출(OCR) → 번역 웹 앱."""

import io
from pathlib import Path

import pytesseract
import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

app = FastAPI(title="Image Translator")

STATIC_DIR = Path(__file__).parent / "static"

# OCR에 사용할 언어 조합 (Tesseract 언어 코드)
OCR_LANGS = {
    "auto": "kor+eng+jpn+chi_sim",
    "kor": "kor+eng",
    "eng": "eng",
    "jpn": "jpn+eng",
    "chi_sim": "chi_sim+eng",
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"


def translate_text(text: str, target_lang: str) -> str:
    """Google 무료 번역 엔드포인트로 텍스트를 번역한다."""
    resp = requests.get(
        TRANSLATE_URL,
        params={"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": text},
        timeout=15,
    )
    resp.raise_for_status()
    segments = resp.json()[0] or []
    return "".join(seg[0] for seg in segments if seg[0])


def preprocess(image: Image.Image) -> Image.Image:
    """OCR 정확도를 위한 전처리: EXIF 회전 보정, 그레이스케일, 소형 이미지 확대."""
    image = ImageOps.exif_transpose(image)
    image = image.convert("L")
    if min(image.size) < 600:
        scale = 600 / min(image.size)
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.LANCZOS,
        )
    return image


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/translate")
async def translate_image(
    file: UploadFile = File(...),
    ocr_lang: str = Form("auto"),
    target_lang: str = Form("ko"),
) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 10MB를 초과합니다.")

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        raise HTTPException(status_code=400, detail="이미지 파일을 열 수 없습니다. PNG/JPG 등 이미지 형식인지 확인해 주세요.")

    lang = OCR_LANGS.get(ocr_lang, OCR_LANGS["auto"])
    try:
        extracted = pytesseract.image_to_string(preprocess(image), lang=lang)
    except pytesseract.TesseractError as e:
        raise HTTPException(status_code=500, detail=f"OCR 실패: {e}")

    extracted = extracted.strip()
    if not extracted:
        return {"extracted": "", "translated": "", "message": "이미지에서 텍스트를 찾지 못했습니다."}

    try:
        # 번역 API는 요청당 길이 제한이 있어 긴 텍스트는 나눠서 번역한다.
        chunks, current = [], ""
        for line in extracted.splitlines():
            if len(current) + len(line) + 1 > 4500:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        chunks.append(current)
        translated = "\n".join(
            translate_text(c, target_lang) if c.strip() else c for c in chunks
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"번역 실패 (네트워크를 확인해 주세요): {e}")

    return {"extracted": extracted, "translated": translated, "message": ""}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
