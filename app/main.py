"""이미지 업로드 → 텍스트 추출(OCR) → 번역문으로 치환한 이미지 생성 웹 앱."""

import base64
import io
from pathlib import Path

import pytesseract
import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

from app.render import extract_paragraphs, render_translated

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


def preprocess(image: Image.Image) -> tuple[Image.Image, float]:
    """OCR 전처리: 그레이스케일 + 소형 이미지 확대. 적용된 배율도 반환한다."""
    gray = image.convert("L")
    scale = 1.0
    if min(gray.size) < 600:
        scale = 600 / min(gray.size)
        gray = gray.resize(
            (round(gray.width * scale), round(gray.height * scale)),
            Image.LANCZOS,
        )
    return gray, scale


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
        image = ImageOps.exif_transpose(image)
    except Exception:
        raise HTTPException(status_code=400, detail="이미지 파일을 열 수 없습니다. PNG/JPG 등 이미지 형식인지 확인해 주세요.")

    lang = OCR_LANGS.get(ocr_lang, OCR_LANGS["auto"])
    try:
        processed, scale = preprocess(image)
        paragraphs = extract_paragraphs(processed, lang=lang, scale=scale)
    except pytesseract.TesseractError as e:
        raise HTTPException(status_code=500, detail=f"OCR 실패: {e}")

    if not paragraphs:
        return {"extracted": "", "translated": "", "image": "", "message": "이미지에서 텍스트를 찾지 못했습니다."}

    try:
        for p in paragraphs:
            p["translated"] = translate_text(p["text"], target_lang)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"번역 실패 (네트워크를 확인해 주세요): {e}")

    rendered = render_translated(image, paragraphs)
    buf = io.BytesIO()
    rendered.save(buf, format="PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "extracted": "\n\n".join(p["text"] for p in paragraphs),
        "translated": "\n\n".join(p["translated"] for p in paragraphs),
        "image": f"data:image/png;base64,{image_b64}",
        "message": "",
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
