from typing import Any

from pydantic import BaseModel, Field

from .models import model_capabilities


class RemovalOptions(BaseModel):
    alpha_matting: bool = False
    alpha_matting_foreground_threshold: int = Field(default=240, ge=0, le=255)
    alpha_matting_background_threshold: int = Field(default=10, ge=0, le=255)
    alpha_matting_erode_size: int = Field(default=10, ge=0, le=255)
    post_process_mask: bool = False
    cloth_category: str | None = None
    sam_prompt: list[dict[str, Any]] | None = None
    sam_model: str | None = None
    sam_quant: bool = False

    def to_kwargs(self) -> dict[str, Any]:
        values = self.model_dump(exclude_defaults=True)
        if not self.alpha_matting:
            values.pop("alpha_matting_foreground_threshold", None)
            values.pop("alpha_matting_background_threshold", None)
            values.pop("alpha_matting_erode_size", None)
        if values.get("cloth_category") == "all":
            values.pop("cloth_category")
        return values

    def validate_for_model(self, model_name: str) -> None:
        capabilities = model_capabilities(model_name)
        if self.alpha_matting and not capabilities["supports_alpha_matting"]:
            raise ValueError(f"Model does not support alpha matting: {model_name}")
        if self.post_process_mask and not capabilities["supports_post_process_mask"]:
            raise ValueError(
                f"Model does not support mask post-processing: {model_name}"
            )

        parameter_names = {
            parameter["name"] for parameter in capabilities["parameters"]
        }
        model_specific_values = {
            "cloth_category": self.cloth_category,
            "sam_prompt": self.sam_prompt,
            "sam_model": self.sam_model,
            "sam_quant": self.sam_quant,
        }
        for name, value in model_specific_values.items():
            if value not in (None, False) and name not in parameter_names:
                raise ValueError(f"Model does not support parameter: {name}")

        if self.cloth_category is not None and self.cloth_category not in {
            "all",
            "upper",
            "lower",
            "full",
        }:
            raise ValueError(f"Unsupported cloth category: {self.cloth_category}")

        if self.sam_model is not None and self.sam_model not in {
            "sam_vit_b_01ec64",
            "sam_vit_l_0b3195",
            "sam_vit_h_4b8939",
        }:
            raise ValueError(f"Unsupported SAM model: {self.sam_model}")

        if self.sam_prompt is not None:
            if not self.sam_prompt:
                raise ValueError("SAM prompt must not be empty")
            for mark in self.sam_prompt:
                if not isinstance(mark, dict):
                    raise ValueError(  # noqa: TRY004 - API validation maps this to HTTP 422
                        "Each SAM prompt mark must be an object"
                    )
                mark_type = mark.get("type")
                data = mark.get("data")
                label = mark.get("label")
                expected_length = {"point": 2, "rectangle": 4}.get(mark_type)
                if expected_length is None:
                    raise ValueError(f"Unsupported SAM prompt type: {mark_type}")
                if not isinstance(data, list) or len(data) != expected_length:
                    raise ValueError(
                        f"SAM {mark_type} prompt data must contain "
                        f"{expected_length} values"
                    )
                if any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    for value in data
                ):
                    raise ValueError("SAM prompt coordinates must be numbers")
                if mark_type == "point" and label not in (0, 1):
                    raise ValueError("SAM point prompt label must be 0 or 1")
