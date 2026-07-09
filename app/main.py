"""이미지 업로드 → GPT 분석(텍스트 인식·번역) → GPT 이미지 2.0(gpt-image-2)로 번역문 치환 이미지 생성.

1단계(분석): 비전 모델이 이미지와 사용자 사전을 읽고 블록별 원문/번역을 만든다.
2단계(생성): 번역 결과로 조립한 최종 프롬프트를 이미지 편집 API에 보내 치환된 이미지를 받는다.
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

app = FastAPI(title="Image Translator")

STATIC_DIR = Path(__file__).parent / "static"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB

# 테스트나 프록시 환경을 위해 베이스 URL을 바꿀 수 있게 한다
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

ANALYSIS_MODELS = {"fast": "gpt-5.4-mini", "pro": "gpt-5.5"}
GENERATION_MODELS = {"fast": "gpt-image-1-mini", "pro": "gpt-image-2"}

LANG_NAMES = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh-CN": "Simplified Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

ACCURACY_NOTES = {
    "fast": "Translate quickly and naturally.",
    "balanced": "Translate naturally while keeping meaning accurate.",
    "precise": (
        "Carefully verify every number, unit, date, and proper noun. "
        "Prefer precise terminology over fluency. Re-read the image to "
        "double-check ambiguous characters before translating."
    ),
}

ENHANCE_NOTES = {
    "none": "",
    "sharpen": "Also subtly enhance overall sharpness and clean up compression artifacts.",
    "clean": (
        "Also clean up the image: remove noise and compression artifacts, "
        "and make the background around replaced text uniform and tidy."
    ),
}

ANALYSIS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "image_text_translation",
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
                        },
                        "required": ["text", "translation"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["blocks"],
            "additionalProperties": False,
        },
    },
}


def analyze_image(
    image_bytes: bytes,
    mime: str,
    target_lang: str,
    api_key: str,
    model: str,
    glossary: str,
    accuracy: str,
) -> list[dict]:
    """분석 모델로 이미지 속 텍스트 블록(원문/번역)을 추출한다."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)

    glossary_part = ""
    if glossary.strip():
        glossary_part = (
            "\n\nUser dictionary (MUST be applied exactly; format: source=translation):\n"
            + glossary.strip()
        )

    instruction = (
        "Find every distinct piece of text in the attached image (titles, paragraphs, "
        "labels, buttons, captions). For each, report the original text exactly as "
        f"written and its translation into {lang_name}. "
        f"{ACCURACY_NOTES.get(accuracy, ACCURACY_NOTES['balanced'])} "
        "List blocks in reading order. Do not invent text that is not in the image."
        f"{glossary_part}"
    )

    image_b64 = base64.b64encode(image_bytes).decode()
    resp = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "response_format": ANALYSIS_SCHEMA,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional translator that reads text in images precisely.",
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
        raise RuntimeError(f"분석 모델 오류 (HTTP {resp.status_code}): {_api_error(resp)}")

    content = resp.json()["choices"][0]["message"]["content"]
    blocks = json.loads(content)["blocks"]
    return [
        {"text": str(b["text"]).strip(), "translation": str(b["translation"]).strip()}
        for b in blocks
        if str(b.get("text", "")).strip() and str(b.get("translation", "")).strip()
    ]


def build_generation_prompt(blocks: list[dict], target_lang: str, enhance: str) -> str:
    """분석 결과로 이미지 편집(생성) 모델에 보낼 최종 프롬프트를 조립한다."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    lines = "\n".join(
        f'{i + 1}. "{b["text"]}" → "{b["translation"]}"' for i, b in enumerate(blocks)
    )
    prompt = (
        f"Edit this image: replace every piece of visible text with its {lang_name} "
        "translation below, as if the image had originally been made in "
        f"{lang_name}. Keep the layout, font style, text size, colors, and "
        "background exactly the same. Do not alter any non-text elements.\n\n"
        f"Translations to apply:\n{lines}"
    )
    enhance_note = ENHANCE_NOTES.get(enhance, "")
    if enhance_note:
        prompt += f"\n\n{enhance_note}"
    return prompt


def resolve_size(gen_model: str, width: int, height: int, output_size: str) -> str:
    """출력 크기(1k/2k/4k)와 원본 비율로 이미지 API의 size 파라미터를 계산한다."""
    if gen_model == "gpt-image-2":
        long_edge = {"1k": 1024, "2k": 2048, "4k": 3840}.get(output_size, 1024)
        scale = long_edge / max(width, height)
        w, h = width * scale, height * scale
        # gpt-image-2 한계: 최대 3840x2160(가로) / 2160x3840(세로), 비율 1:3~3:1
        max_w, max_h = (3840, 2160) if width >= height else (2160, 3840)
        shrink = min(1.0, max_w / w, max_h / h)
        w, h = w * shrink, h * shrink
        if w / h > 3:
            h = w / 3
        elif h / w > 3:
            w = h / 3
        to16 = lambda v: max(16, round(v / 16) * 16)
        return f"{to16(w)}x{to16(h)}"
    # gpt-image-1 계열은 고정 크기만 지원
    if width > height:
        return "1536x1024"
    if height > width:
        return "1024x1536"
    return "1024x1024"


def generate_image(
    image_bytes: bytes,
    mime: str,
    filename: str,
    prompt: str,
    api_key: str,
    model: str,
    size: str,
) -> bytes:
    """이미지 편집 API(gpt-image-2 등)로 번역문이 반영된 이미지를 생성한다."""
    resp = requests.post(
        f"{OPENAI_BASE_URL}/images/edits",
        headers={"Authorization": f"Bearer {api_key}"},
        files={"image": (filename or "image.png", image_bytes, mime)},
        data={"model": model, "prompt": prompt, "size": size, "n": "1"},
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"생성 모델 오류 (HTTP {resp.status_code}): {_api_error(resp)}")
    return base64.b64decode(resp.json()["data"][0]["b64_json"])


def _api_error(resp: requests.Response) -> str:
    try:
        return resp.json()["error"]["message"]
    except Exception:
        return resp.text[:300]


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/translate")
async def translate_image(
    file: UploadFile = File(...),
    target_lang: str = Form("ko"),
    api_key: str = Form(""),
    analysis_model: str = Form("fast"),
    generation_model: str = Form("pro"),
    accuracy: str = Form("balanced"),
    enhance: str = Form("none"),
    output_size: str = Form("1k"),
    glossary: str = Form(""),
) -> dict:
    api_key = api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API 키를 입력해 주세요.")

    a_model = ANALYSIS_MODELS.get(analysis_model, ANALYSIS_MODELS["fast"])
    g_model = GENERATION_MODELS.get(generation_model, GENERATION_MODELS["pro"])

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

    mime = file.content_type or "image/png"

    # 1단계: 분석 (텍스트 인식 + 번역)
    try:
        blocks = analyze_image(
            image_bytes=data,
            mime=mime,
            target_lang=target_lang,
            api_key=api_key,
            model=a_model,
            glossary=glossary,
            accuracy=accuracy,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"분석 실패: {e}")

    if not blocks:
        return {
            "extracted": "", "translated": "", "prompt": "", "image": "",
            "engine": f"{a_model} + {g_model}",
            "message": "이미지에서 텍스트를 찾지 못했습니다.",
        }

    # 2단계: 최종 프롬프트 조립 → 이미지 생성
    prompt = build_generation_prompt(blocks, target_lang, enhance)
    size = resolve_size(g_model, image.width, image.height, output_size)
    try:
        out_bytes = generate_image(
            image_bytes=data,
            mime=mime,
            filename=file.filename or "image.png",
            prompt=prompt,
            api_key=api_key,
            model=g_model,
            size=size,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"이미지 생성 실패: {e}")

    return {
        "extracted": "\n\n".join(b["text"] for b in blocks),
        "translated": "\n\n".join(b["translation"] for b in blocks),
        "prompt": prompt,
        "image": f"data:image/png;base64,{base64.b64encode(out_bytes).decode()}",
        "engine": f"{a_model} + {g_model} ({size})",
        "message": "",
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
