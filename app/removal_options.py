from pydantic import BaseModel, Field

from .models import model_capabilities


class RemovalOptions(BaseModel):
    alpha_matting: bool = False
    alpha_matting_foreground_threshold: int = Field(default=240, ge=0, le=255)
    alpha_matting_background_threshold: int = Field(default=10, ge=0, le=255)
    alpha_matting_erode_size: int = Field(default=10, ge=0, le=255)
    post_process_mask: bool = False

    def to_kwargs(self) -> dict[str, bool | int]:
        values = self.model_dump(exclude_defaults=True)
        if not self.alpha_matting:
            values.pop("alpha_matting_foreground_threshold", None)
            values.pop("alpha_matting_background_threshold", None)
            values.pop("alpha_matting_erode_size", None)
        return values

    def validate_for_model(self, model_name: str) -> None:
        capabilities = model_capabilities(model_name)
        if self.alpha_matting and not capabilities["supports_alpha_matting"]:
            raise ValueError(f"Model does not support alpha matting: {model_name}")
        if self.post_process_mask and not capabilities["supports_post_process_mask"]:
            raise ValueError(
                f"Model does not support mask post-processing: {model_name}"
            )
