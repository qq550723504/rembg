import pytest
from pydantic import ValidationError

from app.removal_options import RemovalOptions


def test_removal_options_use_rembg_defaults_and_omit_default_kwargs():
    options = RemovalOptions()

    assert options.model_dump() == {
        "alpha_matting": False,
        "alpha_matting_foreground_threshold": 240,
        "alpha_matting_background_threshold": 10,
        "alpha_matting_erode_size": 10,
        "post_process_mask": False,
        "cloth_category": None,
        "sam_prompt": None,
        "sam_model": None,
        "sam_quant": False,
    }
    assert options.to_kwargs() == {}


def test_removal_options_convert_non_defaults_to_allowlisted_kwargs():
    options = RemovalOptions(
        alpha_matting=True,
        alpha_matting_foreground_threshold=220,
        post_process_mask=True,
    )

    assert options.to_kwargs() == {
        "alpha_matting": True,
        "alpha_matting_foreground_threshold": 220,
        "post_process_mask": True,
    }


def test_removal_options_serialize_model_specific_kwargs():
    options = RemovalOptions(
        cloth_category="upper",
        sam_prompt=[{"type": "point", "label": 1, "data": [100, 120]}],
        sam_model="sam_vit_b_01ec64",
        sam_quant=True,
    )

    assert options.to_kwargs() == {
        "cloth_category": "upper",
        "sam_prompt": [{"type": "point", "label": 1, "data": [100, 120]}],
        "sam_model": "sam_vit_b_01ec64",
        "sam_quant": True,
    }


@pytest.mark.parametrize(
    "field",
    [
        "alpha_matting_foreground_threshold",
        "alpha_matting_background_threshold",
        "alpha_matting_erode_size",
    ],
)
def test_removal_options_reject_out_of_range_integers(field):
    with pytest.raises(ValidationError):
        RemovalOptions(**{field: 256})
