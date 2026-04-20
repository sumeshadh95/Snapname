from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image, ImageChops, ImageOps
from pytesseract import Output


LOGGER = logging.getLogger(__name__)


class OcrUnavailableError(RuntimeError):
    """Raised when the Tesseract executable is not installed or not on PATH."""


@dataclass(frozen=True)
class OcrResult:
    raw_text: str
    avg_confidence: float
    word_list: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "avg_confidence": self.avg_confidence,
            "word_list": self.word_list,
        }


class TesseractOcrEngine:
    def __init__(
        self,
        min_word_confidence: float = 60.0,
        config: str = "--oem 3 --psm 6",
    ) -> None:
        self.min_word_confidence = min_word_confidence
        self.config = config
        self._configure_tesseract_command()

    def read_image(self, image_path: Path) -> OcrResult:
        try:
            with Image.open(image_path) as image:
                prepared = preprocess_image(image)
                return self._read_prepared_image(prepared)
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrUnavailableError(
                "Tesseract OCR is not installed or is not available on PATH."
            ) from exc
        except OSError:
            LOGGER.exception("Could not open image for OCR: %s", image_path)
            return OcrResult("", 0.0, [])

    def read_header(self, image_path: Path) -> OcrResult:
        try:
            with Image.open(image_path) as image:
                width, height = image.size
                header_height = max(24, int(height * 0.10))
                header = image.crop((0, 0, width, header_height))
                prepared = preprocess_image(header)
                return self._read_prepared_image(prepared)
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrUnavailableError(
                "Tesseract OCR is not installed or is not available on PATH."
            ) from exc
        except OSError:
            LOGGER.exception("Could not OCR image header: %s", image_path)
            return OcrResult("", 0.0, [])

    def _read_prepared_image(self, image: Image.Image) -> OcrResult:
        data = pytesseract.image_to_data(
            image,
            output_type=Output.DICT,
            config=self.config,
        )
        return _parse_tesseract_data(data, self.min_word_confidence)

    def _configure_tesseract_command(self) -> None:
        candidates = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in candidates:
            if candidate.exists():
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
                LOGGER.info("Using Tesseract executable: %s", candidate)
                return


def preprocess_image(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.grayscale(image)
    grayscale = ImageOps.autocontrast(grayscale)

    width, height = grayscale.size
    if width < 1000:
        grayscale = grayscale.resize(
            (width * 2, height * 2),
            Image.Resampling.LANCZOS,
        )

    return adaptive_threshold(grayscale)


def adaptive_threshold(image: Image.Image) -> Image.Image:
    from PIL import ImageFilter

    local_average = image.filter(ImageFilter.GaussianBlur(radius=9))
    difference = ImageChops.subtract(image, local_average, offset=128)
    return difference.point(lambda pixel: 255 if pixel > 121 else 0, mode="1")


def _parse_tesseract_data(
    data: dict[str, list[Any]],
    min_word_confidence: float,
) -> OcrResult:
    line_words: dict[tuple[int, int, int], list[str]] = {}
    word_list: list[str] = []
    confidence_values: list[float] = []

    texts = data.get("text", [])
    confidences = data.get("conf", [])
    blocks = data.get("block_num", [])
    paragraphs = data.get("par_num", [])
    lines = data.get("line_num", [])

    for index, text_value in enumerate(texts):
        text = str(text_value).strip()
        if not text:
            continue

        confidence = _parse_confidence(confidences[index])
        if confidence < min_word_confidence:
            continue

        key = (
            _safe_int(blocks[index]),
            _safe_int(paragraphs[index]),
            _safe_int(lines[index]),
        )
        line_words.setdefault(key, []).append(text)
        word_list.append(text)
        confidence_values.append(confidence / 100.0)

    raw_text = "\n".join(
        " ".join(words)
        for _, words in sorted(line_words.items(), key=lambda item: item[0])
    )
    avg_confidence = (
        sum(confidence_values) / len(confidence_values)
        if confidence_values
        else 0.0
    )
    return OcrResult(
        raw_text=raw_text,
        avg_confidence=avg_confidence,
        word_list=word_list,
    )


def _parse_confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
