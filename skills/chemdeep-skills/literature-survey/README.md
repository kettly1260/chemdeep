# literature-survey Skill

## 功能简介
- 支持中/英双语，化学/材料领域的系统性文献调研
- 可通过 API、plugin、hook 三种方式调用，接口层支持能力热插拔与扩展

## 接口说明

### API
- 路径：/run
- 方法：POST
- 参数：
  - query: str
  - language: zh/en
  - field: chemistry/materials
  - mode: api
  - extra: dict（可选）

### Plugin
- 入口：plugin_entry(query, language, field, **kwargs)

### Hook
- 支持注册 before_run/after_run 等hook，实现流程扩展

## 示例

```python
from .plugin import plugin_entry
result = plugin_entry("COF 光催化 CO2 还原", language="zh", field="chemistry")
print(result)
```

## 扩展说明
- 支持多语言/多领域参数，未来可扩展更多模型/领域
- API、plugin、hook三类接口可独立或组合使用
- 具体实现见 skill_impl.py
