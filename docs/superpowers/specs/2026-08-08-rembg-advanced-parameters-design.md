# rembg Advanced Removal Parameters Design

## Goal

Expose rembg's supported alpha-matting and mask post-processing controls through the existing upload API, URL API, and Web UI while preserving the current default output and existing clients.

## Scope

The feature adds these optional request parameters:

- `alpha_matting`: boolean, default `false`.
- `alpha_matting_foreground_threshold`: integer `0..255`, default `240`.
- `alpha_matting_background_threshold`: integer `0..255`, default `10`.
- `alpha_matting_erode_size`: integer `0..255`, default `10`.
- `post_process_mask`: boolean, default `false`.

The first version does not expose `only_mask`, `bgcolor`, or SAM-specific point inputs because they would change the current RGBA-PNG response contract or require a separate interaction model.

## API Design

Both `POST /v1/remove-background` and `POST /v1/remove-background/url` accept the five parameters. Multipart requests use form fields; URL requests use JSON fields. FastAPI/Pydantic validation rejects values outside the declared ranges with the existing `422` validation response.

The API maps only these allowlisted fields to rembg. It never forwards arbitrary request keys as `**kwargs`.

When all values are omitted, the service calls the remover using the existing `(data, model_name)` shape. This keeps injected remover implementations and old clients compatible. Non-default values are forwarded only after explicit validation.

## Internal Design

Add a focused `RemovalOptions` Pydantic model that owns defaults, bounds, and conversion to the allowlisted rembg keyword dictionary. The existing `ImageUrlRequest` embeds the same fields, while the upload route declares equivalent typed form fields.

Extend the remover protocol and `RembgRemover` with optional keyword arguments. The production remover passes the validated options to `rembg.remove()` alongside the cached session and `force_return_bytes=True`. Model session creation and caching remain unchanged.

The result remains normalized to RGBA PNG by the existing route layer regardless of the selected options.

## Web UI

Add a collapsed “高级参数” section below model selection with a checkbox for alpha matting, numeric inputs for the three thresholds, and a checkbox for mask post-processing. The controls use the same defaults and browser min/max bounds as the API.

The file and URL request builders serialize the same option names. Existing busy-state behavior disables the new controls while a request is running. The UI does not expose options that are outside this design.

## Testing

- Unit-test `RemovalOptions` defaults, bounds, and allowlisted conversion.
- Verify `RembgRemover` forwards non-default options to the fake rembg function and preserves the existing no-option call.
- Verify both API routes forward validated options to a fake remover.
- Verify invalid threshold values are rejected before remover execution.
- Verify the HTML and JavaScript include the controls and serialize all five fields.
- Run the full test suite, compile check, Ruff, and Docker Compose config validation.

## Error Handling and Compatibility

Parameter validation errors use FastAPI's normal `422` response. Model selection errors remain `400`. Inference errors retain the existing `500` mapping. No new environment variables or dependencies are required.
