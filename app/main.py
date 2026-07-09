"""이미지 업로드 → OpenAI(GPT) API로 이미지 번역 → 번역문 치환 이미지 생성 웹 앱.

이미지와 사용자 사전만 GPT에 보내면 텍스트 인식·번역·위치 추정까지 한 번에 받아온다.
"""

import base64
import io
import json
import os
from pathlib import Path

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

from app.render import render_translated

app = FastAPI(title="Image Translator")

STATIC_DIR = Path(__file__).parent / "static"

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

# GPT가 블록별 원문/번역/위치를 정해진 형식으로만 응답하도록 강제한다
RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "image_translation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "blocks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "translation": {"type": "string"},
                            "x0": {"type": "integer"},
                            "y0": {"type": "integer"},
                            "x1": {"type": "integer"},
                            "y1": {"type": "integer"},
                            "lines": {"type": "integer"},
                        },
                        "required": ["text", "translation", "x0", "y0", "x1", "y1", "lines"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["blocks"],
            "additionalProperties": False,
        },
    },
}


def translate_image_with_gpt(
    image_bytes: bytes,
    mime: str,
    target_lang: str,
    api_key: str,
    model: str,
    glossary: str,
) -> list[dict]:
    """이미지를 GPT에 보내 텍스트 블록(원문/번역/위치) 목록을 받아온다."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)

    glossary_part = ""
    if glossary.strip():
        glossary_part = (
            "\n\nUser dictionary (MUST be applied exactly; format: source=translation):\n"
            + glossary.strip()
        )

    instruction = (
        "Find every distinct text block in the attached image (a block is a title, "
        "a paragraph, a label, a button caption, etc.). For each block report:\n"
        f"- text: the original text exactly as written\n"
        f"- translation: the text translated into {lang_name}. Keep numbers, prices, "
        "and proper nouns accurate\n"
        "- x0, y0, x1, y1: a tight bounding box around the text, in a normalized "
        "coordinate system where (0,0) is the top-left corner of the image and "
        "(1000,1000) is the bottom-right corner\n"
        "- lines: how many visual lines the original text occupies\n"
        "List the blocks in reading order. Do not invent text that is not in the image."
        f"{glossary_part}"
    )

    image_b64 = base64.b64encode(image_bytes).decode()
    resp = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "response_format": RESPONSE_SCHEMA,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional translator that reads text in images precisely, including its position.",
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
        timeout=180,
    )
    if resp.status_code != 200:
        try:
            detail = resp.json()["error"]["message"]
        except Exception:
            detail = resp.text[:300]
        raise RuntimeError(f"OpenAI API 오류 (HTTP {resp.status_code}): {detail}")

    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)["blocks"]


def blocks_to_paragraphs(blocks: list[dict], width: int, height: int) -> list[dict]:
    """GPT의 정규화 좌표(0~1000)를 픽셀 좌표로 바꿔 렌더링용 문단 목록을 만든다."""
    paragraphs = []
    for b in blocks:
        text = str(b.get("text", "")).strip()
        translated = str(b.get("translation", "")).strip()
        if not text or not translated:
            continue
        x0 = round(min(b["x0"], b["x1"]) / 1000 * width)
        x1 = round(max(b["x0"], b["x1"]) / 1000 * width)
        y0 = round(min(b["y0"], b["y1"]) / 1000 * height)
        y1 = round(max(b["y0"], b["y1"]) / 1000 * height)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(width, x1), min(height, y1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        lines = max(1, int(b.get("lines", 1)))
        paragraphs.append({
            "text": text,
            "translated": translated,
            "box": (x0, y0, x1, y1),
            "line_height": (y1 - y0) / lines,
        })
    return paragraphs


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/translate")
async def translate_image(
    file: UploadFile = File(...),
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

    try:
        blocks = translate_image_with_gpt(
            image_bytes=data,
            mime=file.content_type or "image/png",
            target_lang=target_lang,
            api_key=api_key,
            model=model,
            glossary=glossary,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"번역 실패: {e}")

    paragraphs = blocks_to_paragraphs(blocks, image.width, image.height)
    if not paragraphs:
        return {"extracted": "", "translated": "", "image": "", "engine": f"OpenAI {model}", "message": "이미지에서 텍스트를 찾지 못했습니다."}

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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
