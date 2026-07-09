"""이미지 업로드 → OpenAI(GPT) API로 이미지 번역 → 번역문 치환 이미지 생성 웹 앱."""

import base64
import io
import json
import os
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

# OCR(텍스트 위치 추출)에 사용할 언어 조합 (Tesseract 언어 코드)
OCR_LANGS = {
    "auto": "kor+eng+jpn+chi_sim",
    "kor": "kor+eng",
    "eng": "eng",
    "jpn": "jpn+eng",
    "chi_sim": "chi_sim+eng",
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB

# 테스트나 프록시 환경을 위해 베이스 URL을 바꿀 수 있게 한다
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_MODEL = "gpt-5.5"

LANG_NAMES = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh-CN": "Simplified Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

TRANSLATION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "translations",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "translations": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["translations"],
            "additionalProperties": False,
        },
    },
}


def translate_blocks_with_gpt(
    image_bytes: bytes,
    mime: str,
    blocks: list[str],
    target_lang: str,
    api_key: str,
    model: str,
    glossary: str,
) -> list[str]:
    """이미지와 OCR 블록을 GPT에 보내 블록별 번역을 받아온다."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)

    glossary_part = ""
    if glossary.strip():
        glossary_part = (
            "\n\nUser dictionary (MUST be applied exactly; format: source=translation):\n"
            + glossary.strip()
        )

    numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(blocks))
    instruction = (
        f"The attached image contains text. Below are {len(blocks)} text blocks "
        "extracted by OCR, in reading order. Look at the image to understand context "
        "and fix any obvious OCR mistakes, then translate each block into "
        f"{lang_name}.{glossary_part}\n\n"
        "Return JSON with a \"translations\" array containing exactly "
        f"{len(blocks)} strings, where translations[i] is the translation of block [i]. "
        "Keep numbers, prices, and proper nouns accurate. Output only the translation "
        "for each block, nothing else.\n\n"
        f"Text blocks:\n{numbered}"
    )

    image_b64 = base64.b64encode(image_bytes).decode()
    resp = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "response_format": TRANSLATION_SCHEMA,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional translator. Translate text found in images accurately and naturally.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                        },
                    ],
                },
            ],
        },
        timeout=120,
    )
    if resp.status_code != 200:
        try:
            detail = resp.json()["error"]["message"]
        except Exception:
            detail = resp.text[:300]
        raise RuntimeError(f"OpenAI API 오류 (HTTP {resp.status_code}): {detail}")

    content = resp.json()["choices"][0]["message"]["content"]
    translations = json.loads(content)["translations"]
    # 개수가 어긋나면 부족분은 원문 유지, 초과분은 버린다
    translations = [str(t) for t in translations[: len(blocks)]]
    translations += blocks[len(translations):]
    return translations


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/translate")
async def translate_image(
    file: UploadFile = File(...),
    ocr_lang: str = Form("auto"),
    target_lang: str = Form("ko"),
    api_key: str = Form(""),
    model: str = Form(DEFAULT_MODEL),
    glossary: str = Form(""),
) -> dict:
    api_key = api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API 키를 입력해 주세요.")
    model = model.strip() or DEFAULT_MODEL

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
        return {"extracted": "", "translated": "", "image": "", "engine": "", "message": "이미지에서 텍스트를 찾지 못했습니다."}

    try:
        translations = translate_blocks_with_gpt(
            image_bytes=data,
            mime=file.content_type or "image/png",
            blocks=[p["text"] for p in paragraphs],
            target_lang=target_lang,
            api_key=api_key,
            model=model,
            glossary=glossary,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"번역 실패: {e}")

    for p, t in zip(paragraphs, translations):
        p["translated"] = t

    rendered = render_translated(image, paragraphs)
    buf = io.BytesIO()
    rendered.save(buf, format="PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "extracted": "\n\n".join(p["text"] for p in paragraphs),
        "translated": "\n\n".join(p["translated"] for p in paragraphs),
        "image": f"data:image/png;base64,{image_b64}",
        "engine": f"OpenAI {model}",
        "message": "",
    }


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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
