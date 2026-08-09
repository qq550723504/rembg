# Model Capability Profiles Design

## Goal

让高级参数的 UI 和 API 契约表达模型能力边界，同时保留 rembg 当前统一的 Alpha Matting 和遮罩后处理能力。

## Design

- `app/models.py` 为每个支持的模型提供能力元数据：分类、公共参数能力、实验性状态和模型专属参数定义。
- `/v1/models` 返回参数定义，前端根据定义动态渲染控件；公共 Alpha Matting 参数继续保留在固定区域。
- `u2net_cloth_seg` 暴露 `cloth_category`（全部、上装、下装、整套）。
- `sam` 暴露 `sam_prompt`（点/矩形 JSON）、`sam_model` 和 `sam_quant`。
- 后端使用相同的参数定义校验模型专属请求，并将其映射为 rembg 的 `cloth_category`、`sam_prompt`、`sam_model` 和 `sam_quant` 参数。
- 未开启 Alpha Matting 时，阈值和腐蚀尺寸不传入实际推理调用。

## Validation

- 模型列表为每个模型返回完整能力字段。
- 服装模型和 SAM 返回不同的 `parameters` 列表，普通模型不返回模型专属参数。
- 错误模型收到模型专属参数时返回 422，不进入推理。
- 模型专属参数能进入实际 rembg 调用，且字段名和类型保持稳定。
- Alpha Matting 关闭时，阈值参数不会进入 rembg 调用；开启时会保留。
- 现有模型选择、请求参数和响应格式保持兼容。
