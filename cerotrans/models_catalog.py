"""Whisper.cpp ggml model catalog (OpenAI Whisper size table)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import SUPPORT

HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

# Downloadable / selectable models live here (writable).
USER_MODELS_DIR = SUPPORT / "models"


@dataclass(frozen=True)
class ModelInfo:
    label: str
    filename: str
    params: str
    relative_speed: str
    english_only: bool
    size_key: str  # tiny|base|small|medium|large|turbo
    approx_mb: int
    multilingual_sibling: str | None = None  # label of multilingual twin


# Order matches the OpenAI Whisper README size table.
MODELS: tuple[ModelInfo, ...] = (
    ModelInfo("Tiny EN", "ggml-tiny.en.bin", "39 M", "~10x", True, "tiny", 75, "Tiny"),
    ModelInfo("Tiny", "ggml-tiny.bin", "39 M", "~10x", False, "tiny", 75, None),
    ModelInfo("Base EN", "ggml-base.en.bin", "74 M", "~7x", True, "base", 142, "Base"),
    ModelInfo("Base", "ggml-base.bin", "74 M", "~7x", False, "base", 142, None),
    ModelInfo("Small EN", "ggml-small.en.bin", "244 M", "~4x", True, "small", 466, "Small"),
    ModelInfo("Small", "ggml-small.bin", "244 M", "~4x", False, "small", 466, None),
    ModelInfo("Medium EN", "ggml-medium.en.bin", "769 M", "~2x", True, "medium", 1500, "Medium"),
    ModelInfo("Medium", "ggml-medium.bin", "769 M", "~2x", False, "medium", 1500, None),
    ModelInfo("Large", "ggml-large-v3.bin", "1550 M", "1x", False, "large", 3100, None),
    ModelInfo("Turbo", "ggml-large-v3-turbo.bin", "809 M", "~8x", False, "turbo", 1600, None),
)

MODEL_BY_LABEL: dict[str, ModelInfo] = {m.label: m for m in MODELS}
MODEL_FILES: dict[str, str] = {m.label: m.filename for m in MODELS}
DEFAULT_MODEL = "Base EN"

# Bundled in the DMG / repo models/ (always preferred if present)
BUNDLED_LABELS = frozenset({"Tiny EN", "Base EN"})


def model_labels() -> list[str]:
    return [m.label for m in MODELS]


def get_model(label: str) -> ModelInfo:
    if label not in MODEL_BY_LABEL:
        raise KeyError(f"Unknown model: {label}")
    return MODEL_BY_LABEL[label]


def hf_url(filename: str) -> str:
    return f"{HF_BASE}/{filename}"


def multilingual_for(label: str) -> str | None:
    """If label is English-only, return the multilingual sibling label."""
    info = MODEL_BY_LABEL.get(label)
    if info is None:
        return None
    if not info.english_only:
        return label
    return info.multilingual_sibling


def english_only_for_size(size_key: str) -> str | None:
    for m in MODELS:
        if m.size_key == size_key and m.english_only:
            return m.label
    return None


def resolve_model_path(label: str, bundled_dir: Path | None = None) -> Path | None:
    """Return path if the ggml file exists (user dir first, then bundled)."""
    info = get_model(label)
    user = USER_MODELS_DIR / info.filename
    if user.is_file():
        return user
    if bundled_dir is not None:
        bundled = bundled_dir / info.filename
        if bundled.is_file():
            return bundled
    return None


def model_is_available(label: str, bundled_dir: Path | None = None) -> bool:
    return resolve_model_path(label, bundled_dir) is not None
