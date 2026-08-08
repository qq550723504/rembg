from typing import TypedDict

SUPPORTED_MODELS = (
    "birefnet-general",
    "birefnet-general-lite",
    "birefnet-portrait",
    "birefnet-dis",
    "birefnet-hrsod",
    "birefnet-cod",
    "birefnet-massive",
    "u2net",
    "u2netp",
    "u2net_human_seg",
    "u2net_cloth_seg",
    "isnet-general-use",
    "isnet-anime",
    "silueta",
    "sam",
    "bria-rmbg",
)

MODEL_DESCRIPTIONS = {
    "birefnet-general": "通用场景",
    "birefnet-general-lite": "轻量通用，显存占用更低",
    "birefnet-portrait": "人像",
    "birefnet-dis": "显著目标",
    "birefnet-hrsod": "高分辨率显著目标",
    "birefnet-cod": "隐蔽物体",
    "birefnet-massive": "复杂通用场景",
    "u2net": "通用 U²-Net",
    "u2netp": "轻量 U²-Net",
    "u2net_human_seg": "人体分割",
    "u2net_cloth_seg": "服装分割",
    "isnet-general-use": "通用 IS-Net",
    "isnet-anime": "动漫角色",
    "silueta": "轻量通用",
    "sam": "提示式分割",
    "bria-rmbg": "BRIA 背景移除",
}


class ModelOption(TypedDict):
    name: str
    description: str
    is_default: bool


def resolve_model_name(requested: str | None, default: str) -> str:
    name = (requested or default).strip()
    if name not in SUPPORTED_MODELS:
        raise ValueError(f"Unsupported model: {name}")
    return name


def model_options(default: str) -> list[ModelOption]:
    return [
        {
            "name": name,
            "description": MODEL_DESCRIPTIONS[name],
            "is_default": name == default,
        }
        for name in SUPPORTED_MODELS
    ]
