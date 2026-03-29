"""
Evidence Extractor Module
Implements Instruction 6: 文献 → Evidence 的抽取接口
集成字段保真、稳定 ID 生成、study_type 分类、验证 Gate
"""
import logging
import hashlib
import re
from typing import List, Dict, Optional
from core.ai import AIClient
from .core_types import Evidence, ProblemSpec, IterativeResearchState, ContentLevel, StudyType
from .conflict_adjudicator import get_independence_key
from .evidence_quality import calculate_quality_weight
from config.settings import settings

logger = logging.getLogger('deep_research')

# ============================================================
# P16: AI 调用优化 - 单例 & 缓存
# ============================================================

# 模块级 AIClient 单例 (避免每次提取都初始化)
_ai_client: Optional[AIClient] = None

def _get_ai_client() -> AIClient:
    """获取或创建 AIClient 单例"""
    global _ai_client
    if _ai_client is None:
        from core.ai import get_ai_client
        _ai_client = get_ai_client()
        logger.info("📌 AIClient 单例已创建 (复用)")
    return _ai_client


# 提取结果缓存 (paper_cache_key -> extraction_result)
# 避免同一论文重复调用 AI
_extraction_cache: Dict[str, dict] = {}


def _get_cache_key(title: str, content: str) -> str:
    """生成缓存键 (基于标题 + 内容摘要)"""
    content_snippet = content[:500] if content else ""
    return hashlib.md5(f"{title}|{content_snippet}".encode()).hexdigest()


def _get_cached_extraction(key: str) -> Optional[dict]:
    """从缓存获取提取结果"""
    return _extraction_cache.get(key)


def _set_cached_extraction(key: str, result: dict):
    """缓存提取结果"""
    _extraction_cache[key] = result


EXTRACTION_PROMPT = '''从科研文献中提取研究方法和性能信息。

研究主题: {research_object}

文献信息:
标题: {title}
摘要/内容: {content}

任务: 从这篇文献中提取有价值的科研信息。

请返回JSON格式结果:
{{
  "relevant": true,
  "implementation": "这篇文献研究的核心方法或系统是什么？(一句话概括)",
  "key_variables": {{
    "核心变量1": "具体数值或描述",
    "核心变量2": "具体数值或描述"
  }},
  "performance_results": {{
    "主要性能": "具体数值或定性描述",
    "其他特性": "数值或描述"
  }},
  "limitations": ["局限性或挑战"],
    "method_category": "这项研究的技术类别 (如: 荧光探针/光电材料/传感器/催化剂)",
    "category": "direct_data" // direct_data | methodology | analogy_insight
  }

判断标准:
- 如果文献涉及 化学材料、荧光、光学、探针、传感器、有机分子 等主题，请设置 relevant: true
- 只有当文献完全不相关（如纯计算机、医学临床等）时才返回 {"relevant": false}
- 尽量从文献中提取有用信息，即使不完全匹配研究主题
- [Fallback] 如果未找到 Target Object 的直接数据，请提取 Method/Protocol 或 Analogue Insight，并将 category 设为 "methodology" 或 "analogy_insight"'''


EVIDENCE_BATCH_PROMPT = '''从以下 {count} 篇科研文献中提取研究方法和性能信息。

研究主题: {research_object}

待处理文献列表:
{papers_content}

任务: 逐篇提取有价值的科研信息。

请返回 JSON 格式结果:
{{
  "items": [
    {{
      "paper_index": "文献编号 (如 1, 2...)",
      "relevant": true,
      "implementation": "这篇文献研究的核心方法或系统是什么？(一句话概括)",
      "key_variables": {{
        "核心变量1": "具体数值或描述"
      }},
      "performance_results": {{
        "主要性能": "具体数值或定性描述"
      }},
      "limitations": ["局限性或挑战"],
      "method_category": "技术类别",
      "category": "direct_data" // direct_data | methodology | analogy_insight
    }},
    ...
  ]
}}

判断标准:
- 如果文献完全不相关，返回 {{"paper_index": "...", "relevant": false}}
- [Fallback] 如果未找到 Target Object 的直接数据，请提取 Method/Protocol 或 Analogue Insight，并将 category 设为 "methodology" 或 "analogy_insight"
- 保持 paper_index 与输入顺序一致
'''


def _normalize_whitespace(text: str) -> str:
    """归一化空白字符：strip + 多空格压缩"""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text.strip())


def _get_paper_key(paper: Dict) -> str:
    """
    获取论文稳定主键 (降级策略)
    doi > paper_id/openalex_id > source_url
    """
    doi = paper.get("doi", "")
    if doi:
        return f"doi:{doi}"
    
    paper_id = paper.get("id", "") or paper.get("openalex_id", "")
    if paper_id:
        return f"id:{paper_id}"
    
    url = paper.get("url", "") or paper.get("primary_location", {}).get("landing_page_url", "")
    if url:
        return f"url:{url}"
    
    return ""


def _generate_evidence_id(paper: Dict, implementation: str, key_variables: Dict, spec: ProblemSpec) -> str:
    """
    生成确定性 evidence_id
    使用: paper_key + normalized_impl[:200] + key_vars_summary + spec.goal[:50]
    """
    paper_key = _get_paper_key(paper)
    
    # 归一化 implementation
    impl_norm = _normalize_whitespace(implementation)[:200]
    
    # key_variables 摘要 (前 100 字符)
    vars_summary = str(sorted(key_variables.items()))[:100] if key_variables else ""
    
    # spec 标识 (避免不同任务冲突)
    spec_id = (spec.goal[:50] if spec else "") 
    
    content = f"{paper_key}|{impl_norm}|{vars_summary}|{spec_id}"
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def _get_first_author(paper: Dict) -> str:
    """提取第一作者"""
    authors = paper.get("authorships", []) or paper.get("authors", [])
    if authors:
        first = authors[0]
        if isinstance(first, dict):
            return first.get("author", {}).get("display_name", "") or first.get("name", "")
        elif isinstance(first, str):
            return first
    return ""


def _classify_study_type(paper: Dict) -> StudyType:
    """
    规则分类 study_type
    强信号词: review/overview/survey/perspective
    弱信号词: progress/advances in (需额外条件)
    """
    title = (paper.get("title") or "").lower()
    abstract = (paper.get("abstract") or "").lower()
    
    # 规则 1: 荟萃分析
    if "meta-analysis" in title or "meta analysis" in title:
        return StudyType.META_ANALYSIS
    
    # 规则 2: 评论/社论
    commentary_keywords = ["comment on", "editorial", "erratum", "corrigendum", "reply to"]
    if any(kw in title for kw in commentary_keywords):
        return StudyType.COMMENTARY
    
    # 规则 3: 综述 (强信号)
    strong_review_keywords = ["review", "overview", "survey", "perspective"]
    if any(kw in title for kw in strong_review_keywords):
        return StudyType.REVIEW
    
    # 规则 4: 综述 (弱信号 + 额外条件)
    weak_review_keywords = ["progress", "advances in", "recent developments"]
    if any(kw in title for kw in weak_review_keywords):
        # 额外条件: abstract 中包含 "this review" 或 "we review"
        if "this review" in abstract or "we review" in abstract or "are reviewed" in abstract:
            return StudyType.REVIEW
    
    # 规则 5: 原创研究关键词
    original_keywords = ["synthesis", "preparation", "fabrication", "we report", "we demonstrate", "we developed", "we synthesized"]
    if any(kw in title.lower() or kw in abstract for kw in original_keywords):
        return StudyType.ORIGINAL
    
    return StudyType.UNKNOWN


def _determine_content_level(paper: Dict) -> ContentLevel:
    """根据 paper 内容确定 content_level"""
    if paper.get("full_content"):
        return ContentLevel.FULL_TEXT
    elif paper.get("abstract") or paper.get("Abstract") or paper.get("summary"):
        return ContentLevel.ABSTRACT_ONLY
    else:
        return ContentLevel.TITLE_ONLY


def _inherit_paper_metadata(paper: Dict, evidence: Evidence) -> None:
    """从 paper 元数据继承字段 (不允许 LLM 猜)"""
    evidence.doi = paper.get("doi", "")
    evidence.paper_id = paper.get("id", "") or paper.get("openalex_id", "")
    evidence.paper_title = paper.get("title", "")
    evidence.paper_year = paper.get("publication_year") or paper.get("year")
    evidence.first_author = _get_first_author(paper)
    evidence.source_url = paper.get("url", "") or paper.get("primary_location", {}).get("landing_page_url", "")
    evidence.content_level = _determine_content_level(paper)
    evidence.study_type = _classify_study_type(paper)


def _validate_and_gate(evidence: Evidence) -> None:
    """
    Evidence Gate (最后校验)
    1. 计算 independence_key
    2. Gate: paper_key 全空 → 降级为 TITLE_ONLY
    3. 计算 quality_weight
    4. Gate: falsifiable_allowed 仅当 normalized_values 非空
    """
    # 1. 计算 independence_key
    evidence.independence_key = get_independence_key(evidence)
    
    # 2. Gate 1: 若 independence_key 是 hash 兜底且无标题 -> TITLE_ONLY
    if evidence.independence_key.startswith("hash:"):
        if not evidence.paper_title:
            evidence.content_level = ContentLevel.TITLE_ONLY
    
    # 3. 计算 quality_weight
    evidence.quality_weight = calculate_quality_weight(evidence)
    
    # 4. Gate 2: falsifiable_allowed 仅当 normalized_values 非空
    # (全文但无数值仅作为 supporting，不参与 falsification)
    evidence.falsifiable_allowed = bool(evidence.normalized_values)


def _attempt_json_repair(text: str) -> Optional[dict]:
    """
    [P66] 尝试修复损坏的 JSON
    Strategy:
    1. Extract generic JSON block
    2. Try json.loads
    3. Try ast.literal_eval (Python syntax is close to JSON)
    4. Try regex fix for Missing Comma
    """
    import json
    import ast
    
    if not text:
        return None

    # Helper: Extract likely JSON part
    # Look for outermost { }
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        json_candidate = match.group(1)
    else:
        json_candidate = text
        
    # Attempt 1: Standard JSON
    try:
        return json.loads(json_candidate)
    except:
        pass
        
    # Attempt 2: ast.literal_eval (Handles single quotes, False/True title case, but not null/true/false)
    # We need to map JSON constants to Python
    python_candidate = json_candidate.replace("true", "True").replace("false", "False").replace("null", "None")
    try:
        res = ast.literal_eval(python_candidate)
        if isinstance(res, dict):
            return res
    except:
        pass
        
    # Attempt 3: Fix missing commas (simple heuristic)
    # Pattern: "value" "next_key": -> "value", "next_key":
    try:
        # Fix missing comma between value and key
        fixed = re.sub(r'([\"\}])\s*\n\s*\"', r'\1,\n"', json_candidate)
        return json.loads(fixed)
    except:
        pass
        
    return None


def extract_evidence_from_paper(
    paper: Dict, 
    spec: ProblemSpec
) -> Evidence | None:
    """
    从单篇论文提取 Evidence
    """
    title = paper.get("title", "Unknown")
    
    # 获取内容
    full_content = paper.get("full_content")
    abstract = (
        paper.get("abstract") or 
        paper.get("Abstract") or 
        paper.get("summary") or 
        paper.get("description") or
        paper.get("abstractText") or
        ""
    )
    snippet = paper.get("snippet") or paper.get("Snippet") or ""
    
    content = full_content or abstract or snippet
    
    # 确定内容来源
    if full_content:
        content_source = "full_text"
    elif abstract:
        content_source = "abstract"
    elif snippet:
        content_source = "snippet"
    else:
        content_source = "none"
        if title and len(title) > 30:
            content = f"Title: {title}"
            content_source = "title_only"
        else:
            logger.debug(f"    无内容: {title[:50]}")
            return None
    
    # 内容太短
    if len(content) < 100:
        logger.debug(f"    内容太短 ({len(content)} chars): {title[:50]}")
        return None
    
    # 截断过长内容
    if len(content) > 6000:
        content = content[:6000] + "..."
    
    # P16: 检查缓存 (避免重复提取)
    cache_key = _get_cache_key(title, content)
    cached = _get_cached_extraction(cache_key)
    if cached is not None:
        logger.debug(f"    [缓存命中] {title[:40]}")
        data = cached
    else:
        # 调用 AI 提取 (使用单例)
        ai = _get_ai_client()
        prompt = EXTRACTION_PROMPT.format(
            research_object=spec.research_object,
            title=title,
            content=content
        )
        
        result = ai.call(prompt, json_mode=True)
        
        if not (result.success and isinstance(result.data, dict)):
            return None
        
        data = result.data
        
        # [P66] JSON Repair Logic (Already handled in AI core if P67 AI client fix applied, but keeping fallback)
        if data.get("_parse_failed", False):
            # [P65-2] Explicit log for downstream
            logger.warning(f"  ✗ 提取失败：JSON 解析失败（已尝试修复但无效）: {title[:30]}")
            return None

        # 缓存结果 (无论相关与否都缓存)
        _set_cached_extraction(cache_key, data)
    
    return _create_evidence_from_data(paper, data, spec, content_source, full_content is not None)


def _create_evidence_from_data(
    paper: Dict,
    data: Dict, 
    spec: ProblemSpec,
    content_source: str,
    is_full_text: bool
) -> Evidence | None:
    """[P67] 统一数据转换逻辑 (Batch/Single共用)"""
    
    if not data.get("relevant", False):
        # logger.debug(f"    AI判断不相关") # Caller handles logs usually
        return None
    
    implementation = data.get("implementation", "")
    key_variables = data.get("key_variables", {})
    
    # 创建 Evidence
    evidence = Evidence(
        implementation=implementation,
        key_variables=key_variables,
        performance_results=data.get("performance_results", {}),
        limitations=data.get("limitations", []),
        method_category=data.get("method_category", ""),
        category=data.get("category", "direct_data"), # [P87]
        confidence=0.8 if is_full_text else 0.5,
        source_type=content_source
    )
    
    # 1. 继承 paper 元数据 (不允许 LLM 猜)
    _inherit_paper_metadata(paper, evidence)
    
    # 2. 生成确定性 evidence_id
    evidence.evidence_id = _generate_evidence_id(paper, implementation, key_variables, spec)
    
    # 3. 验证 Gate (填充 independence_key, quality_weight, falsifiable_allowed)
    _validate_and_gate(evidence)
    
    return evidence



def extract_all_evidence_batched(
    papers: List[Dict], 
    spec: ProblemSpec,
    max_papers: int = 20
) -> List[Evidence]:
    """
    [P67] 批量提取 Evidence (Batch Mode)
    """
    logger.info(f"🔬 [Batch] 正在从 {min(len(papers), max_papers)} 篇文献中提取证据...")
    
    evidence_list = []
    papers_to_process = papers[:max_papers]
    
    # Check cache first for all
    uncached_indices = []
    for i, p in enumerate(papers_to_process):
        title = p.get("title", "Unknown")
        content = p.get("full_content") or p.get("abstract") or p.get("snippet") or "" 
        if not content: continue
        
        cache_key = _get_cache_key(title, content)
        cached = _get_cached_extraction(cache_key)
        
        if cached:
            # Rehydrate from cache
            src = "full_text" if p.get("full_content") else ("abstract" if p.get("abstract") else "snippet")
            try:
                ev = _create_evidence_from_data(p, cached, spec, src, bool(p.get("full_content")))
                if ev:
                    evidence_list.append(ev)
                    logger.debug(f"  [Cache] Batch hit for {title[:20]}")
            except Exception:
                # Cache might be corrupted or incompatible
                uncached_indices.append(i)
        else:
            uncached_indices.append(i)
            
    if not uncached_indices:
        return evidence_list

    # Process uncached in batches
    batch_size = settings.EVIDENCE_BATCH_SIZE
    if batch_size < 2: 
         batch_size = 4 

    import math
    
    # Group indices
    chunks = [uncached_indices[i:i + batch_size] for i in range(0, len(uncached_indices), batch_size)]
    
    ai = _get_ai_client()
    
    for chunk in chunks:
        # Prepare batch prompt
        papers_text = []
        chunk_papers = []
        for local_idx, real_idx in enumerate(chunk):
            p = papers_to_process[real_idx]
            chunk_papers.append(p)
            
            # Content prep
            title = p.get("title", "")
            content = p.get("full_content") or p.get("abstract") or p.get("snippet") or ""
            # Truncate for batch context limit
            max_chars = settings.EVIDENCE_BATCH_MAX_CHARS
            if len(content) > max_chars:
                content = content[:max_chars] + "..."
            
            papers_text.append(f"[{local_idx+1}] 标题: {title}\n内容: {content}\n")
            
        prompt = EVIDENCE_BATCH_PROMPT.format(
            count=len(chunk),
            research_object=spec.research_object,
            papers_content="\n".join(papers_text)
        )
        
        # Call AI
        success = False
        try:
            # Use json_mode
            result = ai.call(prompt, json_mode=True)
            
            if result.success and isinstance(result.data, dict) and "items" in result.data:
                items = result.data["items"]
                
                # [P92] Defensive check: items must be list
                if not isinstance(items, list):
                    logger.warning(f"  [Batch] Invalid items type: {type(items)}")
                    success = False
                else:
                    success = True
                    
                    # Match items back to papers
                    for item in items:
                         # [P92] Defensive check: item must be dict
                        if not isinstance(item, dict):
                            continue
                            
                        p_idx_str = str(item.get("paper_index", "0"))
                        # Extract number
                        nums = re.findall(r"\d+", p_idx_str)
                        if not nums: continue
                        b_idx = int(nums[0]) - 1 # 1-based to 0-based
                        
                        if 0 <= b_idx < len(chunk_papers):
                            target_paper = chunk_papers[b_idx]
                            
                            # Determine source
                            src = "full_text" if target_paper.get("full_content") else "abstract"
                            
                            # Cache it
                            c_content = target_paper.get("full_content") or target_paper.get("abstract") or target_paper.get("snippet") or ""
                            c_key = _get_cache_key(target_paper.get("title", ""), c_content)
                            _set_cached_extraction(c_key, item)
                            
                            try:
                                ev = _create_evidence_from_data(target_paper, item, spec, src, bool(target_paper.get("full_content")))
                                if ev:
                                    evidence_list.append(ev)
                                    logger.info(f"  [Batch] ✓ {ev.method_category} (ID: {ev.evidence_id})")
                            except Exception as ex:
                                logger.warning(f"  [Batch] Item processing failed: {ex}")
            else:
                 logger.warning(f"  [Batch] AI response invalid structure or failed: {result.error or 'No items'}")
                 
        except Exception as e:
            logger.error(f"  [Batch] Error: {e}")
            
        # Fallback if Batch Failed
        if not success:
            logger.warning("  ⚠️ Batch failed, falling back to single extraction for this chunk")
            for p in chunk_papers:
                try:
                    ev = extract_evidence_from_paper(p, spec)
                    if ev:
                        evidence_list.append(ev)
                        logger.info(f"  [Fallback] ✓ {ev.evidence_id}")
                except Exception as ex:
                    logger.warning(f"  [Fallback] Failed: {ex}")

    logger.info(f"✅ [Batch] 共提取 {len(evidence_list)} 条有效证据")
    return evidence_list


def extract_all_evidence(
    papers: List[Dict], 
    spec: ProblemSpec,
    max_papers: int = 20
) -> List[Evidence]:
    """批量提取 Evidence (Entry Point)"""
    
    # [P67] Dispatch to batch mode if enabled
    if settings.EVIDENCE_BATCH_SIZE > 1:
        return extract_all_evidence_batched(papers, spec, max_papers)
        
    logger.info(f"🔬 正在从 {min(len(papers), max_papers)} 篇文献中提取证据 (Single Mode)...")
    
    if papers:
        first = papers[0]
        logger.info(f"   论文字段示例: {list(first.keys())}")
    
    evidence_list = []
    papers_to_process = papers[:max_papers]
    
    for i, paper in enumerate(papers_to_process, 1):
        try:
            ev = extract_evidence_from_paper(paper, spec)
            if ev:
                evidence_list.append(ev)
                logger.info(f"  [{i}/{len(papers_to_process)}] ✓ {ev.method_category} (ID: {ev.evidence_id})")
            else:
                logger.info(f"  [{i}/{len(papers_to_process)}] ✗ 不相关或无法提取")
        except Exception as e:
            logger.warning(f"  [{i}] 提取失败: {e}")
    
    logger.info(f"✅ 共提取 {len(evidence_list)} 条有效证据")
    return evidence_list


def extract_evidence(state: IterativeResearchState) -> IterativeResearchState:
    """
    State-based evidence extraction
    输入: state.paper_pool, state.problem_spec
    输出: state.evidence_set
    """
    if not state.paper_pool:
        logger.warning("No papers to extract evidence from")
        return state
    
    if state.problem_spec is None:
        raise ValueError("problem_spec must be set first")
    
    new_evidence = extract_all_evidence(state.paper_pool, state.problem_spec)
    state.evidence_set.extend(new_evidence)
    
    return state


# ============================================================
# P28: Async Parallel Extraction
# ============================================================
import asyncio

async def extract_evidence_from_paper_async(
    paper: Dict, 
    spec: ProblemSpec,
    semaphore: asyncio.Semaphore,
    index: int,
    total: int
) -> Optional[Evidence]:
    """Async wrapper for single paper extraction with semaphore control."""
    async with semaphore:
        try:
            # Run the synchronous extraction in thread pool
            ev = await asyncio.to_thread(extract_evidence_from_paper, paper, spec)
            if ev:
                logger.info(f"  [{index}/{total}] ✓ {ev.method_category}")
            else:
                logger.debug(f"  [{index}/{total}] ✗ Skipped")
            return ev
        except Exception as e:
            logger.warning(f"  [{index}/{total}] 提取失败: {e}")
            return None


async def extract_all_evidence_async(
    papers: List[Dict], 
    spec: ProblemSpec,
    max_papers: int = 20,
    concurrency: int = 5
) -> List[Evidence]:
    """
    P28: Async parallel evidence extraction.
    Uses asyncio.gather with Semaphore for controlled concurrency.
    """
    papers_to_process = papers[:max_papers]
    total = len(papers_to_process)
    
    logger.info(f"🚀 Extracting evidence from {total} docs ({concurrency}x concurrency)...")
    
    semaphore = asyncio.Semaphore(concurrency)
    
    tasks = [
        extract_evidence_from_paper_async(paper, spec, semaphore, i+1, total)
        for i, paper in enumerate(papers_to_process)
    ]
    
    results = await asyncio.gather(*tasks)
    
    # Filter None results
    evidence_list = [ev for ev in results if ev is not None]
    
    logger.info(f"✅ 共提取 {len(evidence_list)} 条有效证据 (并行处理)")
    return evidence_list


async def extract_evidence_async(state: IterativeResearchState) -> IterativeResearchState:
    """
    P28: Async state-based evidence extraction.
    Drop-in async replacement for extract_evidence.
    """
    if not state.paper_pool:
        logger.warning("No papers to extract evidence from")
        return state
    
    if state.problem_spec is None:
        raise ValueError("problem_spec must be set first")
    
    new_evidence = await extract_all_evidence_async(state.paper_pool, state.problem_spec)
    state.evidence_set.extend(new_evidence)
    
    return state

