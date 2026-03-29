"""
Iterative Research Main Loop
Implements the complete iterative research workflow
"""

import logging
from .core_types import (
    ProblemSpec,
    IterativeResearchState,
    SufficiencyStatus,
    JobCancelledError,
)
from .formalizer import formalize
from .query_generator import init_search_space, expand_search_space
from .search_executor import execute_search
from .content_fetch import fetch
from .evidence_extractor import extract_evidence
from .method_clusterer import cluster
from .sufficiency_checker import evaluate
from .result_generator import generate_result

logger = logging.getLogger("deep_research")


from typing import Callable, List, Optional


async def run_iterative_research(
    goal: str,
    max_iterations: int = 3,
    cancel_callback: Callable[[], bool] = None,
    interaction_callback: Callable[[str, List[str]], str] = None,
    job_id: str = "",
    previous_context: str = "",  # [P54] Support for context refinement
    initial_state: Optional[IterativeResearchState] = None,  # [P98] Resume support
    min_year: int = None,  # 最小年份筛选（如 2020）
    min_score: float = 0.0,  # 最低评分筛选
) -> IterativeResearchState:
    """
    完整的迭代式深度研究流程 (Async)

    流程:
    Goal → ProblemSpec → SearchQuerySet → PaperSet → EvidenceSet
        → MethodClusters → Evaluation → SufficiencyCheck
        → (扩展检索 循环) or Result

    Args:
        goal: 研究目标
        max_iterations: 最大迭代次数
        cancel_callback: 取消回调
        interaction_callback: 交互回调
        job_id: 任务ID
        previous_context: 上下文（用于细化模式）
        initial_state: 初始状态（用于恢复）
        min_year: 最小年份筛选（如 2020 表示只保留2020年及以后的论文）
        min_score: 最低评分筛选（0-10分）
    """

    # P24: 取消检查辅助函数 - 抛出异常以立即停止
    def check_cancel():
        if cancel_callback and cancel_callback():
            logger.warning("⚠️ 检测到取消请求，正在停止任务...")
            raise JobCancelledError("User requested cancellation")

    try:
        logger.info("=" * 60)
        logger.info(f"🚀 启动迭代式深度研究")
        logger.info(f"   目标: {goal}")
        if initial_state:
            logger.info(
                f"   📂 从检查点恢复 (Job ID: {initial_state.job_id}, Iter: {initial_state.iteration})"
            )
        if previous_context:
            logger.info(f"   上下文: {len(previous_context)} char (Refinement Mode)")
        logger.info("=" * 60)

        # 1. 初始化或恢复状态
        if initial_state:
            state = initial_state
            # Ensure callbacks/configs are up to date
            state.max_iterations = max_iterations
            # job_id should match
        else:
            state = IterativeResearchState(
                job_id=job_id,
                problem_spec=ProblemSpec(
                    goal=goal, refinement_context=previous_context
                ),
                max_iterations=max_iterations,
            )

        # 存储年份和评分参数到 state
        state.min_year = min_year
        state.min_score = min_score
        logger.info(f"   年份筛选: {f'≥{min_year}' if min_year else '不限'}")
        logger.info(f"   最低评分: {min_score}")

        # [P62] Initialize Tree Recorder
        from .tree_recorder import ResearchTreeRecorder

        recorder = ResearchTreeRecorder(job_id)
        if not initial_state:
            recorder.record_root(goal)

        check_cancel()

        # 2. 需求形式化 (指令2)
        # Check if already formalized
        if state.problem_spec and state.problem_spec.research_object:
            logger.info("\n⏩ 阶段 1: 需求形式化 (已完成)")
        else:
            logger.info("\n📋 阶段 1: 需求形式化")
            state = formalize(state)

            # [P86] 保存检查点
            from .checkpoint_manager import save_checkpoint

            save_checkpoint(job_id, state, "formalize")

        check_cancel()

        # 2.5 机理假设生成
        # Check if hypotheses exist
        if state.hypothesis_set and state.hypothesis_set.hypotheses:
            logger.info("\n⏩ 阶段 1.5: 机理假设生成 (已完成)")
        else:
            from .hypothesis_generator import generate_hypotheses

            state = generate_hypotheses(
                state, interaction_callback=interaction_callback
            )

            # [P86] 保存检查点
            from .checkpoint_manager import save_checkpoint  # Re-import safe

            save_checkpoint(job_id, state, "hypothesis")

        check_cancel()

        # 3. 生成初始检索空间 (指令4)
        # Check if queries exist
        if state.query_set and state.query_set.queries:
            logger.info("\n⏩ 阶段 2: 生成检索空间 (已完成)")
        else:
            logger.info("\n🔍 阶段 2: 生成检索空间")
            state = init_search_space(state)

            # [P86] 保存检查点
            from .checkpoint_manager import save_checkpoint

            save_checkpoint(job_id, state, "init_search")

        # 4. 迭代循环
        # If resuming inside iteration (e.g. check iteration index or phase)
        # The loop condition handles iteration index.
        # But if we crashed mid-iteration (e.g. fetch), we might want to repeat steps?
        # Current logic: loop runs if iteration < max.
        # If we loaded a state with iteration=0, it enters here.
        while state.iteration < state.max_iterations:
            check_cancel()

            logger.info(f"\n{'=' * 60}")
            logger.info(f"📖 迭代 {state.iteration + 1}/{state.max_iterations}")
            logger.info(f"{'=' * 60}")

            # [P62] Record Iteration Start
            recorder.record_iteration_start(state.iteration + 1)

            # 4a. 执行检索
            logger.info("\n🔎 阶段 3: 文献获取")
            # Async Call
            state = await execute_search(state)

            # [P62] Record Search Stats
            if hasattr(state, "last_search_stats"):
                recorder.record_search_execution(
                    state.iteration + 1, state.last_search_stats
                )

            # [P86] 保存检查点
            save_checkpoint(job_id, state, f"search_iter{state.iteration}")

            check_cancel()

            if not state.paper_pool:
                logger.warning("未找到任何论文，终止迭代")
                break

            # 4b. 全文获取 (可选)
            # P23 Fix: 将同步的 Playwright 调用放入独立线程
            import asyncio

            logger.info("\n📥 阶段 3.5: 全文获取")
            # [P27] Explicitly pass interaction_callback
            # [P81] Pass cancel_callback for responsive termination
            state = await asyncio.to_thread(
                fetch,
                state,
                interaction_callback=interaction_callback,
                cancel_callback=cancel_callback,
            )

            # 检查用户是否取消
            if hasattr(state, "cancelled") and state.cancelled:
                logger.warning("任务已被用户取消")
                raise JobCancelledError("User cancelled via interaction")

            # [P86] 保存检查点
            save_checkpoint(job_id, state, f"fetch_iter{state.iteration}")

            check_cancel()

            # 4c. 证据提取 (指令6)
            logger.info("\n🔬 阶段 4: 证据抽取")
            state = extract_evidence(state)

            # [P86] 保存检查点
            save_checkpoint(job_id, state, f"extract_iter{state.iteration}")

            check_cancel()

            # 4c.5 机理假设验证 (New)
            from .hypothesis_evaluator import evaluate_hypotheses

            state = evaluate_hypotheses(state)

            check_cancel()

            if not state.evidence_set:
                logger.warning("未提取到有效证据，尝试扩展检索")
                # 创建一个默认的评估结果
                from .core_types import EvaluationResult, SufficiencyStatus

                state.evaluation = EvaluationResult(
                    is_sufficient=False,
                    status=SufficiencyStatus.INSUFFICIENT_QUANTITY,
                    reason="未提取到任何证据",
                    total_papers=len(state.paper_pool),
                    total_evidence=0,
                    cluster_count=0,
                    missing_variables=state.problem_spec.control_variables
                    if state.problem_spec
                    else [],
                    missing_metrics=state.problem_spec.performance_metrics
                    if state.problem_spec
                    else [],
                    suggested_expansions=["扩大搜索范围", "使用不同关键词"],
                )

                # [P62] Record Failed Evaluation
                recorder.record_evaluation(
                    state.iteration + 1, False, "No evidence extracted"
                )

                state = expand_search_space(state)
                state.iteration += 1
                continue

            # 4d. 方法归并 (指令8)
            logger.info("\n🔄 阶段 5: 方法归并")
            state = cluster(state)

            check_cancel()

            # 4e. 评估 (指令10)
            logger.info("\n⚖️ 阶段 6: 评估与充分性判断")
            state = evaluate(state)

            # [P86] 保存检查点
            save_checkpoint(job_id, state, f"evaluate_iter{state.iteration}")

            check_cancel()

            # [P61] 提取增量知识 (Instruction 6.5)
            from .learnings_extractor import extract_learnings

            old_learnings_count = len(state.learnings)
            state = extract_learnings(state)
            new_learnings = state.learnings[old_learnings_count:]

            # [P62] Record Learnings
            recorder.record_learnings(state.iteration + 1, new_learnings)

            # Record query history (P61)
            # Add executed keywords to query_history for persistence context
            state.query_history.extend(list(state.query_set.executed_keywords))
            # Dedup
            state.query_history = list(set(state.query_history))

            # [P62] Record Evaluation Result
            recorder.record_evaluation(
                state.iteration + 1,
                state.evaluation.is_sufficient,
                state.evaluation.reason,
            )

            # 4f. 充分性判断 (指令11)
            if state.evaluation.is_sufficient:
                logger.info("✅ 研究充分，准备生成结果")
                break
            else:
                logger.warning(f"⚠️ 研究不充分: {state.evaluation.reason}")

                if state.iteration + 1 >= state.max_iterations:
                    logger.warning("已达最大迭代次数，使用当前结果")
                    break

                # 4g. 扩展检索空间 (指令12)
                logger.info("\n🔄 扩展检索空间")
                state = expand_search_space(state)
                state.iteration += 1

        # 5. 生成最终结果
        logger.info("\n📝 阶段 7: 生成研究结果")
        state = generate_result(state)

        # [P32] Save with Chinese filename
        from .result_generator import save_report_with_chinese_name
        from config.settings import settings

        # [P59] Unified Output to PROJECTS_DIR
        # Save to data/projects/{job_id}/
        report_dir = settings.PROJECTS_DIR / state.job_id
        report_dir.mkdir(parents=True, exist_ok=True)  # Ensure dir exists
        saved_path = save_report_with_chinese_name(state, report_dir)
        state.final_report_path = saved_path  # Store for execution.py to use

        logger.info("\n" + "=" * 60)
        logger.info("🎉 迭代式深度研究完成")
        logger.info(f"   总迭代次数: {state.iteration + 1}")
        logger.info(f"   论文数量: {len(state.paper_pool)}")
        logger.info(f"   证据数量: {len(state.evidence_set)}")
        logger.info(f"   技术路线: {len(state.method_clusters)}")
        logger.info("=" * 60)

        return state

    except JobCancelledError as e:
        logger.warning(f"🛑 任务已被取消: {e}")
        state.cancelled = True
        return state

    finally:
        # P24: 确保资源清理 (浏览器等)
        logger.debug("研究流程结束，执行清理")
