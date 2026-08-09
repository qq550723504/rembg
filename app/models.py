from typing import Literal, TypedDict

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

MODEL_CATEGORIES = {
    "birefnet-general": "general",
    "birefnet-general-lite": "general",
    "birefnet-portrait": "portrait",
    "birefnet-dis": "salient",
    "birefnet-hrsod": "salient",
    "birefnet-cod": "salient",
    "birefnet-massive": "general",
    "u2net": "general",
    "u2netp": "general",
    "u2net_human_seg": "portrait",
    "u2net_cloth_seg": "clothing",
    "isnet-general-use": "general",
    "isnet-anime": "anime",
    "silueta": "general",
    "sam": "prompt",
    "bria-rmbg": "general",
}


class ModelCapabilities(TypedDict):
    category: str
    supports_alpha_matting: bool
    supports_post_process_mask: bool
    experimental: bool
    parameters: list["ModelParameter"]


class ParameterOption(TypedDict):
    value: str
    label: str


class ModelParameter(TypedDict, total=False):
    name: str
    label: str
    type: Literal["checkbox", "json", "select"]
    default: bool | str | None
    options: list[ParameterOption]
    placeholder: str
    description: str


MODEL_PARAMETER_DEFINITIONS: dict[str, list[ModelParameter]] = {
    "u2net_cloth_seg": [
        {
            "name": "cloth_category",
            "label": "服装类别",
            "type": "select",
            "default": "all",
            "options": [
                {"value": "all", "label": "全部"},
                {"value": "upper", "label": "上装"},
                {"value": "lower", "label": "下装"},
                {"value": "full", "label": "整套"},
            ],
            "description": "选择要保留的服装区域。",
        }
    ],
    "sam": [
        {
            "name": "sam_prompt",
            "label": "SAM 提示点/框",
            "type": "json",
            "default": None,
            "placeholder": '[{"type":"point","label":1,"data":[512,512]}]',
            "description": "JSON 数组；留空时使用图片中心点。",
        },
        {
            "name": "sam_model",
            "label": "SAM 模型规格",
            "type": "select",
            "default": "sam_vit_b_01ec64",
            "options": [
                {"value": "sam_vit_b_01ec64", "label": "ViT-B（推荐）"},
                {"value": "sam_vit_l_0b3195", "label": "ViT-L"},
                {"value": "sam_vit_h_4b8939", "label": "ViT-H"},
            ],
        },
        {
            "name": "sam_quant",
            "label": "使用量化模型",
            "type": "checkbox",
            "default": False,
            "description": "降低显存占用，但可能影响边缘质量。",
        },
    ],
}


MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    name: {
        "category": MODEL_CATEGORIES[name],
        "supports_alpha_matting": True,
        "supports_post_process_mask": True,
        "experimental": name == "sam",
        "parameters": MODEL_PARAMETER_DEFINITIONS.get(name, []),
    }
    for name in SUPPORTED_MODELS
}


class ModelOption(TypedDict):
    name: str
    description: str
    is_default: bool
    capabilities: ModelCapabilities


def model_capabilities(name: str) -> ModelCapabilities:
    return MODEL_CAPABILITIES[name]


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
            "capabilities": model_capabilities(name),
        }
        for name in SUPPORTED_MODELS
    ]
