"""
ChemDeep MCP Server
为 Cherry Studio 和 OpenClaw 提供文献搜索、评分、深度调研与机理推理功能

Skills 概览:
  ─ 文献检索层: search_papers, search_lanfanshu, get_paper_details, score_papers
  ─ 分析推理层: analyze_research_gaps, formalize_research_goal,
                generate_hypotheses, evaluate_hypotheses
  ─ 证据处理层: extract_evidence, cluster_methods
  ─ 验证设计层: design_verification_plan
  ─ 全流程层:   run_deep_research
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, List, Optional
from datetime import datetime

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env 文件
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "config" / ".env")

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("chemdeep-mcp")

FULL_TEXT_FETCH_TIMEOUT_SECONDS = 12.0
FULL_TEXT_FETCH_COLD_START_TIMEOUT_SECONDS = 90.0
FULL_TEXT_FETCH_BROWSER_CDP_PORT = 9222

# 创建 MCP 服务器
server = Server(name="chemdeep", version="0.1.0")

LLM_CONFIG_SCHEMA = {
    "type": "object",
    "title": "llm_config",
    "description": (
        "可选的本次工具调用级 LLM 配置。未传时沿用服务端既有全局配置；"
        "适合由 Cherry Studio 将 /models 选择结果映射为 provider/model/base_url/api_key 后透传。"
        "若 Cherry Studio 对嵌套对象编辑器支持有限，也可直接填写当前工具顶层同名字段。"
    ),
    "properties": {
        "provider": {
            "type": "string",
            "enum": ["openai", "gemini", "auto"],
            "description": "LLM 提供方。建议传 openai、gemini 或 auto。",
            "examples": ["openai", "gemini", "auto"],
        },
        "model": {
            "type": "string",
            "description": "本次调用要使用的模型名称，例如 gpt-4o-mini、gemini-2.0-flash。",
            "examples": ["gpt-4o-mini", "gemini-2.0-flash"],
        },
        "base_url": {
            "type": "string",
            "format": "uri",
            "description": "OpenAI 兼容接口的 base URL，例如 https://api.openai.com/v1。",
            "examples": ["https://api.openai.com/v1"],
        },
        "api_key": {
            "type": "string",
            "format": "password",
            "description": "本次调用使用的 API Key。仅作用于当前请求，不会持久化到服务端全局状态。",
        },
    },
    "additionalProperties": True,
}

REQUEST_LLM_OVERRIDE_PROPERTIES = {
    "provider": {
        "type": "string",
        "enum": ["openai", "gemini", "auto"],
        "description": "本次 analyze_research_gaps 调用级 provider。Cherry Studio 若不便编辑 llm_config，可直接填写这里。",
        "examples": ["openai", "gemini", "auto"],
    },
    "model": {
        "type": "string",
        "description": "本次 analyze_research_gaps 调用级模型名；优先级高于 llm_config.model。",
        "examples": ["gpt-4o-mini", "gemini-2.0-flash"],
    },
    "base_url": {
        "type": "string",
        "format": "uri",
        "description": "本次 analyze_research_gaps 调用级 OpenAI 兼容 base URL；优先级高于 llm_config.base_url。",
        "examples": ["https://api.openai.com/v1"],
    },
    "api_key": {
        "type": "string",
        "format": "password",
        "description": "本次 analyze_research_gaps 调用级 API Key；优先级高于 llm_config.api_key，且不会持久化。",
    },
}


def build_request_llm_config(arguments: dict[str, Any]) -> dict[str, Any] | None:
    """合并 llm_config 与顶层 provider/model/base_url/api_key。"""
    merged: dict[str, Any] = {}

    nested = arguments.get("llm_config")
    if isinstance(nested, dict):
        merged.update(nested)

    for key in ["provider", "model", "base_url", "api_key"]:
        value = arguments.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        merged[key] = value

    return merged or None


# ============================================================
# 工具定义
# ============================================================


@server.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用的工具"""
    return [
        Tool(
            name="search_papers",
            description="通用多源学术论文搜索工具，支持 OpenAlex、CrossRef、烂番薯学术等搜索源；默认返回搜索结果与摘要，不主动抓取全文/正文；仅在显式传入 fetch_full_text=true 时，才会尝试抓取前几篇论文全文/正文；如需明确使用烂番薯学术，优先调用 search_lanfanshu。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或查询语句"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "搜索源: lanfanshu（烂番薯，优先）, openalex, crossref, scholar",
                        "default": ["lanfanshu", "openalex", "crossref"],
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数",
                        "default": 10,
                    },
                    "min_year": {
                        "type": "integer",
                        "description": "最小年份筛选（如 2020）",
                    },
                    "fetch_abstracts": {
                        "type": "boolean",
                        "description": "是否获取摘要（默认 true）",
                        "default": True,
                    },
                    "fetch_full_text": {
                        "type": "boolean",
                        "description": "是否主动抓取论文全文/正文（默认 False；仅显式开启时尝试抓取，失败时自动回退到摘要）",
                        "default": True,
                    },
                    "max_full_texts": {
                        "type": "integer",
                        "description": "最多主动抓取前几篇结果的全文（默认 3）",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_lanfanshu",
            description="烂番薯学术专用搜索工具。该工具会强制仅使用烂番薯学术搜索源，默认返回搜索结果与摘要，不主动抓取全文/正文；仅在显式传入 fetch_full_text=true 时，才会尝试抓取前几篇论文全文/正文，便于 Cherry Studio 明确选择并调用烂番薯。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或查询语句"},
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数",
                        "default": 10,
                    },
                    "min_year": {
                        "type": "integer",
                        "description": "最小年份筛选（如 2020）",
                    },
                    "fetch_abstracts": {
                        "type": "boolean",
                        "description": "是否获取摘要（默认 true）",
                        "default": True,
                    },
                    "fetch_full_text": {
                        "type": "boolean",
                        "description": "是否主动抓取论文全文/正文（默认 false；仅显式开启时尝试抓取，失败时自动回退到摘要）",
                        "default": False,
                    },
                    "max_full_texts": {
                        "type": "integer",
                        "description": "最多主动抓取前几篇结果的全文（默认 3）",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_paper_details",
            description="获取论文的详细信息；默认返回论文元数据与摘要，不主动抓取正文/全文；仅在显式传入 fetch_full_text=true 时，才会尝试抓取正文/全文，失败时自动回退到摘要。",
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {
                        "type": "string",
                        "description": "论文的 DOI",
                    },
                    "title": {
                        "type": "string",
                        "description": "论文标题（无 DOI 时使用）",
                    },
                    "fetch_full_text": {
                        "type": "boolean",
                        "description": "是否主动抓取论文全文/正文（默认 false；仅显式开启时尝试抓取，失败时自动回退到摘要）",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="prepare_live_browser_session",
            description="为受限出版商全文抓取准备实时浏览器会话。该工具会检测本地 Edge/CDP 会话，必要时尝试启动带远程调试端口的 Edge，并返回手动登录/验证码处理指引。它不会绕过付费墙，只复用用户已有授权会话。",
            inputSchema={
                "type": "object",
                "properties": {
                    "launch_if_needed": {
                        "type": "boolean",
                        "description": "若未检测到可用会话，是否自动尝试启动 Edge（默认 true）",
                        "default": True,
                    },
                    "purpose": {
                        "type": "string",
                        "description": "可选，本次准备会话的用途说明，例如 ScienceDirect PDF 下载、全文抓取等。",
                    },
                },
            },
        ),
        Tool(
            name="download_paper_pdf",
            description="按 DOI 通过当前浏览器实时会话下载论文 PDF。适用于 ScienceDirect 等需要登录态或机构授权的站点。调用前建议先执行 prepare_live_browser_session，并确保用户已在浏览器中完成合法登录与验证码处理。",
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {
                        "type": "string",
                        "description": "论文 DOI。优先使用 DOI 来定位文章与 PDF。",
                    },
                    "title": {
                        "type": "string",
                        "description": "可选，论文标题，仅用于返回结果中的可读说明。",
                    },
                },
                "required": ["doi"],
            },
        ),
        Tool(
            name="score_papers",
            description="对论文进行评分，基于期刊影响力、关键词匹配、机构权重等维度",
            inputSchema={
                "type": "object",
                "properties": {
                    "papers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "abstract": {"type": "string"},
                                "source": {"type": "string"},
                                "authors": {"type": "string"},
                                "year": {"type": "integer"},
                                "doi": {"type": "string"},
                            },
                        },
                        "description": "待评分的论文列表",
                    },
                    "min_score": {
                        "type": "number",
                        "description": "最低评分阈值",
                        "default": 0,
                    },
                },
                "required": ["papers"],
            },
        ),
        Tool(
            name="analyze_research_gaps",
            description="分析研究空白和机会。支持通过顶层 provider/model/base_url/api_key 或嵌套 llm_config 指定本次调用级 LLM 配置，便于 Cherry Studio 在工具参数 UI 中显示与填写。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "研究主题"},
                    "papers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "abstract": {"type": "string"},
                                "year": {"type": "integer"},
                            },
                        },
                        "description": "相关论文列表",
                    },
                    **REQUEST_LLM_OVERRIDE_PROPERTIES,
                    "llm_config": LLM_CONFIG_SCHEMA,
                },
                "required": ["topic", "papers"],
            },
        ),
        # ==============================================================
        # 文献调研 Skills
        # ==============================================================
        Tool(
            name="formalize_research_goal",
            description=(
                "【文献调研·第一步】将用户的一句话研究目标形式化为结构化的 ProblemSpec。"
                "输出包含：研究对象(research_object)、可调控变量(control_variables)、"
                "性能指标(performance_metrics)、约束(constraints)、研究领域(domain)。"
                "后续可作为 generate_hypotheses / run_deep_research 的输入。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "研究目标描述（如：设计一种用于检测汞离子的碳硼烷荧光探针）",
                    },
                    "previous_context": {
                        "type": "string",
                        "description": "可选，之前研究的上下文信息（用于在已有研究基础上细化）",
                    },
                    **REQUEST_LLM_OVERRIDE_PROPERTIES,
                    "llm_config": LLM_CONFIG_SCHEMA,
                },
                "required": ["goal"],
            },
        ),
        # ==============================================================
        # 机理假设生成 Skills
        # ==============================================================
        Tool(
            name="generate_hypotheses",
            description=(
                "【机理假设生成】基于形式化的研究问题（ProblemSpec）生成竞争性机理假设。"
                "每个假设包含：机理描述、必需变量、证伪条件、预期性能趋势。"
                "可传入 problem_spec（来自 formalize_research_goal 的输出）或直接传 goal 自动形式化。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "研究目标（与 formalize_research_goal 的 goal 相同；如已传 problem_spec 则可省略）",
                    },
                    "problem_spec": {
                        "type": "object",
                        "description": "来自 formalize_research_goal 的输出（可选；若未传则自动执行形式化）",
                        "properties": {
                            "goal": {"type": "string"},
                            "research_object": {"type": "string"},
                            "control_variables": {"type": "array", "items": {"type": "string"}},
                            "performance_metrics": {"type": "array", "items": {"type": "string"}},
                            "constraints": {"type": "array", "items": {"type": "string"}},
                            "domain": {"type": "string"},
                        },
                    },
                    "abstracts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选的参考文献摘要列表，用于启发假设生成",
                    },
                    **REQUEST_LLM_OVERRIDE_PROPERTIES,
                    "llm_config": LLM_CONFIG_SCHEMA,
                },
                "required": [],
            },
        ),
        # ==============================================================
        # 证据提取 Skills
        # ==============================================================
        Tool(
            name="extract_evidence",
            description=(
                "【证据提取】从论文列表中提取结构化证据（Evidence）。"
                "每条证据包含：技术路线(implementation)、关键变量(key_variables)、"
                "性能结果(performance_results)、局限性(limitations)、方法类别(method_category)。"
                "需要传入 problem_spec 以指导提取方向。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "papers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "abstract": {"type": "string"},
                                "doi": {"type": "string"},
                                "year": {"type": "integer"},
                                "full_content": {"type": "string"},
                            },
                        },
                        "description": "待提取证据的论文列表",
                    },
                    "problem_spec": {
                        "type": "object",
                        "description": "来自 formalize_research_goal 的输出",
                        "properties": {
                            "goal": {"type": "string"},
                            "research_object": {"type": "string"},
                            "control_variables": {"type": "array", "items": {"type": "string"}},
                            "performance_metrics": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    **REQUEST_LLM_OVERRIDE_PROPERTIES,
                    "llm_config": LLM_CONFIG_SCHEMA,
                },
                "required": ["papers", "problem_spec"],
            },
        ),
        # ==============================================================
        # 假设评估 Skills
        # ==============================================================
        Tool(
            name="evaluate_hypotheses",
            description=(
                "【假设评估/证伪】基于已提取的证据评估机理假设的有效性。"
                "返回每个假设的状态(active/rejected)、支持证据数、冲突证据数、证伪原因。"
                "需要传入 hypotheses（来自 generate_hypotheses）和 evidence（来自 extract_evidence）。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "hypotheses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "hypothesis_id": {"type": "string"},
                                "mechanism_description": {"type": "string"},
                                "required_variables": {"type": "array", "items": {"type": "string"}},
                                "irrelevant_variables": {"type": "array", "items": {"type": "string"}},
                                "falsifiable_conditions": {"type": "array", "items": {"type": "string"}},
                                "expected_performance_trend": {"type": "string"},
                            },
                        },
                        "description": "机理假设列表（来自 generate_hypotheses 输出的 hypotheses 字段）",
                    },
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "implementation": {"type": "string"},
                                "key_variables": {"type": "object"},
                                "performance_results": {"type": "object"},
                                "limitations": {"type": "array", "items": {"type": "string"}},
                                "paper_title": {"type": "string"},
                                "doi": {"type": "string"},
                            },
                        },
                        "description": "证据列表（来自 extract_evidence 输出的 evidence 字段）",
                    },
                    **REQUEST_LLM_OVERRIDE_PROPERTIES,
                    "llm_config": LLM_CONFIG_SCHEMA,
                },
                "required": ["hypotheses", "evidence"],
            },
        ),
        # ==============================================================
        # 方法归并 Skills
        # ==============================================================
        Tool(
            name="cluster_methods",
            description=(
                "【方法归并】将提取的证据按技术路线/机理进行归并分类。"
                "返回技术路线簇(MethodCluster)列表，每个簇包含：机理类型、核心思路、"
                "优势/局限、创新切入点、综合评分等。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "implementation": {"type": "string"},
                                "key_variables": {"type": "object"},
                                "performance_results": {"type": "object"},
                                "limitations": {"type": "array", "items": {"type": "string"}},
                                "method_category": {"type": "string"},
                                "paper_title": {"type": "string"},
                            },
                        },
                        "description": "证据列表（来自 extract_evidence 输出）",
                    },
                    **REQUEST_LLM_OVERRIDE_PROPERTIES,
                    "llm_config": LLM_CONFIG_SCHEMA,
                },
                "required": ["evidence"],
            },
        ),
        # ==============================================================
        # 证据验证设计 Skills
        # ==============================================================
        Tool(
            name="design_verification_plan",
            description=(
                "【证据验证设计】基于机理假设和已有证据，设计实验/计算验证方案。"
                "为每个活跃假设生成：关键实验方案、对照组设计、预期结果判据、"
                "计算模拟建议、所需材料/设备清单。适合用于指导后续实验设计。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "研究目标",
                    },
                    "hypotheses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "hypothesis_id": {"type": "string"},
                                "mechanism_description": {"type": "string"},
                                "required_variables": {"type": "array", "items": {"type": "string"}},
                                "falsifiable_conditions": {"type": "array", "items": {"type": "string"}},
                                "expected_performance_trend": {"type": "string"},
                                "status": {"type": "string"},
                            },
                        },
                        "description": "机理假设列表",
                    },
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "implementation": {"type": "string"},
                                "key_variables": {"type": "object"},
                                "performance_results": {"type": "object"},
                                "paper_title": {"type": "string"},
                            },
                        },
                        "description": "已有证据列表（可选；有则基于证据gap设计）",
                    },
                    "method_clusters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "mechanism_type": {"type": "string"},
                                "core_idea": {"type": "string"},
                                "advantages": {"type": "array", "items": {"type": "string"}},
                                "limitations": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                        "description": "技术路线簇列表（可选；来自 cluster_methods 输出）",
                    },
                    **REQUEST_LLM_OVERRIDE_PROPERTIES,
                    "llm_config": LLM_CONFIG_SCHEMA,
                },
                "required": ["goal", "hypotheses"],
            },
        ),
        # ==============================================================
        # 全流程深度研究 Skills
        # ==============================================================
        Tool(
            name="run_deep_research",
            description=(
                "【全流程深度研究】一键执行完整的迭代式深度文献调研流程。"
                "流程：目标形式化 → 机理假设生成 → 文献检索 → 全文获取 → 证据提取 → "
                "假设评估/证伪 → 方法归并 → 充分性判断 → (迭代扩展) → 生成研究报告。"
                "注意：此工具耗时较长（通常数分钟），适合完整的文献调研任务。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "研究目标（如：调研碳硼烷荧光探针的设计策略与检测机理）",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "最大迭代轮次（默认 3，每轮扩展检索范围）",
                        "default": 3,
                    },
                    "min_year": {
                        "type": "integer",
                        "description": "最小年份筛选（如 2020 表示只保留 2020 年及以后的论文）",
                    },
                    "min_score": {
                        "type": "number",
                        "description": "最低论文评分阈值（0-10），低于此分的论文将被过滤",
                        "default": 0.0,
                    },
                    "previous_context": {
                        "type": "string",
                        "description": "之前研究的上下文信息（用于在已有研究基础上深化）",
                    },
                    **REQUEST_LLM_OVERRIDE_PROPERTIES,
                    "llm_config": LLM_CONFIG_SCHEMA,
                },
                "required": ["goal"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """调用工具"""
    if name == "search_papers":
        return await handle_search_papers(arguments)
    elif name == "search_lanfanshu":
        return await handle_search_lanfanshu(arguments)
    elif name == "get_paper_details":
        return await handle_get_paper_details(arguments)
    elif name == "prepare_live_browser_session":
        return await handle_prepare_live_browser_session(arguments)
    elif name == "download_paper_pdf":
        return await handle_download_paper_pdf(arguments)
    elif name == "score_papers":
        return await handle_score_papers(arguments)
    elif name == "analyze_research_gaps":
        return await handle_analyze_gaps(arguments)
    # ── 文献调研 & 机理假设 & 证据验证 Skills ──
    elif name == "formalize_research_goal":
        return await handle_formalize_research_goal(arguments)
    elif name == "generate_hypotheses":
        return await handle_generate_hypotheses(arguments)
    elif name == "extract_evidence":
        return await handle_extract_evidence(arguments)
    elif name == "evaluate_hypotheses":
        return await handle_evaluate_hypotheses(arguments)
    elif name == "cluster_methods":
        return await handle_cluster_methods(arguments)
    elif name == "design_verification_plan":
        return await handle_design_verification_plan(arguments)
    elif name == "run_deep_research":
        return await handle_run_deep_research(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")


# ============================================================
# 工具实现
# ============================================================


def clean_paper(paper: dict) -> dict:
    """清理论文数据，确保类型正确"""
    cleaned = {}

    # 确保字符串字段不为 None
    for field in ["title", "abstract", "source", "journal", "authors", "doi", "url"]:
        val = paper.get(field)
        cleaned[field] = str(val) if val is not None else ""

    # 确保 year 是整数或 None
    year = paper.get("year")
    if year is not None:
        try:
            cleaned["year"] = int(str(year)[:4])
        except (ValueError, TypeError):
            cleaned["year"] = None
    else:
        cleaned["year"] = None

    # 保留其他字段
    for key in paper:
        if key not in cleaned:
            cleaned[key] = paper[key]

    return cleaned


def execute_search_source(
    mcp: Any, query: str, source: str, max_results: int
) -> dict[str, Any]:
    """根据 source 分派到底层搜索实现"""
    if source == "lanfanshu":
        return mcp.search_lanfanshu(query, max_results)
    if source == "openalex":
        return mcp.search_openalex(query, max_results)
    if source == "crossref":
        return mcp.search_papers(query, "crossref", max_results)
    if source == "scholar":
        return mcp.search_google_scholar(query, max_results)
    return mcp.search_papers(query, source, max_results)


async def run_search_request(
    arguments: dict,
    *,
    requested_tool: str,
    forced_sources: Optional[list[str]] = None,
) -> list[TextContent]:
    """执行论文搜索请求，并支持显式指定搜索源"""
    query = arguments.get("query", "")
    provided_sources = arguments.get("sources")
    max_results = arguments.get("max_results", 10)
    min_year = arguments.get("min_year")
    fetch_abstracts = arguments.get("fetch_abstracts", True)
    fetch_full_text = arguments.get("fetch_full_text", False)
    max_full_texts = arguments.get("max_full_texts", 3)

    search_sources = (
        list(forced_sources)
        if forced_sources is not None
        else (provided_sources or ["lanfanshu", "openalex", "crossref"])
    )

    logger.info(
        "MCP search request: tool=%s, query=%s, requested_sources=%s, actual_sources=%s, fetch_abstracts=%s, fetch_full_text=%s, max_full_texts=%s",
        requested_tool,
        query,
        provided_sources,
        search_sources,
        fetch_abstracts,
        fetch_full_text,
        max_full_texts,
    )

    try:
        from core.mcp_search import MCPSearcher

        mcp = MCPSearcher()
        all_papers = []

        for source in search_sources:
            logger.info(
                "MCP search dispatch: tool=%s -> source=%s",
                requested_tool,
                source,
            )
            try:
                result = execute_search_source(mcp, query, source, max_results * 2)
                if result.get("success"):
                    source_papers = result.get("papers", [])
                    all_papers.extend(source_papers)
                    logger.info(
                        "MCP search success: tool=%s, source=%s, papers=%s",
                        requested_tool,
                        source,
                        len(source_papers),
                    )
                else:
                    logger.warning(
                        "MCP search returned failure: tool=%s, source=%s, error=%s",
                        requested_tool,
                        source,
                        result.get("error"),
                    )
            except Exception as e:
                logger.warning(
                    "MCP search failed: tool=%s, source=%s, error=%s",
                    requested_tool,
                    source,
                    e,
                )

        papers = [clean_paper(p) for p in all_papers]

        seen_dois = set()
        unique_papers = []
        for p in papers:
            doi = (p.get("doi") or "").lower().strip()
            if doi and doi in seen_dois:
                continue
            if doi:
                seen_dois.add(doi)
            unique_papers.append(p)
        papers = unique_papers

        if fetch_abstracts:
            papers = await fetch_missing_abstracts(papers, max_count=min(len(papers), 10))

        if min_year:
            from core.services.research.paper_scorer import paper_scorer

            papers = paper_scorer.filter_by_year(papers, min_year=min_year)

        from core.services.research.paper_scorer import paper_scorer

        for paper in papers:
            try:
                score_result = paper_scorer.score_paper(paper)
                paper["score"] = score_result["score"]
                paper["level"] = score_result["level"]
            except Exception as e:
                logger.warning(f"评分失败: {e}")
                paper["score"] = 0
                paper["level"] = "D"

        papers.sort(key=lambda x: x.get("score", 0) or 0, reverse=True)
        papers = papers[:max_results]

        full_text_fetch_status = None
        if fetch_full_text:
            full_text_fetch_status = {
                "requested": True,
                "status": "pending",
                "max_full_texts": max_full_texts,
                "timeout_seconds": FULL_TEXT_FETCH_TIMEOUT_SECONDS,
            }
            papers = await enrich_papers_with_full_text(
                papers,
                max_count=max_full_texts,
                preview_chars=2000,
                timeout_seconds=FULL_TEXT_FETCH_TIMEOUT_SECONDS,
                status=full_text_fetch_status,
            )

        output = {
            "success": True,
            "requested_tool": requested_tool,
            "query": query,
            "total_found": len(papers),
            "sources_used": search_sources,
            "papers": papers,
        }
        if full_text_fetch_status is not None:
            output["full_text_fetch"] = full_text_fetch_status

        return [
            TextContent(
                type="text", text=json.dumps(output, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(
            "MCP search request failed: tool=%s, error=%s",
            requested_tool,
            e,
            exc_info=True,
        )
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "success": False,
                        "requested_tool": requested_tool,
                        "error": str(e),
                    }
                ),
            )
        ]


async def handle_search_papers(arguments: dict) -> list[TextContent]:
    """处理通用论文搜索请求"""
    return await run_search_request(arguments, requested_tool="search_papers")


async def handle_search_lanfanshu(arguments: dict) -> list[TextContent]:
    """处理烂番薯学术专用搜索请求"""
    return await run_search_request(
        arguments,
        requested_tool="search_lanfanshu",
        forced_sources=["lanfanshu"],
    )


async def fetch_missing_abstracts(
    papers: list[dict], max_count: int = 10
) -> list[dict]:
    """获取缺失摘要的论文摘要"""
    import httpx

    updated_papers = []
    fetched_count = 0

    for paper in papers:
        should_fetch = fetched_count < max_count

        # 如果已有摘要，直接保留
        if paper.get("abstract") and len(paper["abstract"]) > 50:
            updated_papers.append(paper)
            continue

        # 仅对前 max_count 篇缺摘要论文做补抓，其余原样保留
        doi = paper.get("doi", "")
        if should_fetch and doi:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    # CrossRef API
                    url = f"https://api.crossref.org/works/{doi}"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json().get("message", {})
                        abstract = data.get("abstract", "")
                        if abstract:
                            # 清理 HTML 标签
                            import re

                            abstract = re.sub(r"<[^>]+>", "", abstract)
                            paper["abstract"] = abstract
                            logger.info(f"获取摘要成功: {paper.get('title', '')[:50]}")
            except Exception as e:
                logger.warning(f"获取摘要失败 ({doi}): {e}")
            finally:
                fetched_count += 1

        updated_papers.append(paper)

    return updated_papers


async def resolve_full_text_fetch_timeout(
    timeout_seconds: float,
) -> tuple[float, str, bool]:
    """根据浏览器/CDP 是否已就绪，决定全文抓取使用的总超时。"""
    try:
        from core.browser.edge_launcher import is_real_browser_running

        browser_ready = await asyncio.to_thread(
            is_real_browser_running,
            FULL_TEXT_FETCH_BROWSER_CDP_PORT,
        )
    except Exception as exc:
        logger.warning("检查 Edge/CDP 就绪状态失败，将按冷启动超时处理: %s", exc)
        browser_ready = False

    if browser_ready:
        return timeout_seconds, "warm", True

    effective_timeout_seconds = max(
        timeout_seconds,
        FULL_TEXT_FETCH_COLD_START_TIMEOUT_SECONDS,
    )
    return effective_timeout_seconds, "cold_start", False



def apply_full_text_fallback_status(
    papers: list[dict],
    attempted_dois: set[str],
    *,
    status: str,
    timeout_seconds: float,
    timeout_mode: str,
    browser_ready: bool,
    message: str,
) -> None:
    """为已尝试全文抓取的论文标记降级状态。"""
    for paper in papers:
        doi = (paper.get("doi") or "").strip().lower()
        if doi not in attempted_dois:
            continue

        paper["full_text_fetch_attempted"] = True
        paper["full_text_fetched"] = False
        paper["full_text_fetch_status"] = status
        paper["full_text_fetch_fallback"] = True
        paper["full_text_fetch_timeout_seconds"] = timeout_seconds
        paper["full_text_fetch_timeout_mode"] = timeout_mode
        paper["full_text_fetch_browser_ready"] = browser_ready
        paper["full_text_fetch_message"] = message


async def enrich_papers_with_full_text(
    papers: list[dict],
    max_count: int = 3,
    preview_chars: int = 2000,
    timeout_seconds: float = FULL_TEXT_FETCH_TIMEOUT_SECONDS,
    status: Optional[dict[str, Any]] = None,
) -> list[dict]:
    """主动抓取前几篇论文的正文/全文，并将结果回填到 paper dict。"""
    if status is not None:
        status.update(
            {
                "attempted": False,
                "attempted_count": 0,
                "fetched_count": 0,
                "requested_timeout_seconds": timeout_seconds,
                "timeout_seconds": timeout_seconds,
                "timeout_mode": "pending",
                "browser_ready": None,
            }
        )

    if not papers or max_count <= 0:
        if status is not None:
            status.update(
                {
                    "status": "skipped",
                    "message": "未找到可执行全文抓取的论文。",
                }
            )
        return papers

    candidates: list[dict] = []
    for paper in papers:
        doi = (paper.get("doi") or "").strip()
        if doi:
            candidates.append(dict(paper))
        if len(candidates) >= max_count:
            break

    attempted_dois = {
        (paper.get("doi") or "").strip().lower() for paper in candidates if paper.get("doi")
    }

    if status is not None:
        status.update(
            {
                "attempted": bool(candidates),
                "attempted_count": len(candidates),
            }
        )

    if not candidates:
        if status is not None:
            status.update(
                {
                    "status": "skipped",
                    "message": "候选论文缺少 DOI，已跳过全文抓取。",
                }
            )
        return papers

    effective_timeout_seconds, timeout_mode, browser_ready = (
        await resolve_full_text_fetch_timeout(timeout_seconds)
    )
    if status is not None:
        status.update(
            {
                "timeout_seconds": effective_timeout_seconds,
                "timeout_mode": timeout_mode,
                "browser_ready": browser_ready,
            }
        )

    try:
        from core.services.research.content_fetch import fetch
        from core.services.research.core_types import IterativeResearchState

        state = IterativeResearchState(paper_pool=candidates)
        state = await asyncio.wait_for(
            asyncio.to_thread(
                fetch,
                state,
                interaction_callback=None,
                cancel_callback=None,
            ),
            timeout=effective_timeout_seconds,
        )

        fetched_by_doi: dict[str, dict] = {}
        for fetched in state.paper_pool:
            doi = (fetched.get("doi") or "").strip().lower()
            if doi:
                fetched_by_doi[doi] = fetched

        fetched_count = 0
        for paper in papers:
            doi = (paper.get("doi") or "").strip().lower()
            if doi not in attempted_dois:
                continue

            paper["full_text_fetch_attempted"] = True
            paper["full_text_fetch_fallback"] = False
            paper["full_text_fetch_timeout_seconds"] = effective_timeout_seconds
            paper["full_text_fetch_timeout_mode"] = timeout_mode
            paper["full_text_fetch_browser_ready"] = browser_ready

            fetched = fetched_by_doi.get(doi)
            if not fetched:
                paper["full_text_fetched"] = False
                paper["full_text_fetch_status"] = "not_found"
                continue

            for field in [
                "library_id",
                "content_level",
                "content_source",
                "content_complete",
                "full_content_path",
                "pdf_path",
                "abstract_path",
            ]:
                value = fetched.get(field)
                if value not in (None, ""):
                    paper[field] = value

            full_content = fetched.get("full_content") or ""
            paper["full_text_fetched"] = bool(
                full_content
                or fetched.get("full_content_path")
                or fetched.get("pdf_path")
            )
            paper["full_text_fetch_status"] = (
                "fetched" if paper["full_text_fetched"] else "not_found"
            )

            if paper["full_text_fetched"]:
                fetched_count += 1

            if full_content:
                paper["full_content_preview"] = full_content[:preview_chars]
                paper["full_content_length"] = len(full_content)

        if status is not None:
            strategy_label = "热启动" if timeout_mode == "warm" else "冷启动"
            status.update(
                {
                    "status": "completed",
                    "fetched_count": fetched_count,
                    "message": (
                        f"全文抓取已采用{strategy_label}超时策略，并在 {effective_timeout_seconds:.1f}s 的时间边界内完成。"
                        if fetched_count
                        else f"全文抓取已采用{strategy_label}超时策略，并在 {effective_timeout_seconds:.1f}s 的时间边界内完成，但未附加到可用全文。"
                    ),
                }
            )
        return papers
    except asyncio.TimeoutError:
        strategy_label = "热启动" if timeout_mode == "warm" else "冷启动"
        message = (
            f"全文抓取采用{strategy_label}超时策略，超过 {effective_timeout_seconds:.1f}s，已回退为原始搜索/详情结果。"
        )
        logger.warning(message)
        apply_full_text_fallback_status(
            papers,
            attempted_dois,
            status="timeout",
            timeout_seconds=effective_timeout_seconds,
            timeout_mode=timeout_mode,
            browser_ready=browser_ready,
            message=message,
        )
        if status is not None:
            status.update(
                {
                    "status": "timeout",
                    "message": message,
                }
            )
        return papers
    except Exception as e:
        strategy_label = "热启动" if timeout_mode == "warm" else "冷启动"
        message = f"主动抓取全文失败（{strategy_label}超时策略），将继续返回摘要结果: {e}"
        logger.warning(message)
        apply_full_text_fallback_status(
            papers,
            attempted_dois,
            status="error",
            timeout_seconds=effective_timeout_seconds,
            timeout_mode=timeout_mode,
            browser_ready=browser_ready,
            message=message,
        )
        if status is not None:
            status.update(
                {
                    "status": "error",
                    "message": message,
                }
            )
        return papers


async def handle_get_paper_details(arguments: dict) -> list[TextContent]:
    """获取论文详细信息"""
    doi = arguments.get("doi", "")
    title = arguments.get("title", "")
    fetch_full_text = arguments.get("fetch_full_text", False)

    logger.info(f"获取论文详情: DOI={doi}, Title={title[:50] if title else ''}")

    try:
        import httpx

        result = {"success": False, "paper": None}

        # 通过 DOI 获取详情
        if doi:
            async with httpx.AsyncClient(timeout=20) as client:
                # CrossRef API
                url = f"https://api.crossref.org/works/{doi}"
                resp = await client.get(url)

                if resp.status_code == 200:
                    data = resp.json().get("message", {})

                    # 提取作者
                    authors = []
                    for author in data.get("author", []):
                        name = f"{author.get('given', '')} {author.get('family', '')}".strip()
                        if name:
                            authors.append(name)

                    # 提取摘要
                    abstract = data.get("abstract", "")
                    import re

                    abstract = re.sub(r"<[^>]+>", "", abstract)

                    # 提取日期
                    pub_date = data.get(
                        "published-print", data.get("published-online", {})
                    )
                    year = None
                    if pub_date and pub_date.get("date-parts"):
                        year = (
                            pub_date["date-parts"][0][0]
                            if pub_date["date-parts"]
                            else None
                        )

                    paper = {
                        "title": data.get("title", [""])[0]
                        if data.get("title")
                        else title,
                        "authors": ", ".join(authors),
                        "abstract": abstract,
                        "doi": doi,
                        "year": year,
                        "source": data.get("container-title", [""])[0]
                        if data.get("container-title")
                        else "",
                        "url": data.get("URL", ""),
                        "cited_by_count": data.get("is-referenced-by-count", 0),
                        "type": data.get("type", ""),
                    }

                    result = {"success": True, "paper": clean_paper(paper)}

        # 如果 CrossRef 失败，尝试 Semantic Scholar
        if not result["success"] and doi:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,authors,abstract,year,citationCount,venue,externalIds"
                    resp = await client.get(url)

                    if resp.status_code == 200:
                        data = resp.json()

                        authors = [a.get("name", "") for a in data.get("authors", [])]

                        paper = {
                            "title": data.get("title", title),
                            "authors": ", ".join(authors),
                            "abstract": data.get("abstract", ""),
                            "doi": doi,
                            "year": data.get("year"),
                            "source": data.get("venue", ""),
                            "url": f"https://www.doi.org/{doi}",
                            "cited_by_count": data.get("citationCount", 0),
                        }

                        result = {"success": True, "paper": clean_paper(paper)}
            except Exception as e:
                logger.warning(f"Semantic Scholar 查询失败: {e}")

        if result.get("success") and result.get("paper") and fetch_full_text:
            full_text_fetch_status = {
                "requested": True,
                "status": "pending",
                "max_full_texts": 1,
                "timeout_seconds": FULL_TEXT_FETCH_TIMEOUT_SECONDS,
            }
            enriched = await enrich_papers_with_full_text(
                [result["paper"]],
                max_count=1,
                preview_chars=8000,
                timeout_seconds=FULL_TEXT_FETCH_TIMEOUT_SECONDS,
                status=full_text_fetch_status,
            )
            result["paper"] = enriched[0]
            result["full_text_fetch"] = full_text_fetch_status

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"获取详情失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_prepare_live_browser_session(arguments: dict) -> list[TextContent]:
    """准备实时浏览器会话，用于受限站点全文抓取与 PDF 下载。"""
    launch_if_needed = arguments.get("launch_if_needed", True)
    purpose = arguments.get("purpose", "")

    try:
        from core.browser.edge_launcher import is_real_browser_running, launch_real_edge_with_cdp

        browser_ready = await asyncio.to_thread(
            is_real_browser_running,
            FULL_TEXT_FETCH_BROWSER_CDP_PORT,
        )
        launch_attempted = False
        launch_message = ""

        if not browser_ready and launch_if_needed:
            launch_attempted = True
            launch_success, launch_message = await asyncio.to_thread(
                launch_real_edge_with_cdp,
                FULL_TEXT_FETCH_BROWSER_CDP_PORT,
            )
            browser_ready = launch_success

        status = "ready" if browser_ready else "manual_action_required"
        result = {
            "success": browser_ready,
            "status": status,
            "purpose": purpose,
            "debug_port": FULL_TEXT_FETCH_BROWSER_CDP_PORT,
            "browser_ready": browser_ready,
            "launch_attempted": launch_attempted,
            "launch_if_needed": launch_if_needed,
            "launch_message": launch_message,
            "legal_notice": "该能力不会绕过付费墙，只会复用用户已合法获得授权的浏览器会话。",
            "instructions": [
                "如 Edge 已打开，请在同一会话中完成出版社/机构登录。",
                "如遇 Cloudflare 或验证码，请手动在浏览器里完成验证。",
                "建议先打开目标文章页，并点击一次 View PDF / Download PDF，以便建立有效会话。",
                "保持该浏览器窗口开启后，再调用 download_paper_pdf 或带 fetch_full_text=true 的工具。",
            ],
        }

        if launch_message == "PROFILE_LOCKED":
            result["error"] = "检测到系统中已有 Edge 进程但未开放 CDP 端口，请关闭冲突 Edge 进程后重试，或手动按远程调试方式启动专用会话。"
        elif not browser_ready and launch_attempted and launch_message:
            result["error"] = launch_message

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]
    except Exception as e:
        logger.error(f"准备实时浏览器会话失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_download_paper_pdf(arguments: dict) -> list[TextContent]:
    """通过当前浏览器实时会话下载单篇论文 PDF。"""
    doi = arguments.get("doi", "")
    title = arguments.get("title", "")

    try:
        from core.services.research.content_fetch import download_pdf_for_paper

        result = await asyncio.to_thread(download_pdf_for_paper, doi, title, None)
        result["legal_notice"] = "该工具仅复用当前浏览器中的合法授权会话，不会尝试绕过付费墙或创建新权限。"
        result["recommended_next_steps"] = [
            "如下载失败，先调用 prepare_live_browser_session 并在浏览器里完成登录/验证。",
            "如已具备会话，也可使用 get_paper_details(fetch_full_text=true) 或 search_papers(fetch_full_text=true) 抓取正文预览。",
        ]
        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]
    except Exception as e:
        logger.error(f"PDF 下载失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_score_papers(arguments: dict) -> list[TextContent]:
    """处理论文评分请求"""
    papers = arguments.get("papers", [])
    min_score = arguments.get("min_score", 0)

    logger.info(f"评分 {len(papers)} 篇论文")

    try:
        from core.services.research.paper_scorer import paper_scorer

        # 清理数据
        papers = [clean_paper(p) for p in papers]

        # 评分并筛选
        scored_papers = paper_scorer.score_and_filter(
            papers, min_score=float(min_score), sort_by="score"
        )

        # 生成摘要
        summary = paper_scorer.get_score_summary(scored_papers)

        output = {
            "success": True,
            "total_scored": len(scored_papers),
            "summary": summary,
            "papers": scored_papers,
        }

        return [
            TextContent(
                type="text", text=json.dumps(output, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"评分失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_analyze_gaps(arguments: dict) -> list[TextContent]:
    """处理研究空白分析请求"""
    topic = arguments.get("topic", "")
    papers = arguments.get("papers", [])

    logger.info(f"分析研究空白: {topic}")

    try:
        from core.reasoning import LiteratureGapAnalyzer
        from core.ai import create_ai_client

        llm_config = build_request_llm_config(arguments)
        ai = create_ai_client(llm_config=llm_config)
        analyzer = LiteratureGapAnalyzer(ai_client=ai)

        # 清理数据
        papers = [clean_paper(p) for p in papers]

        result = analyzer.analyze_gaps(topic, papers)

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"分析失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


# ============================================================
# 文献调研 / 机理假设 / 证据验证 Skills 实现
# ============================================================

# ── 证据验证设计 Prompt ──

VERIFICATION_PLAN_PROMPT = '''你是一位资深的科研方法学专家。请基于以下机理假设和已有证据，为每个活跃假设设计严谨的实验/计算验证方案。

## 研究目标
{goal}

## 机理假设
{hypotheses_text}

## 已有证据
{evidence_text}

## 技术路线簇
{clusters_text}

请返回 JSON 格式结果：
{{
  "verification_plans": [
    {{
      "hypothesis_id": "H1",
      "hypothesis_summary": "假设的简要描述",
      "key_experiments": [
        {{
          "experiment_name": "实验名称",
          "purpose": "该实验验证什么",
          "method": "具体方法步骤",
          "expected_result_if_true": "假设成立时的预期结果",
          "expected_result_if_false": "假设不成立时的预期结果",
          "required_equipment": ["设备1", "设备2"],
          "required_materials": ["材料1", "材料2"],
          "estimated_duration": "预计耗时",
          "difficulty": "easy/medium/hard"
        }}
      ],
      "control_experiments": [
        {{
          "control_name": "对照实验名称",
          "variable_controlled": "控制的变量",
          "purpose": "对照目的"
        }}
      ],
      "computational_suggestions": [
        {{
          "method": "计算方法 (如 DFT/TD-DFT/MD)",
          "software": "推荐软件",
          "purpose": "计算模拟的目的",
          "key_parameters": "关键参数设置"
        }}
      ],
      "success_criteria": "判定假设成立/不成立的明确标准",
      "risk_assessment": "主要风险与应对策略",
      "priority": "high/medium/low"
    }}
  ],
  "overall_recommendations": "综合建议与验证路线图",
  "estimated_total_duration": "总体预估耗时"
}}'''


async def handle_formalize_research_goal(arguments: dict) -> list[TextContent]:
    """处理研究目标形式化请求"""
    goal = arguments.get("goal", "")
    previous_context = arguments.get("previous_context", "")

    logger.info(f"形式化研究目标: {goal[:80]}")

    try:
        from core.ai import create_ai_client
        from core.services.research.formalizer import formalize_problem

        # 支持 per-request LLM 配置
        llm_config = build_request_llm_config(arguments)
        if llm_config:
            ai = create_ai_client(llm_config=llm_config)
            # 将 ai client 注入到全局（临时），因为 formalize_problem 使用 get_ai_client()
            import core.ai as ai_module
            _prev_client = ai_module._ai_client_instance
            ai_module._ai_client_instance = ai
            try:
                spec = formalize_problem(goal, refinement_context=previous_context)
            finally:
                ai_module._ai_client_instance = _prev_client
        else:
            spec = formalize_problem(goal, refinement_context=previous_context)

        result = {
            "success": True,
            "problem_spec": spec.to_dict(),
        }

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"形式化失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_generate_hypotheses(arguments: dict) -> list[TextContent]:
    """处理机理假设生成请求"""
    goal = arguments.get("goal", "")
    problem_spec_data = arguments.get("problem_spec")
    abstracts = arguments.get("abstracts", [])

    logger.info(f"生成机理假设: {goal[:80]}")

    try:
        from core.services.research.core_types import (
            ProblemSpec,
            IterativeResearchState,
        )
        from core.services.research.hypothesis_generator import generate_hypotheses as gen_hyp

        # 如果传入了 problem_spec 则直接使用
        if problem_spec_data and isinstance(problem_spec_data, dict):
            spec = ProblemSpec.from_dict(problem_spec_data)
        elif goal:
            # 自动执行形式化
            from core.services.research.formalizer import formalize_problem
            spec = formalize_problem(goal)
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": False, "error": "需要提供 goal 或 problem_spec"},
                        ensure_ascii=False,
                    ),
                )
            ]

        # 构造最小化 state
        state = IterativeResearchState(problem_spec=spec)

        # 支持 per-request LLM 配置
        llm_config = build_request_llm_config(arguments)
        if llm_config:
            from core.ai import create_ai_client
            import core.ai as ai_module
            ai = create_ai_client(llm_config=llm_config)
            _prev_client = ai_module._ai_client_instance
            ai_module._ai_client_instance = ai
            try:
                state = gen_hyp(state, abstracts=abstracts or None)
            finally:
                ai_module._ai_client_instance = _prev_client
        else:
            state = gen_hyp(state, abstracts=abstracts or None)

        # 序列化输出
        hypotheses_output = []
        if state.hypothesis_set:
            for h in state.hypothesis_set.hypotheses:
                hypotheses_output.append(h.to_dict())

        result = {
            "success": True,
            "problem_spec": spec.to_dict(),
            "hypotheses": hypotheses_output,
            "hypothesis_count": len(hypotheses_output),
        }

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"假设生成失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_extract_evidence(arguments: dict) -> list[TextContent]:
    """处理证据提取请求"""
    papers = arguments.get("papers", [])
    problem_spec_data = arguments.get("problem_spec", {})

    logger.info(f"提取证据: {len(papers)} 篇论文")

    try:
        from core.services.research.core_types import (
            ProblemSpec,
            IterativeResearchState,
        )
        from core.services.research.evidence_extractor import extract_evidence as extract_ev

        spec = ProblemSpec.from_dict(problem_spec_data)

        # 构建 state
        state = IterativeResearchState(
            problem_spec=spec,
            paper_pool=[clean_paper(p) for p in papers],
        )

        # 支持 per-request LLM 配置
        llm_config = build_request_llm_config(arguments)
        if llm_config:
            from core.ai import create_ai_client
            import core.ai as ai_module
            ai = create_ai_client(llm_config=llm_config)
            _prev_client = ai_module._ai_client_instance
            ai_module._ai_client_instance = ai
            try:
                state = extract_ev(state)
            finally:
                ai_module._ai_client_instance = _prev_client
        else:
            state = extract_ev(state)

        # 序列化证据
        evidence_output = [ev.to_dict() for ev in state.evidence_set]

        result = {
            "success": True,
            "evidence_count": len(evidence_output),
            "evidence": evidence_output,
        }

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"证据提取失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_evaluate_hypotheses(arguments: dict) -> list[TextContent]:
    """处理假设评估请求"""
    hypotheses_data = arguments.get("hypotheses", [])
    evidence_data = arguments.get("evidence", [])

    logger.info(f"评估假设: {len(hypotheses_data)} 个假设, {len(evidence_data)} 条证据")

    try:
        from core.services.research.core_types import (
            IterativeResearchState,
            Hypothesis,
            HypothesisSet,
            Evidence,
        )
        from core.services.research.hypothesis_evaluator import evaluate_hypotheses as eval_hyp

        # 重建 Hypothesis 对象
        hypotheses = []
        for h_data in hypotheses_data:
            h = Hypothesis(
                hypothesis_id=h_data.get("hypothesis_id", f"H{len(hypotheses)+1}"),
                mechanism_description=h_data.get("mechanism_description", ""),
                required_variables=h_data.get("required_variables", []),
                irrelevant_variables=h_data.get("irrelevant_variables", []),
                falsifiable_conditions=h_data.get("falsifiable_conditions", []),
                expected_performance_trend=h_data.get("expected_performance_trend", ""),
            )
            hypotheses.append(h)

        hypothesis_set = HypothesisSet(
            hypotheses=hypotheses,
            selected_hypothesis_ids=[h.hypothesis_id for h in hypotheses],
        )

        # 重建 Evidence 对象
        evidence_list = []
        for ev_data in evidence_data:
            ev = Evidence(
                implementation=ev_data.get("implementation", ""),
                key_variables=ev_data.get("key_variables", {}),
                performance_results=ev_data.get("performance_results", {}),
                limitations=ev_data.get("limitations", []),
                paper_title=ev_data.get("paper_title", ""),
                doi=ev_data.get("doi", ""),
                paper_id=ev_data.get("paper_id", ""),
                method_category=ev_data.get("method_category", ""),
            )
            evidence_list.append(ev)

        # 构建 state
        state = IterativeResearchState(
            hypothesis_set=hypothesis_set,
            evidence_set=evidence_list,
        )

        # 支持 per-request LLM 配置
        llm_config = build_request_llm_config(arguments)
        if llm_config:
            from core.ai import create_ai_client
            import core.ai as ai_module
            ai = create_ai_client(llm_config=llm_config)
            _prev_client = ai_module._ai_client_instance
            ai_module._ai_client_instance = ai
            try:
                state = eval_hyp(state)
            finally:
                ai_module._ai_client_instance = _prev_client
        else:
            state = eval_hyp(state)

        # 序列化结果
        evaluation_results = []
        for h in state.hypothesis_set.hypotheses:
            evaluation_results.append({
                **h.to_dict(),
                "supporting_evidence_count": h.supporting_evidence_count,
                "conflicting_evidence_count": h.conflicting_evidence_count,
            })

        result = {
            "success": True,
            "evaluation_results": evaluation_results,
            "active_count": len(state.hypothesis_set.get_active_hypotheses()),
            "rejected_count": len([h for h in state.hypothesis_set.hypotheses
                                   if h.status.value == "rejected"]),
        }

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"假设评估失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_cluster_methods(arguments: dict) -> list[TextContent]:
    """处理方法归并请求"""
    evidence_data = arguments.get("evidence", [])

    logger.info(f"方法归并: {len(evidence_data)} 条证据")

    try:
        from core.services.research.core_types import Evidence
        from core.services.research.method_clusterer import cluster_methods as do_cluster

        # 重建 Evidence 对象
        evidence_list = []
        for ev_data in evidence_data:
            ev = Evidence(
                implementation=ev_data.get("implementation", ""),
                key_variables=ev_data.get("key_variables", {}),
                performance_results=ev_data.get("performance_results", {}),
                limitations=ev_data.get("limitations", []),
                method_category=ev_data.get("method_category", ""),
                paper_title=ev_data.get("paper_title", ""),
                doi=ev_data.get("doi", ""),
            )
            evidence_list.append(ev)

        # 支持 per-request LLM 配置
        llm_config = build_request_llm_config(arguments)
        if llm_config:
            from core.ai import create_ai_client
            import core.ai as ai_module
            ai = create_ai_client(llm_config=llm_config)
            _prev_client = ai_module._ai_client_instance
            ai_module._ai_client_instance = ai
            try:
                clusters = do_cluster(evidence_list)
            finally:
                ai_module._ai_client_instance = _prev_client
        else:
            clusters = do_cluster(evidence_list)

        # 序列化 MethodCluster
        from dataclasses import asdict
        clusters_output = []
        for c in clusters:
            clusters_output.append({
                "cluster_id": c.cluster_id,
                "mechanism_type": c.mechanism_type,
                "core_idea": c.core_idea,
                "paper_count": c.paper_count,
                "representative_papers": c.representative_papers,
                "typical_structures": c.typical_structures,
                "target_applications": c.target_applications,
                "advantages": c.advantages,
                "limitations": c.limitations,
                "synthetic_difficulty": c.synthetic_difficulty,
                "novelty_saturation": c.novelty_saturation,
                "innovation_angles": c.innovation_angles,
                "overall_score": c.overall_score,
            })

        result = {
            "success": True,
            "cluster_count": len(clusters_output),
            "clusters": clusters_output,
        }

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"方法归并失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_design_verification_plan(arguments: dict) -> list[TextContent]:
    """处理证据验证设计请求"""
    goal = arguments.get("goal", "")
    hypotheses_data = arguments.get("hypotheses", [])
    evidence_data = arguments.get("evidence", [])
    clusters_data = arguments.get("method_clusters", [])

    logger.info(f"设计验证方案: {goal[:80]}, {len(hypotheses_data)} 个假设")

    try:
        from core.ai import create_ai_client, get_ai_client

        # 构建假设文本
        hypotheses_text = ""
        for h in hypotheses_data:
            status = h.get("status", "active")
            if status == "rejected":
                continue  # 跳过已证伪的假设
            hypotheses_text += f"""
### {h.get('hypothesis_id', '?')}
机理描述: {h.get('mechanism_description', '')}
必需变量: {', '.join(h.get('required_variables', []))}
证伪条件: {', '.join(h.get('falsifiable_conditions', []))}
预期性能趋势: {h.get('expected_performance_trend', '')}
---
"""

        if not hypotheses_text.strip():
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": False, "error": "没有活跃的假设可供设计验证方案"},
                        ensure_ascii=False,
                    ),
                )
            ]

        # 构建证据文本
        evidence_text = "暂无已提取证据" if not evidence_data else ""
        for i, ev in enumerate(evidence_data[:15], 1):
            evidence_text += f"[{i}] {ev.get('paper_title', '?')}\n"
            evidence_text += f"   技术路线: {ev.get('implementation', '')}\n"
            evidence_text += f"   关键变量: {ev.get('key_variables', {})}\n"
            evidence_text += f"   性能结果: {ev.get('performance_results', {})}\n\n"

        # 构建技术路线簇文本
        clusters_text = "暂无技术路线归并" if not clusters_data else ""
        for c in clusters_data:
            clusters_text += f"- {c.get('mechanism_type', '?')}: {c.get('core_idea', '')}\n"
            if c.get("advantages"):
                clusters_text += f"  优势: {', '.join(c['advantages'])}\n"
            if c.get("limitations"):
                clusters_text += f"  局限: {', '.join(c['limitations'])}\n"

        prompt = VERIFICATION_PLAN_PROMPT.format(
            goal=goal,
            hypotheses_text=hypotheses_text,
            evidence_text=evidence_text,
            clusters_text=clusters_text,
        )

        # 支持 per-request LLM 配置
        llm_config = build_request_llm_config(arguments)
        ai = create_ai_client(llm_config=llm_config) if llm_config else get_ai_client()

        response = ai.call(prompt, json_mode=True)

        if response.success and response.data:
            result = {
                "success": True,
                **response.data,
            }
        else:
            result = {
                "success": False,
                "error": "AI 验证方案生成失败",
            }

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"验证方案设计失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


async def handle_run_deep_research(arguments: dict) -> list[TextContent]:
    """处理完整深度研究请求"""
    goal = arguments.get("goal", "")
    max_iterations = arguments.get("max_iterations", 3)
    min_year = arguments.get("min_year")
    min_score = arguments.get("min_score", 0.0)
    previous_context = arguments.get("previous_context", "")

    logger.info(f"启动深度研究: {goal[:80]}, max_iter={max_iterations}")

    try:
        from core.services.research.iterative_main import run_iterative_research
        from core.services.research.result_generator import _serialize_value
        import uuid

        # 支持 per-request LLM 配置
        _SENTINEL = object()  # 哨兵对象，区分 "未设置" 和 "全局为 None"
        llm_config = build_request_llm_config(arguments)
        if llm_config:
            from core.ai import create_ai_client
            import core.ai as ai_module
            ai = create_ai_client(llm_config=llm_config)
            _prev_client = ai_module._ai_client_instance
            ai_module._ai_client_instance = ai
        else:
            _prev_client = _SENTINEL

        job_id = f"mcp_{uuid.uuid4().hex[:8]}"

        try:
            state = await run_iterative_research(
                goal=goal,
                max_iterations=max_iterations,
                job_id=job_id,
                previous_context=previous_context,
                min_year=min_year,
                min_score=min_score,
            )
        finally:
            if _prev_client is not _SENTINEL:
                import core.ai as ai_module
                ai_module._ai_client_instance = _prev_client

        # 序列化完整结果
        result = {
            "success": True,
            "job_id": job_id,
            "goal": goal,
            "iterations_completed": state.iteration + 1,
            "paper_count": len(state.paper_pool),
            "evidence_count": len(state.evidence_set),
            "cluster_count": len(state.method_clusters),
            "cancelled": state.cancelled,
        }

        # 添加 ProblemSpec
        if state.problem_spec:
            result["problem_spec"] = state.problem_spec.to_dict()

        # 添加假设评估结果
        if state.hypothesis_set:
            result["hypotheses"] = [h.to_dict() for h in state.hypothesis_set.hypotheses]
            result["active_hypotheses"] = len(state.hypothesis_set.get_active_hypotheses())

        # 添加技术路线簇
        if state.method_clusters:
            result["method_clusters"] = [
                {
                    "cluster_id": c.cluster_id,
                    "mechanism_type": c.mechanism_type,
                    "core_idea": c.core_idea,
                    "paper_count": c.paper_count,
                    "advantages": c.advantages,
                    "limitations": c.limitations,
                    "overall_score": c.overall_score,
                    "innovation_angles": c.innovation_angles,
                }
                for c in state.method_clusters
            ]

        # 添加推荐/不推荐路径
        result["recommended_paths"] = state.recommended_paths
        result["not_recommended_paths"] = state.not_recommended_paths

        # 添加最终报告
        if state.final_report:
            result["final_report"] = state.final_report

        if state.final_report_path:
            result["final_report_path"] = state.final_report_path

        # 添加证据摘要（仅关键字段，避免响应过大）
        if state.evidence_set:
            result["evidence_summary"] = [
                {
                    "paper_title": ev.paper_title,
                    "implementation": ev.implementation,
                    "method_category": ev.method_category,
                    "doi": ev.doi,
                }
                for ev in state.evidence_set[:30]  # 最多 30 条摘要
            ]

        return [
            TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"深度研究失败: {e}", exc_info=True)
        return [
            TextContent(
                type="text", text=json.dumps({"success": False, "error": str(e)})
            )
        ]


# ============================================================
# 主入口
# ============================================================


async def main():
    """运行 MCP 服务器"""
    logger.info("🚀 启动 ChemDeep MCP Server")
    logger.info("   默认搜索源: lanfanshu, openalex, crossref")
    logger.info("   超时设置: 120秒")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio

    # 设置事件循环策略（Windows 兼容）
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
