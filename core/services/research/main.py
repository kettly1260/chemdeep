"""
Deep Researcher Facade
"""
import time
import json
import logging
from pathlib import Path
from typing import Callable, Any

from config.settings import settings
from .types import ResearchPlan
from .planner import ResearchPlanner
from .executor import SearchExecutor
from .reporter import ReportGenerator
from .screener import PaperScreener
# from .decomposer import GoalDecomposer  # Moved to formalizer.py
from .extractor import EvidenceExtractor
from .synthesizer import MethodSynthesizer
from .evaluator import ResearchEvaluator

logger = logging.getLogger('deep_research')

class DeepResearcher:
    """深度研究器门面"""
    
    def __init__(self, notify_callback: Callable[[str], None] | None = None):
        self.notify = notify_callback or (lambda x: print(x))
        self.research_dir = settings.LIBRARY_DIR / "deep_research"
        self.research_dir.mkdir(parents=True, exist_ok=True)
        
        self.planner = ResearchPlanner(self.notify)
        self.executor = SearchExecutor(self.notify)
        self.reporter = ReportGenerator(self.notify)
        self.screener = PaperScreener(self.notify)
        
        # Iterative Workflow Components (deprecated - use iterative_main.py instead)
        # self.decomposer = GoalDecomposer(self.notify)  # Moved to formalizer.py
        self.extractor = EvidenceExtractor(self.notify)
        self.synthesizer = MethodSynthesizer(self.notify)
        self.evaluator = ResearchEvaluator(self.notify)

    def generate_plan(self, question: str) -> ResearchPlan:
        return self.planner.generate_plan(question)
    
    def format_plan(self, plan: ResearchPlan) -> str:
        return self.planner.format_plan_text(plan)
    
    def execute_search(self, plan: ResearchPlan, max_per_source: int = 50, top_n: int = 20) -> dict:
        # 1. 执行宽泛搜索
        raw_result = self.executor.execute(plan, max_per_source)
        raw_papers = raw_result.get("papers", [])
        
        if not raw_papers:
            return raw_result
            
        # 2. 执行 LLM 智能筛选
        screened_papers = self.screener.screen_papers(plan.question, raw_papers)
        
        # 3. 过滤并保留 Top N
        # 规则: >=9 必读, <=5 丢弃
        kept_papers = []
        ignored_count = 0
        
        for p in screened_papers:
            score = p.get("screening", {}).get("total_score", 0)
            if score <= 5:
                ignored_count += 1
                continue
            kept_papers.append(p)
            
        # 截取 Top N
        final_papers = kept_papers[:top_n]
        
        self.notify(f"🎯 筛选完成: 原始 {len(raw_papers)} -> 保留 {len(final_papers)} (丢弃 {ignored_count} 篇低分)\n"
                    f"Top 3 推荐:\n" +
                    "\n".join([f"  {i+1}. [{p['screening']['total_score']}] {p.get('title')[:40]}..." 
                              for i, p in enumerate(final_papers[:3])]))

        return {
            "papers": final_papers,
            "count": len(final_papers),
            "sources_used": raw_result.get("sources_used", []),
            "errors": raw_result.get("errors", {}),
            "raw_count": len(raw_papers)
        }
    
    def generate_report(self, question: str, objectives: list[str], analyses: list[dict]) -> str:
        return self.reporter.generate(question, objectives, analyses)
    
    def run_iterative_research(self, goal: str, max_iterations: int = 2) -> dict:
        """运行迭代式研究工作流"""
        research_id = f"dr_iter_{int(time.time())}"
        
        # 1. 目标拆解
        decomposed, queries = self.decomposer.decompose(goal)
        
        all_papers = []
        all_evidence = []
        seen_dois = set()
        
        current_queries = queries
        
        for iteration in range(max_iterations):
            self.notify(f"🔄 迭代轮次 {iteration + 1}/{max_iterations}")
            
            # 2. 文献获取 (MCP)
            # Use ephemeral plan for execution
            # Convert queries dict list to ResearchPlan structure or just execute manually
            # We reuse executor._execute_single_query logic? No, easier to compose a dummy plan.
            from .types import ResearchPlan
            temp_plan = ResearchPlan(question=goal, search_queries=current_queries)
            
            search_result = self.executor.execute(temp_plan, max_per_source=20)
            new_papers = search_result.get("papers", [])
            
            # Deduplicate
            unique_new = []
            for p in new_papers:
                doi = (p.get("doi") or "").lower()
                if doi and doi not in seen_dois:
                    seen_dois.add(doi)
                    unique_new.append(p)
                elif not doi:
                    unique_new.append(p) # Keep no-DOI papers? maybe duplicate risk but okay.
            
            if not unique_new:
                self.notify("⚠️ 本轮未发现新文献")
                break
                
            all_papers.extend(unique_new)
            
            # 2.5. 全文获取 (使用现有 fetcher 服务)
            if unique_new:
                unique_new = self._fetch_paper_contents(unique_new, max_papers=10)
            
            # 3. 证据抽取 (LLM)
            # Only extract from NEW papers to save tokens
            new_evidence = self.extractor.extract_evidence(
                unique_new, 
                decomposed.research_object, 
                decomposed.control_variables
            )
            all_evidence.extend(new_evidence)
            
            # 4. 方法归并 (LLM)
            synthesis_result = self.synthesizer.synthesize(goal, all_evidence)
            method_clusters = synthesis_result.get("method_clusters", [])
            
            # 5. 充分性判断 (LLM)
            sufficiency = self.evaluator.check_sufficiency(goal, method_clusters, len(all_papers))
            
            if sufficiency.get("sufficient", False):
                self.notify("✅ 研究覆盖度已满足要求，停止迭代。")
                break
            else:
                reason = sufficiency.get("reason", "未知原因")
                missing = sufficiency.get("missing_aspects", [])
                self.notify(f"🤔 覆盖度不足: {reason} (缺失: {', '.join(missing)})")
                
                # Expand queries
                suggested = sufficiency.get("suggested_queries", [])
                if suggested:
                    current_queries = suggested
                    self.notify(f"🔍 扩展搜索条件: {len(suggested)} 个新方向")
                else:
                    self.notify("⚠️ 未获得扩展建议，停止迭代。")
                    break
        
        # Final Synthesis
        final_synthesis = self.synthesizer.synthesize(goal, all_evidence)
        
        # Save results
        r_dir = self.research_dir / research_id
        r_dir.mkdir(parents=True, exist_ok=True)
        
        report_path = r_dir / "report.md"
        report_path.write_text(final_synthesis.get("synthesis_text", ""), encoding="utf-8")
        
        return {
            "research_id": research_id,
            "goal": goal,
            "decomposed": decomposed.to_dict(),
            "evidence_count": len(all_evidence),
            "paper_count": len(all_papers),
            "report_path": str(report_path),
            "result": final_synthesis
        }
    
    def _fetch_paper_contents(self, papers: list[dict], max_papers: int = 10) -> list[dict]:
        """使用现有 fetcher 服务获取论文全文"""
        from playwright.sync_api import sync_playwright
        from core.browser.edge_launcher import launch_real_edge_with_cdp, connect_to_real_browser
        from core.services.fetcher.single_fetch import _navigate_to_paper, _handle_potential_cf
        from core.services.fetcher.parsers import html_to_markdown
        import threading
        
        papers_with_doi = [p for p in papers if p.get("doi")][:max_papers]
        
        if not papers_with_doi:
            return papers
            
        self.notify(f"📥 正在获取 {len(papers_with_doi)} 篇论文全文...")
        
        CDP_PORT = 9222
        cf_lock = threading.Lock()
        cf_domains_warned = set()
        
        try:
            # 检查浏览器是否已运行，如果没有则启动
            from core.browser.edge_launcher import is_real_browser_running
            import time as t
            
            # 先检查几次 (浏览器可能刚启动 CDP 还未就绪)
            browser_ready = False
            for _ in range(3):
                if is_real_browser_running(CDP_PORT):
                    browser_ready = True
                    break
                t.sleep(1)
            
            if browser_ready:
                self.notify(f"🌐 Edge 浏览器已在端口 {CDP_PORT} 运行")
            else:
                success, msg = launch_real_edge_with_cdp(CDP_PORT)
                if not success:
                    # 再检查一次，有时启动成功但检测延迟
                    t.sleep(2)
                    if is_real_browser_running(CDP_PORT):
                        self.notify(f"🌐 Edge 浏览器已在端口 {CDP_PORT} 运行 (延迟检测)")
                    else:
                        self.notify(f"⚠️ 浏览器启动问题: {msg}，跳过全文获取")
                        # 不返回，继续使用摘要
                else:
                    self.notify(f"🌐 {msg}")
            
            with sync_playwright() as pw:
                context = connect_to_real_browser(pw, CDP_PORT)
                if not context:
                    self.notify("⚠️ 无法连接到浏览器")
                    return papers
                
                for p_data in papers_with_doi:
                    doi = p_data.get("doi")
                    url = f"https://doi.org/{doi}"
                    page = None
                    
                    try:
                        page = context.new_page()
                        _navigate_to_paper(page, url, settings.RATE_SECONDS)
                        
                        # 复用 fetcher 的 CF 处理逻辑
                        landing_url, html = _handle_potential_cf(
                            page, self, False, cf_lock, cf_domains_warned
                        )
                        
                        if html:
                            md = html_to_markdown(html)
                            p_data["full_content"] = md
                        else:
                            p_data["full_content"] = None
                            
                    except Exception as e:
                        logger.warning(f"抓取 {doi} 失败: {e}")
                        p_data["full_content"] = None
                    finally:
                        if page:
                            try:
                                page.close()
                            except:
                                pass
                                
            fetched = len([p for p in papers if p.get("full_content")])
            self.notify(f"✅ 成功获取 {fetched}/{len(papers_with_doi)} 篇全文")
            
        except Exception as e:
            logger.error(f"全文获取失败: {e}")
            
        return papers

    def save_search_results(self, research_id: str, papers: list[dict]) -> Path:
        """保存搜索结果"""
        r_dir = self.research_dir / research_id
        r_dir.mkdir(parents=True, exist_ok=True)
        
        # Save TSV
        tsv_path = r_dir / "papers.txt"
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("TI\tDO\tAU\tPY\tSO\n")
            for p in papers:
                title = (p.get("title") or "").replace("\t", " ").replace("\n", " ")
                doi = p.get("doi") or ""
                authors = (p.get("authors") or "").replace("\t", " ")
                year = str(p.get("year") or "")
                source = (p.get("source") or "").replace("\t", " ")
                f.write(f"{title}\t{doi}\t{authors}\t{year}\t{source}\n")
        
        # Save JSON
        json_path = r_dir / "papers.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(papers, f, ensure_ascii=False, indent=2)
            
        return tsv_path

    def run_full_research(self, question: str) -> dict:
        research_id = f"dr_{int(time.time())}"
        
        plan = self.generate_plan(question)
        search_result = self.execute_search(plan)
        
        if search_result["count"] == 0:
            return {
                "success": False, 
                "error": "No papers found", 
                "research_id": research_id
            }
            
        papers_file = self.save_search_results(research_id, search_result["papers"])
        
        return {
            "success": True,
            "research_id": research_id,
            "plan": plan.to_dict(),
            "papers_file": str(papers_file),
            "paper_count": search_result["count"],
            "sources_used": search_result["sources_used"],
        }

# --- Phase A-3: Main "Pure Flow Director" ---
from .types import ResearchQuestion, ResearchState
from .planner import build_plan
from .executor import search
from .content_fetch import fetch
from .screener import screen
from .extractor import extract
from .synthesizer import synthesize
from .reporter import report

def run_research(question_text: str) -> ResearchState:
    """
    [New] 纯流程导演函数
    顺序调用各模块，不做决策
    """
    logger.info(f"🚀 Starting research run: {question_text}")
    
    # 1. Initialize State
    state = ResearchState(
        question=ResearchQuestion(question=question_text)
    )

    # 2. Plan
    state.plan = build_plan(state.question)
    logger.info("✅ Plan generated")

    # 3. Execution Phase
    # Search
    state = search(state)
    logger.info(f"✅ Search completed: {len(state.paper_pool)} papers")
    
    # Fetch Content
    state = fetch(state)
    logger.info("✅ Content fetching completed")
    
    # Screen
    state = screen(state)
    logger.info("✅ Screening completed")
    
    # Extract
    state = extract(state)
    logger.info(f"✅ Extraction completed: {len(state.evidence)} items")
    
    # Synthesize
    state = synthesize(state)
    logger.info("✅ Synthesis completed")
    
    # 4. Report
    state.final_report = report(state)
    logger.info("✅ Report generated")

    return state
