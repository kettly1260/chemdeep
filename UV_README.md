# ChemDeep - AI驱动的化学研究深度分析工具

## 功能特性

- 🔬 多源文献搜索（OpenAlex、CrossRef、烂番薯学术、Google Scholar）
- 🧠 AI 驱动的需求推理和文献分析
- 📊 论文评分系统（基于期刊、机构、关键词等维度）
- 📅 年份筛选（5年/10年/自定义年份）
- 📝 自动生成研究报告

## 使用 uv 安装

### 1. 安装 uv

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 创建虚拟环境并安装依赖

```bash
cd G:\LLM\chemdeep

# 创建虚拟环境并安装依赖
uv sync

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 安装 Playwright 浏览器
playwright install chromium
```

### 3. 配置环境变量

复制 `.env.example` 到 `.env` 并填写配置：

```bash
cp config/.env.example config/.env
```

### 4. 启动 Bot

```bash
python tg_bot.py
```

## Telegram Bot 命令

### 深度研究

```
/deepresearch 碳硼烷荧光探针合成方法 --year5
/deepresearch Fe3+检测LOD --score 5 --year10
```

### 可选参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--year5` | 只看近5年文献 | `/dr 催化剂 --year5` |
| `--year10` | 只看近10年文献 | `/dr 探针 --year10` |
| `--year N` | 只看N年及以后 | `/dr 合成 --year 2020` |
| `--score N` | 只看评分≥N分的文献 | `/dr 荧光 --score 6` |
| `--max N` | 最大结果数 | `/dr 催化 --max 100` |

## 评分系统

论文评分基于以下维度（0-10分）：

| 维度 | 分值 | 说明 |
|------|------|------|
| 期刊影响力 | 0-3分 | JACS、Angew等顶刊得分更高 |
| 关键词匹配 | 0-3分 | 与研究主题的相关性 |
| 机构权重 | 0-2分 | 知名研究机构加分 |
| 摘要质量 | 0-2分 | 包含量化结果、方法论等 |

评级标准：
- **S级** (≥8.0): 顶刊/高相关性
- **A级** (6.5-8.0): 优质论文
- **B级** (5.0-6.5): 良好论文
- **C级** (3.5-5.0): 一般论文
- **D级** (<3.5): 参考价值较低

## 项目结构

```
chemdeep/
├── apps/
│   └── telegram_bot/    # Telegram Bot 应用
├── core/
│   ├── services/
│   │   └── research/    # 深度研究服务
│   │       ├── paper_scorer.py    # 论文评分器
│   │       ├── search_executor.py # 搜索执行器
│   │       └── iterative_main.py  # 迭代研究主流程
│   ├── scholar_search.py  # 学术搜索（含烂番薯）
│   └── reasoning.py       # 需求推理模块
├── config/
│   └── settings.py       # 配置文件
├── pyproject.toml        # uv 项目配置
└── requirements.txt      # pip 依赖
```

## 开发

```bash
# 安装开发依赖
uv sync --extra dev

# 运行测试
pytest

# 代码格式化
ruff format .
```
