"""OCR 텍스트 블록 추출과 번역문 치환 렌더링."""

import statistics
from pathlib import Path

import pytesseract
from PIL import Image, ImageDraw, ImageFont

# 번역문 렌더링용 폰트 후보 (앞에서부터 탐색)
FONT_CANDIDATES = [
    Path(__file__).parent / "fonts" / "NotoSansKR-Regular.ttf",
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/unifont/unifont.otf"),
]

MIN_CONFIDENCE = 30  # 이 미만 평균 신뢰도의 블록은 노이즈로 간주


def find_font() -> str:
    for path in FONT_CANDIDATES:
        if path.exists():
            return str(path)
    raise RuntimeError("한글을 지원하는 폰트를 찾지 못했습니다.")


def extract_paragraphs(image: Image.Image, lang: str, scale: float = 1.0) -> list[dict]:
    """문단 단위 텍스트 블록을 추출한다. 좌표는 원본 이미지 기준으로 환산."""
    data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    groups: dict[tuple, dict] = {}
    for i, raw in enumerate(data["text"]):
        word = raw.strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i])
        g = groups.setdefault(key, {"words": [], "confs": []})
        g["words"].append({
            "text": word,
            "line": data["line_num"][i],
            "x": data["left"][i],
            "y": data["top"][i],
            "w": data["width"][i],
            "h": data["height"][i],
        })
        g["confs"].append(conf)

    paragraphs = []
    for g in groups.values():
        if statistics.mean(g["confs"]) < MIN_CONFIDENCE:
            continue
        words = g["words"]
        lines: dict[int, list[str]] = {}
        for w in words:
            lines.setdefault(w["line"], []).append(w["text"])
        text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
        x0 = min(w["x"] for w in words)
        y0 = min(w["y"] for w in words)
        x1 = max(w["x"] + w["w"] for w in words)
        y1 = max(w["y"] + w["h"] for w in words)
        paragraphs.append({
            "text": text,
            "box": tuple(round(v / scale) for v in (x0, y0, x1, y1)),
            "line_height": statistics.median(w["h"] for w in words) / scale,
        })
    return paragraphs


def _color_distance(a: tuple, b: tuple) -> float:
    return sum((ca - cb) ** 2 for ca, cb in zip(a, b)) ** 0.5


def estimate_colors(image: Image.Image, box: tuple) -> tuple[tuple, tuple]:
    """블록 영역의 배경색(다수 픽셀)과 글자색(배경과 먼 픽셀)을 추정한다."""
    region = image.crop(box)
    if region.width * region.height > 64 * 64:
        # NEAREST: 안티앨리어싱으로 글자/배경 색이 섞이지 않게 원본 픽셀만 샘플링
        region = region.resize((64, 64), Image.NEAREST)
    pixels = list(region.getdata())
    bg = tuple(int(statistics.median(ch)) for ch in zip(*pixels))
    text_pixels = [p for p in pixels if _color_distance(p, bg) > 80]
    luminance = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    if text_pixels:
        fg = tuple(int(statistics.median(ch)) for ch in zip(*text_pixels))
    else:
        fg = (0, 0, 0) if luminance > 128 else (255, 255, 255)
    if _color_distance(fg, bg) < 60:  # 대비가 부족하면 흑/백으로 강제
        fg = (0, 0, 0) if luminance > 128 else (255, 255, 255)
    return bg, fg


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    """픽셀 폭 기준 줄바꿈. 공백 없는 긴 토큰(CJK)은 글자 단위로 자른다."""
    lines: list[str] = []
    current = ""
    for token in text.split():
        candidate = f"{current} {token}".strip()
        if draw.textlength(candidate, font=font) <= max_w:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        piece = ""
        for ch in token:
            if draw.textlength(piece + ch, font=font) <= max_w:
                piece += ch
            else:
                lines.append(piece)
                piece = ch
        current = piece
    if current:
        lines.append(current)
    return lines or [""]


def _fit_text(draw, text, box_w, box_h, font_path, start_size):
    """블록 안에 들어가도록 폰트 크기를 줄여가며 줄바꿈을 계산한다."""
    size = max(10, round(start_size))
    while size >= 9:
        font = ImageFont.truetype(font_path, size)
        lines = _wrap(draw, text, font, box_w)
        line_h = size * 1.25
        if len(lines) * line_h <= box_h + size * 0.5:
            return font, lines, line_h
        size = round(size * 0.85) if size > 12 else size - 1
    font = ImageFont.truetype(font_path, 9)
    return font, _wrap(draw, text, font, box_w), 11


def render_translated(image: Image.Image, paragraphs: list[dict]) -> Image.Image:
    """원문 블록을 배경색으로 지우고 그 자리에 번역문을 그린다.

    paragraphs 항목: {"box": (x0,y0,x1,y1), "translated": str, "line_height": float}
    """
    out = image.convert("RGB")
    draw = ImageDraw.Draw(out)
    font_path = find_font()
    for p in paragraphs:
        translated = p["translated"].strip()
        if not translated:
            continue
        x0, y0, x1, y1 = p["box"]
        bg, fg = estimate_colors(out, p["box"])
        pad = max(2, round(p["line_height"] * 0.15))
        draw.rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), fill=bg)
        font, lines, line_h = _fit_text(
            draw, translated, x1 - x0, y1 - y0, font_path, p["line_height"] * 0.85
        )
        y = y0
        for line in lines:
            draw.text((x0, y), line, font=font, fill=fg)
            y += line_h
    return out
