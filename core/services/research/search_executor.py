"""
Search Executor for Iterative Research
Executes queries from SearchQuerySet
"""

import logging
from typing import List, Dict, Any
from core.mcp_search import MCPSearcher
from .core_types import SearchQuery, SearchQuerySet, IterativeResearchState

logger = logging.getLogger("deep_research")


from core.ai import get_ai_client
from .prompts import SEMANTIC_RELEVANCE_PROMPT


async def filter_by_semantic_relevance_single(
    papers: List[Dict], state: IterativeResearchState
) -> List[Dict]:
    """
    [P87] Dynamic Semantic Guard
    Filter papers based on semantic relevance to research object.
    """
    if not papers or not state.problem_spec:
        return []

    logger.info(f"🛡️ Performing Semantic Relevance Check on {len(papers)} papers...")

    # Use batch checking or single check depending on volume?
    # For now, let's use single checks in parallel for accuracy, or small batches if too slow.
    # Given the importance, we use parallel single checks.

    import asyncio

    sem = asyncio.Semaphore(10)  # Limit concurrent LLM calls

    problem_spec = state.problem_spec
    if problem_spec is None:
        return papers

    async def check_paper(p: Dict[str, Any]):
        async with sem:
            title = p.get("title", "")
            abstract = p.get("abstract") or p.get("snippet") or ""
            if not abstract:
                # If no abstract, keep it tentatively (Title only check might be too aggressive)
                return p

            prompt = SEMANTIC_RELEVANCE_PROMPT.format(
                research_object=problem_spec.research_object,
                goal=problem_spec.goal,
                title=title,
                abstract=abstract[:1000],  # Truncate
            )

            ai = get_ai_client()
            result = await asyncio.to_thread(ai.call, prompt, json_mode=True)

            if result.success and isinstance(result.data, dict):
                relation = result.data.get("relation", "IRRELEVANT")
                if relation == "IRRELEVANT":
                    logger.debug(
                        f"  🗑️ Rejected [{relation}]: {title[:40]}... Reason: {result.data.get('reason')}"
                    )
                    return None
                else:
                    # Mark relation type in paper for later use?
                    p["semantic_relation"] = relation
                    return p
            else:
                # On error, keep safe
                return p

    tasks = [check_paper(p) for p in papers]
    checked_papers = await asyncio.gather(*tasks)
    valid_papers = [p for p in checked_papers if p is not None]

    removed = len(papers) - len(valid_papers)
    if removed > 0:
        logger.info(f"🛡️ Filtered out {removed} irrelevant papers.")

    return valid_papers


async def execute_queries(
    query_set: SearchQuerySet,
    max_per_query: int = 15,
    min_year: int | None = None,
    min_score: float = 0.0,
) -> Dict:
    """
    执行 SearchQuerySet 中的待执行查询 (Async)

    Args:
        query_set: 查询集合
        max_per_query: 每个查询最大结果数
        min_year: 最小年份筛选（如 2020 表示只保留2020年及以后的论文）
        min_score: 最低评分筛选

    返回: {"papers": List[Dict], "stats": List[Dict], "score_summary": str}
    """
    pending = query_set.get_pending_queries()
    if not pending:
        logger.info("没有待执行的查询")
        return {"papers": [], "stats": [], "score_summary": ""}

    logger.info(f"🔍 正在执行 {len(pending)} 个检索查询...")

    mcp = MCPSearcher()
    all_papers = []
    seen_dois = set()
    query_stats = []

    # [P63] Concurrency
    import asyncio
    from config.settings import settings

    sem = asyncio.Semaphore(settings.SEARCH_CONCURRENCY)

    async def process_query(query):
        q_stat = {
            "query": query.keywords,
            "source": query.source,
            "success": False,
            "papers_total": 0,
            "papers_new": 0,
            "top_dois": [],
        }

        async with sem:
            try:
                logger.info(f"  📚 [{query.source.upper()}] {query.keywords[:50]}...")

                result = await _dispatch_search(mcp, query, max_per_query)

                if result.get("success"):
                    q_stat["success"] = True
                    papers = result.get("papers", [])
                    q_stat["papers_total"] = len(papers)
                    q_stat["papers_list"] = papers  # Temporarily hold papers

                    # Log brief success
                    expanded = result.get("expanded_sources", [])
                    extra_msg = f" (+ {'/'.join(expanded)})" if expanded else ""
                    logger.info(
                        f"     ✅ [{query.source.upper()}{extra_msg}] Found {len(papers)} papers"
                    )
                else:
                    q_stat["error"] = result.get("error", "Unknown")
                    logger.warning(
                        f"     ❌ [{query.source.upper()}] Failed: {result.get('error')}"
                    )

            except Exception as e:
                logger.error(f"     💥 Execution failed: {e}")
                q_stat["error"] = str(e)

            # Always mark executed
            query_set.mark_executed(query)
            return q_stat

    # Run concurrently
    results_stats = await asyncio.gather(*[process_query(q) for q in pending])

    # Post-process results (Deduplication)
    for q_stat in results_stats:
        # Extract papers if success
        if q_stat.get("success") and "papers_list" in q_stat:
            papers = q_stat.pop("papers_list")  # Remove from stat

            new_count = 0
            current_dois = []

            for p in papers:
                doi = (p.get("doi") or "").lower()
                if doi:
                    if doi not in seen_dois:
                        seen_dois.add(doi)
                        all_papers.append(p)
                        new_count += 1
                    current_dois.append(doi)
                else:
                    all_papers.append(p)
                    new_count += 1

            q_stat["papers_new"] = new_count
            q_stat["top_dois"] = current_dois[:5]

        query_stats.append(q_stat)

    # ========== 年份筛选和评分 ==========
    from core.services.research.paper_scorer import paper_scorer

    # 年份筛选
    if min_year:
        original_count = len(all_papers)
        all_papers = paper_scorer.filter_by_year(all_papers, min_year=min_year)
        logger.info(
            f"📅 年份筛选 (≥{min_year}): {original_count} -> {len(all_papers)} 篇"
        )

    # 评分
    for paper in all_papers:
        score_result = paper_scorer.score_paper(paper)
        paper["score"] = score_result["score"]
        paper["level"] = score_result["level"]
        paper["score_breakdown"] = score_result["breakdown"]

    # 按最低分筛选
    if min_score > 0:
        original_count = len(all_papers)
        all_papers = [p for p in all_papers if p.get("score", 0) >= min_score]
        logger.info(
            f"🏆 评分筛选 (≥{min_score}): {original_count} -> {len(all_papers)} 篇"
        )

    # 按评分排序
    all_papers.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 生成评分摘要
    score_summary = paper_scorer.get_score_summary(all_papers)
    logger.info(f"\n{score_summary}")

    logger.info(f"✅ 检索完成: 共获得 {len(all_papers)} 篇论文")
    return {"papers": all_papers, "stats": query_stats, "score_summary": score_summary}


async def _dispatch_search(
    mcp: MCPSearcher, query: SearchQuery, max_results: int
) -> Dict:
    """分发到对应的搜索源 (Async)"""
    import asyncio

    source = query.source.lower()
    keywords = query.keywords

    # 辅助函数：将同步 MCP 调用包装为 Async
    async def run_sync(func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    if source == "openalex":
        return await run_sync(mcp.search_openalex, keywords, max_results=max_results)
    elif source == "crossref":
        # P20: Crossref/General 搜索使用混合模式 (Academic + Web)
        return await mcp.search_hybrid(keywords, max_results=max_results)
    elif source == "wos":
        return await run_sync(mcp.search_wos, keywords, max_results=max_results)
    elif source == "scholar":
        return await run_sync(
            mcp.search_google_scholar, keywords, max_results=max_results
        )
    elif source == "lanfanshu":
        # 烂番薯学术搜索
        return await run_sync(mcp.search_lanfanshu, keywords, max_results=max_results)
    else:
        # 默认使用混合搜索
        return await mcp.search_hybrid(keywords, max_results=max_results)


# ============================================================
# [P87] 语义相关性过滤
# ============================================================
async def filter_by_semantic_relevance(
    papers: List[Dict], state: "IterativeResearchState", batch_size: int = 10
) -> List[Dict]:
    """
    [P87] 使用 LLM 过滤语义不相关的论文
    """
    if not papers or not state.problem_spec:
        return papers

    from core.ai import simple_chat
    from .prompts import SEMANTIC_RELEVANCE_PROMPT
    import json

    research_object = state.problem_spec.research_object or state.problem_spec.goal
    goal = state.problem_spec.goal

    filtered_papers = []
    total = len(papers)

    logger.info(f"🧹 [P87] 开始语义相关性过滤 ({total} 篇论文)...")

    # 分批处理
    for i in range(0, total, batch_size):
        batch = papers[i : i + batch_size]

        # 准备批次数据
        papers_batch_text = ""
        for idx, p in enumerate(batch):
            title = p.get("title", "Untitled")
            abstract = (p.get("abstract") or "")[:500]
            papers_batch_text += f"\n[{idx}] Title: {title}\nAbstract: {abstract}\n"

        prompt = SEMANTIC_RELEVANCE_PROMPT.format(
            research_object=research_object, goal=goal, papers_batch=papers_batch_text
        )

        try:
            response = simple_chat(prompt, json_mode=True)

            if isinstance(response, list):
                classifications = response
            elif isinstance(response, str):
                classifications = json.loads(response)
            else:
                filtered_papers.extend(batch)
                continue

            if not isinstance(classifications, list):
                filtered_papers.extend(batch)
                continue

            kept_count = 0
            for item in classifications:
                if not isinstance(item, dict):
                    continue
                idx = item.get("index", -1)
                category = item.get("category", "").lower()

                if 0 <= idx < len(batch):
                    if category != "irrelevant":
                        batch[idx]["_semantic_category"] = category
                        filtered_papers.append(batch[idx])
                        kept_count += 1
                    else:
                        logger.debug(
                            f"    [过滤] {batch[idx].get('title', '')[:40]}..."
                        )

            logger.info(
                f"    批次 {i // batch_size + 1}: 保留 {kept_count}/{len(batch)}"
            )

        except Exception as e:
            logger.warning(f"语义过滤批次失败: {e}，保留全部")
            filtered_papers.extend(batch)

    removed = total - len(filtered_papers)
    logger.info(
        f"✅ [P87] 语义过滤完成: 移除 {removed} 篇噪音，保留 {len(filtered_papers)} 篇"
    )

    return filtered_papers


# State-based interface
async def execute_search(
    state: IterativeResearchState,
    min_year: int | None = None,
    min_score: float | None = None,
) -> IterativeResearchState:
    """
    State-based search execution (Async)
    输入: state.query_set
    输出: state.paper_pool (追加)
    [P62] Also returns execution stats in state.last_search_stats
    """
    # Execute queries with concurrency (P63) and stats (P62)
    effective_min_year = min_year if min_year is not None else state.min_year
    effective_min_score = min_score if min_score is not None else state.min_score

    results = await execute_queries(
        state.query_set,
        min_year=int(effective_min_year) if effective_min_year is not None else None,
        min_score=effective_min_score,
    )
    new_papers = results["papers"]
    state.last_search_stats = results["stats"]
    state.score_summary = results.get("score_summary", "")

    # [P87] Semantic Filter
    if new_papers:
        new_papers = await filter_by_semantic_relevance(new_papers, state)

    # 库管理 imports
    from config.settings import settings
    import json
    import re
    import hashlib

    # 确保分区目录存在
    index_dir = settings.LIBRARY_INDEX_DIR
    index_dir.mkdir(parents=True, exist_ok=True)

    article_dir = settings.LIBRARY_ARTICLE_DIR
    article_dir.mkdir(parents=True, exist_ok=True)

    def get_paper_id(p: Dict) -> str:
        """生成唯一的 paper ID (优先使用 DOI，否则使用 Title 哈希)"""
        doi = p.get("doi")
        if doi:
            # 替换文件名非法字符
            return re.sub(r'[\\/*?:"<>|]', "_", doi.lower())

        title = p.get("title", "")
        # 使用 Title 的 MD5
        return hashlib.md5(title.encode("utf-8")).hexdigest()

    # 加载现有库 (用于彻底去重)
    existing_ids = set()
    for p in state.paper_pool:
        existing_ids.add(get_paper_id(p))

    added_count = 0

    for p in new_papers:
        pid = get_paper_id(p)

        # 元数据路径 (Index分区)
        metadata_path = index_dir / f"{pid}.json"

        # 1. 如果已在内存中，跳过
        if pid in existing_ids:
            continue

        # 2. 跨区域查重: 检查全局 Index 库
        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    stored_paper = json.load(f)
                    # 复用全局库中的信息
                    p.update(stored_paper)
                    logger.debug(f"    [查重命中] 复用全局库: {pid}")
            except Exception as e:
                logger.warning(f"    读取全局元数据失败 {pid}: {e}")

        # 3. 保存/更新元数据到全局 Index 库
        try:
            # 确保存入 ID 和关联的文章路径建议
            p["library_id"] = pid

            # 如果 full_content_path 还没设置，预设标准路径
            if not p.get("full_content_path"):
                proposed_article_path = article_dir / pid / "full.md"
                # 只有当文件实际存在时才标记? 或者留给 fetcher 处理
                # 这里暂时不强制设置路径，交由 fetcher 决定实际写入位置

            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"    保存元数据失败 {pid}: {e}")

        state.paper_pool.append(p)
        existing_ids.add(pid)
        added_count += 1

    logger.info(f"📊 论文池追加: {added_count} 篇 (总数: {len(state.paper_pool)})")
    return state
