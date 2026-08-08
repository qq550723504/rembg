from pydantic import BaseModel, Field


class RemovalOptions(BaseModel):
    alpha_matting: bool = False
    alpha_matting_foreground_threshold: int = Field(default=240, ge=0, le=255)
    alpha_matting_background_threshold: int = Field(default=10, ge=0, le=255)
    alpha_matting_erode_size: int = Field(default=10, ge=0, le=255)
    post_process_mask: bool = False

    def to_kwargs(self) -> dict[str, bool | int]:
        return self.model_dump(exclude_defaults=True)
