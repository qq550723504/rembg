# Model Capability Profiles Design

## Goal

让高级参数的 UI 和 API 契约表达模型能力边界，同时保留 rembg 当前统一的 Alpha Matting 和遮罩后处理能力。

## Design

- `app/models.py` 为每个支持的模型提供能力元数据：分类、是否支持 Alpha Matting、是否支持遮罩后处理、是否实验性。
- 当前 rembg 通用后处理能力对现有模型统一开放；`sam` 标记为实验性，因为当前页面没有提示式输入控件。
- `/v1/models` 返回能力元数据，前端根据元数据更新模型说明，并为未来不支持的能力禁用相应控件。
- 后端以同一份能力元数据校验请求，避免只依赖前端。
- 未开启 Alpha Matting 时，阈值和腐蚀尺寸不传入实际推理调用。

## Validation

- 模型列表为每个模型返回完整能力字段。
- Alpha Matting 关闭时，阈值参数不会进入 rembg 调用；开启时会保留。
- 现有模型选择、请求参数和响应格式保持兼容。
