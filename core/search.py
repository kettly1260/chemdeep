import json
import logging
from config.settings import settings
from core.ai import AIClient, MODEL_STATE
from core.reasoning import (
    NeedInferenceEngine,
    LiteratureGapAnalyzer,
    RequirementRefiner,
)
from core.scholar_search import UnifiedSearcher
from apps.telegram_bot.client import TelegramClient
from utils.db import DB

logger = logging.getLogger("search")


class SearchOrchestrator:
    def __init__(self, db: DB):
        self.db = db
        self.tg = TelegramClient()

    def process_request(self, request_id: str):
        """处理研究请求，生成搜索策略并反馈"""
        row = self.db._conn.execute(
            "SELECT * FROM research_requests WHERE request_id = ?", (request_id,)
        ).fetchone()

        if not row:
            return

        user_query = row["user_query"]
        chat_id = row["chat_id"]

        def notify(msg: str):
            self.tg.send_message(chat_id, msg)

        ai = AIClient(notify_callback=notify)

        # 先检查 AI 连接状态
        notify("🔍 正在检查 AI 连接...")
        connection_status = ai.test_connection()

        openai_ok = connection_status.get("openai", {}).get("status") == "ok"
        gemini_ok = connection_status.get("gemini", {}).get("status") == "ok"

        if not openai_ok and not gemini_ok:
            openai_err = connection_status.get("openai", {}).get("error", "未配置")
            gemini_err = connection_status.get("gemini", {}).get("error", "未配置")
            notify(f"❌ AI 连接失败:\n• OpenAI: {openai_err}\n• Gemini: {gemini_err}")
            self._send_fallback_strategy(chat_id, user_query)
            return

        # 使用全局 MODEL_STATE 获取当前模型
        current_model = MODEL_STATE.openai_model
        notify(f"🤖 使用 OpenAI ({current_model}) 生成策略...")

        # 生成策略
        result = ai.generate_search_strategy(user_query)

        if result.success:
            strategy = result.data
            self.db.update_request_strategy(request_id, strategy)

            # 使用实际返回的模型信息
            actual_model = result.model or current_model
            strategy_msg = self._format_strategy(
                strategy, result.provider, actual_model
            )
            notify(strategy_msg)
            self._send_wos_instructions(chat_id, strategy)
        else:
            notify(f"❌ AI 生成策略失败: {result.error}")
            self._send_fallback_strategy(chat_id, user_query)

    def _format_strategy(self, strategy: dict, provider: str, model: str) -> str:
        keywords = strategy.get("keywords", [])
        boolean_query = strategy.get("boolean_query", "")
        google_query = strategy.get("google_scholar_query", "")
        databases = strategy.get("databases", ["WoS"])
        goal = strategy.get("goal", "synthesis")
        max_results = strategy.get("max_results", 50)
        rationale = strategy.get("rationale", "")

        lines = [
            f"📊 搜索策略 (by {provider}/{model})",
            "",
            f"🔑 关键词: {', '.join(keywords)}",
            "",
            "📝 WoS 检索式:",
            f"{boolean_query}",
            "",
            f"🔍 Google Scholar: {google_query}",
            "",
            f"📁 数据库: {', '.join(databases)}",
            f"🎯 目标: {goal}",
            f"📄 最大结果: {max_results}",
        ]

        if rationale:
            lines.extend(["", f"💡 说明: {rationale}"])

        return "\n".join(lines)

    def _send_fallback_strategy(self, chat_id: int, user_query: str):
        strategy = {
            "keywords": [user_query],
            "boolean_query": f'TS=("{user_query}")',
            "google_scholar_query": user_query,
            "max_results": 20,
            "goal": "synthesis",
            "databases": ["WoS"],
        }
        self.tg.send_message(chat_id, "📋 使用基本检索策略:")
        self.tg.send_message(
            chat_id, self._format_strategy(strategy, "fallback", "none")
        )
        self._send_wos_instructions(chat_id, strategy)

    def _send_wos_instructions(self, chat_id: int, strategy: dict):
        boolean_query = strategy.get("boolean_query", "")
        goal = strategy.get("goal", "synthesis")
        max_results = strategy.get("max_results", 50)

        instructions = f"""📚 Web of Science 导出步骤

1️⃣ 访问: https://www.webofscience.com

2️⃣ 粘贴检索式:
{boolean_query}

3️⃣ 筛选条件:
   • 时间: 最近5年
   • 类型: Article, Review
   • 语言: English

4️⃣ 导出设置:
   • 格式: Tab delimited file (.txt)
   • 字段: Full Record

5️⃣ 保存文件后发送命令:
/run <文件路径> goal={goal} max={max_results}

或者使用自动搜索:
/wos {boolean_query[:100]}...

或者使用免费数据源:
/search {strategy.get("google_scholar_query", "")} sources=openalex,crossref

或者使用烂番薯学术（国内友好）:
/search {strategy.get("google_scholar_query", "")} sources=lanfanshu

🚀 一键搜索所有源并推理:
/searchall {strategy.get("google_scholar_query", "")}"""
        self.tg.send_message(chat_id, instructions)

    def infer_needs_from_papers(
        self, user_query: str, papers: list[dict], goal: str = "general"
    ):
        """
        通过文献分析推断用户需求

        Args:
            user_query: 用户原始查询
            papers: 搜索到的论文列表
            goal: 研究目标

        Returns:
            ReasoningResult: 推理结果
        """

        def notify(msg: str):
            logger.info(msg)

        ai = AIClient(notify_callback=notify)
        engine = NeedInferenceEngine(ai_client=ai, notify_callback=notify)

        return engine.infer_from_papers(user_query, papers, goal)

    def analyze_research_gaps(self, research_topic: str, papers: list[dict]):
        """
        分析研究空白

        Args:
            research_topic: 研究主题
            papers: 搜索到的论文列表

        Returns:
            dict: 分析结果
        """

        def notify(msg: str):
            logger.info(msg)

        ai = AIClient(notify_callback=notify)
        analyzer = LiteratureGapAnalyzer(ai_client=ai, notify_callback=notify)

        return analyzer.analyze_gaps(research_topic, papers)

    def refine_user_requirement(
        self, original_query: str, papers: list[dict], user_context: dict | None = None
    ):
        """
        细化用户需求

        Args:
            original_query: 原始查询
            papers: 搜索到的论文列表
            user_context: 用户上下文

        Returns:
            dict: 细化结果
        """

        def notify(msg: str):
            logger.info(msg)

        ai = AIClient(notify_callback=notify)
        refiner = RequirementRefiner(ai_client=ai, notify_callback=notify)

        return refiner.refine_requirement(original_query, papers, user_context)

    def search_and_infer(
        self,
        query: str,
        chat_id: int,
        sources: list[str] | None = None,
        max_results: int = 50,
        goal: str = "general",
        headless: bool = False,
    ):
        """
        搜索所有源并进行需求推理

        Args:
            query: 搜索查询
            chat_id: Telegram chat ID
            sources: 搜索源列表，默认 ["openalex", "crossref", "lanfanshu"]
            max_results: 最大结果数
            goal: 研究目标
            headless: 是否无头模式

        Returns:
            dict: 包含搜索结果和推理结果
        """

        def notify(msg: str):
            self.tg.send_message(chat_id, msg)

        if sources is None:
            sources = ["openalex", "crossref", "lanfanshu"]

        # 1. 搜索文献
        notify(f"🔍 开始多源搜索: {', '.join(sources)}")

        searcher = UnifiedSearcher(notify_callback=notify)
        search_results = searcher.search(
            query,
            sources=sources,
            max_results=max_results,
            headless=headless,
            parallel=True,
        )

        if not search_results["success"]:
            notify(f"❌ 搜索失败: {search_results.get('errors', {})}")
            return search_results

        papers = search_results["papers"]
        notify(f"✅ 共找到 {len(papers)} 篇论文")

        # 2. 推理需求
        notify("🧠 正在分析文献，推断研究需求...")

        ai = AIClient(notify_callback=notify)
        engine = NeedInferenceEngine(ai_client=ai, notify_callback=notify)
        reasoning_result = engine.infer_from_papers(query, papers, goal)

        # 3. 分析研究空白
        notify("🔍 正在分析研究空白...")
        gap_analyzer = LiteratureGapAnalyzer(ai_client=ai, notify_callback=notify)
        gap_result = gap_analyzer.analyze_gaps(query, papers)

        # 4. 汇总结果
        result = {
            "search": search_results,
            "reasoning": reasoning_result,
            "gaps": gap_result,
        }

        # 5. 生成报告
        report = self._generate_comprehensive_report(result, query)
        notify(report)

        return result

    def _generate_comprehensive_report(self, result: dict, query: str) -> str:
        """生成综合报告"""
        search = result.get("search", {})
        reasoning = result.get("reasoning")
        gaps = result.get("gaps", {})

        lines = [
            "📊 综合搜索与推理报告",
            "=" * 50,
            f"🔍 查询: {query}",
            "",
            "📚 搜索结果:",
            f"  • 共找到 {search.get('count', 0)} 篇论文",
            f"  • 来源: {', '.join(search.get('sources_used', []))}",
            "",
        ]

        # 各源统计
        if search.get("sources_stats"):
            lines.append("📈 各源统计:")
            for source, count in search["sources_stats"].items():
                lines.append(f"  • {source}: {count} 篇")
            lines.append("")

        # 推理结果
        if reasoning and reasoning.success:
            lines.append("🧠 需求推理:")
            lines.append(f"  • 置信度: {reasoning.confidence_score:.0%}")

            if reasoning.inferred_needs:
                lines.append("  • 推断需求:")
                for need in reasoning.inferred_needs[:3]:
                    lines.append(f"    - {need}")

            if reasoning.research_directions:
                lines.append("  • 研究方向:")
                for direction in reasoning.research_directions[:3]:
                    lines.append(f"    - {direction}")
            lines.append("")

        # 研究空白
        if gaps.get("success"):
            lines.append("🔬 研究空白:")
            for gap in gaps.get("gaps", [])[:3]:
                lines.append(f"  • {gap.get('description', '')}")
            lines.append("")

        # 推荐
        if reasoning and reasoning.recommendations:
            lines.append("📝 研究建议:")
            for rec in reasoning.recommendations[:3]:
                lines.append(f"  • {rec}")

        return "\n".join(lines)

    def search_all_sources(
        self, query: str, chat_id: int, max_results: int = 50, headless: bool = False
    ):
        """
        搜索所有可用数据源并汇总

        等同于 search_and_infer 使用默认参数
        """
        return self.search_and_infer(
            query=query,
            chat_id=chat_id,
            sources=["openalex", "crossref", "lanfanshu"],
            max_results=max_results,
            headless=headless,
        )
