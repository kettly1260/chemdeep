"""
Paper Screener Module
"""
import json
import logging
from typing import Callable, Any
from core.ai import AIClient
from .prompts import PAPER_SCREENING_PROMPT

logger = logging.getLogger('deep_research')

class PaperScreener:
    def __init__(self, notify: Callable[[str], None]):
        self.notify = notify

    def screen_papers(self, question: str, papers: list[dict], batch_size: int = 5) -> list[dict]:
        """
        对搜索结果进行 LLM 复筛
        
        Args:
            question: 研究问题
            papers: 搜索到的论文列表
            batch_size: 每批处理的论文数量
            
        Returns:
            筛选后的论文列表 (包含评分和标签)
        """
        if not papers:
            return []
            
        self.notify(f"🧠 开始智能筛选 {len(papers)} 篇论文...")
        
        filtered_papers = []
        
        # 分批处理
        for i in range(0, len(papers), batch_size):
            batch = papers[i:i+batch_size]
            batch_results = self._process_batch(question, batch, i)
            filtered_papers.extend(batch_results)
            self.notify(f"  - 已筛选 {min(i+batch_size, len(papers))}/{len(papers)} 篇")
            
        # 根据总分排序
        filtered_papers.sort(key=lambda x: x.get("screening", {}).get("total_score", 0), reverse=True)
        
        return filtered_papers

    def _process_batch(self, question: str, batch: list[dict], start_idx: int) -> list[dict]:
        # 构造极简输入格式
        papers_text = ""
        for j, p in enumerate(batch):
            idx = start_idx + j + 1
            # 优先使用摘要，如果没有则标记缺失
            abstract = (p.get("abstract") or p.get("snippet") or "No abstract available").strip()
            # 截断过长的摘要以节省 token
            if len(abstract) > 1000:
                abstract = abstract[:1000] + "..."
                
            papers_text += f"[{idx}]\n"
            papers_text += f"Title: {p.get('title', 'Unknown')}\n"
            papers_text += f"Journal/Year: {p.get('source', 'Unknown')} / {p.get('year', 'Unknown')}\n"
            papers_text += f"Abstract: {abstract}\n\n"

        from core.ai import get_ai_client
        ai = get_ai_client()
        prompt = PAPER_SCREENING_PROMPT.format(question=question, papers_text=papers_text)
        
        result = ai.call(prompt, json_mode=True)
        
        processed_batch = []
        scores_map = {}
        
        if result.success:
            try:
                data = result.data
                if isinstance(data, dict) and data.get("text"):
                     # 如果返回了包装结构，尝试提取 JSON
                     text = data.get("text", "")
                     json_data = self._extract_json(text)
                     if json_data:
                         scores_list = json.loads(json_data)
                     else:
                         scores_list = []
                elif isinstance(data, list):
                    scores_list = data
                else:
                    logger.warning(f"Unexpected screening result format: {type(data)}")
                    scores_list = []
                
                # 建立索引映射
                for item in scores_list:
                    if "index" in item:
                        scores_map[item["index"]] = item
            except Exception as e:
                logger.error(f"解析筛选结果失败: {e}")
        
        # 将评分合并回论文数据
        for j, p in enumerate(batch):
            idx = start_idx + j + 1
            score_data = scores_map.get(idx)
            
            p_copy = p.copy()
            if score_data:
                p_copy["screening"] = {
                    "total_score": score_data.get("total_score", 0),
                    "label": score_data.get("label", "可忽略"),
                    "reason": score_data.get("reason", ""),
                    "scores": score_data.get("scores", {})
                }
            else:
                # 如果 AI 没返回这篇，默认为低分
                p_copy["screening"] = {
                    "total_score": 0,
                    "label": "未评分",
                    "reason": "AI 未返回评分",
                    "scores": {}
                }
            processed_batch.append(p_copy)
            
        return processed_batch

    def _extract_json(self, text: str) -> str | None:
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            return text[start:end].strip()
        elif "[" in text and "]" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            return text[start:end]
        return None

# --- Phase A-4: Executor "State-Only" Interface ---
from .types import ResearchState

def screen(state: ResearchState) -> ResearchState:
    """
    [New] 纯状态驱动的筛选逻辑
    输入: state.paper_pool (原始论文)
    输出: state.paper_pool (带 screening 字段), state.intermediate_results["screening"]
    """
    # 临时通知回调适配 (main.py 应该设置某种全局 logger 或 callback)
    # 这里简单打印或忽略
    def temp_notify(msg):
        logger.info(msg)
        
    papers = state.paper_pool
    if not papers:
        logger.warning("No papers in state.paper_pool to screen.")
        return state
        
    question_text = state.question.question # accessing ResearchQuestion.question
    
    # Simple constraints from plan if available
    # criteria = state.plan.criteria if state.plan else {}
    
    screener = PaperScreener(temp_notify)
    # Reuse existing logic
    screened_papers = screener.screen_papers(question_text, papers)
    
    # Filter only relevant papers? Or just keep all with scores?
    # Usually we want to keep all but marked with relevance.
    state.paper_pool = screened_papers
    
    # Update intermediate results
    relevant_count = sum(1 for p in screened_papers if p.get("screening", {}).get("total_score", 0) >= 5)
    state.intermediate_results["screening"] = {
        "status": "completed",
        "total_screened": len(papers),
        "relevant_count": relevant_count
    }
    
    return state
