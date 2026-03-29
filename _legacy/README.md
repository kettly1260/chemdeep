# Legacy 代码

此目录包含重构前的旧版本代码，仅作备份参考。

## 文件说明

| 文件 | 说明 |
|------|------|
| `main.py` | 旧版入口文件 (2000+ 行) |
| `fetcher.py` | 旧版抓取器 (未拆分) |
| `bot_handlers_old.py` | 旧版处理器 (未拆分) |

## 恢复旧版本

如需恢复旧版本：

```powershell
# 备份新版
Move-Item main.py main_v2.py

# 恢复旧版
Copy-Item _legacy\main.py main.py
```

## 注意

旧版代码不再维护，建议使用新版本。
