"""
机理假设评估器 (Hypothesis Evaluator)
基于提取的证据，评估假设的状态（Active / Rejected）
"""
import logging
import json
import re
from typing import List
from core.ai import simple_chat
from .core_types import IterativeResearchState, Hypothesis, HypothesisStatus, Evidence
from .prompts import HYPOTHESIS_FALSIFICATION_PROMPT
from .data_normalizer import normalize_evidence_set
from .conflict_adjudicator import adjudicate_falsification

logger = logging.getLogger('deep_research')

def evaluate_hypotheses(state: IterativeResearchState) -> IterativeResearchState:
    """
    评估所有 Active 的假设，判断是否被证伪
    集成：数据归一化 -> LLM判断 -> 冲突仲裁
    P16 优化: 批量评估所有假设 (1次AI调用代替N次)
    """
    if not state.hypothesis_set or not state.evidence_set:
        return state
        
    logger.info("\n⚖️ 阶段 5.5: 机理假设验证与证伪")
    
    active_hypotheses = state.hypothesis_set.get_active_hypotheses()
    if not active_hypotheses:
        logger.warning("没有活跃的机理假设")
        return state

    # 1. 先进行数据归一化 (Data Normalizer)
    normalize_evidence_set(state.evidence_set)
    
    # 1.5 更新 falsifiable_allowed 标志
    for ev in state.evidence_set:
        ev.falsifiable_allowed = bool(ev.normalized_values)

    # 2. 准备本轮评估用的证据批次 (Taking last 20 to ensure enough context)
    current_evidence_batch = state.evidence_set[-20:]
    
    # 2.5 过滤出可用于证伪的证据 (falsifiable_allowed=True)
    falsifiable_batch = [ev for ev in current_evidence_batch if ev.falsifiable_allowed]
    
    evidence_text = _format_evidence(current_evidence_batch)  # 展示全部
    
    if not evidence_text:
        return state
    
    # P16: 批量评估所有假设
    # [P56] Partition into chunks to avoid context overflow and ensuring reliability
    BATCH_SIZE = 5
    
    # 转换为列表以便切片
    hypothesis_list = list(active_hypotheses)
    
    # Process in chunks
    for i in range(0, len(hypothesis_list), BATCH_SIZE):
        chunk = hypothesis_list[i : i + BATCH_SIZE]
        
        if len(chunk) == 1:
             _evaluate_single_hypothesis(chunk[0], evidence_text, falsifiable_batch, current_evidence_batch)
        else:
             _evaluate_batch_hypotheses(chunk, evidence_text, falsifiable_batch)
        
    return state

def _evaluate_single_hypothesis(h: Hypothesis, evidence_text: str, falsifiable_batch: List[Evidence], full_batch: List[Evidence]):
    """评估单个假设，包含仲裁逻辑"""
    prompt = HYPOTHESIS_FALSIFICATION_PROMPT.format(
        mechanism_description=h.mechanism_description,
        expected_performance_trend=h.expected_performance_trend,
        falsifiable_conditions="\n".join([f"- {c}" for c in h.falsifiable_conditions]),
        evidence_list=evidence_text
    )
    
    try:
        resp = simple_chat(prompt, json_mode=True)
        data = _parse_json(resp)
        
        is_falsified_claim = data.get("is_falsified", False)
        h.supporting_evidence_count = data.get("supporting_evidence_count", 0)
        
        if is_falsified_claim:
            # 3. 触发冲突仲裁 (Conflict Adjudicator)
            refuting_indices = data.get("refuting_evidence_indices", [])
            rejection_reason = data.get("rejection_reason", "")
            
            # 新签名: (confirmed, reason, evidence_ids, paper_keys)
            # 仲裁只使用 falsifiable_allowed=True 的证据
            confirmed, reason, _, _ = adjudicate_falsification(
                h, 
                refuting_indices, 
                falsifiable_batch,  # 仅使用可证伪的证据
                triggered_condition=rejection_reason,
                iteration=0
            )
            
            if confirmed:
                h.status = HypothesisStatus.REJECTED
                h.rejection_reason = reason
                logger.warning(f"❌ 假设 [{h.hypothesis_id}] 被证伪: {reason}")
            else:
                h.conflicting_evidence_count = len(refuting_indices)
                logger.info(f"🛡️ 假设 [{h.hypothesis_id}] 证伪被仲裁驳回: {reason}")
        else:
            h.conflicting_evidence_count = data.get("conflicting_evidence_count", 0)
            logger.info(f"✅ 假设 [{h.hypothesis_id}] 保持活跃 (支持: {h.supporting_evidence_count})")
            
    except Exception as e:
        logger.error(f"评估假设 {h.hypothesis_id} 失败: {e}")


def _evaluate_batch_hypotheses(hypotheses: List[Hypothesis], evidence_text: str, falsifiable_batch: List[Evidence]):
    """
    P16: 批量评估多个假设 (1次AI调用)
    将所有假设合并到一个Prompt中，返回每个假设的评估结果
    """
    # 构建批量Prompt
    hypotheses_text = ""
    for h in hypotheses:
        hypotheses_text += f"""
### 假设 {h.hypothesis_id}
机理描述: {h.mechanism_description}
预期趋势: {h.expected_performance_trend}
证伪条件:
{chr(10).join([f"  - {c}" for c in h.falsifiable_conditions])}
---
"""
    
    batch_prompt = f"""批量评估以下机理假设是否被证据证伪。

## 假设列表
{hypotheses_text}

## 证据列表
{evidence_text}

请对每个假设分别评估，返回JSON对象:
{{
  "<hypothesis_id>": {{
    "is_falsified": true/false,
    "supporting_evidence_count": N,
    "conflicting_evidence_count": N,
    "refuting_evidence_indices": [1, 3] (如果被证伪),
    "rejection_reason": "..." (如果被证伪)
  }},
  ...
}}
"""
    
    try:
        resp = simple_chat(batch_prompt, json_mode=True)
        data = _parse_json(resp)
        
        # 处理每个假设的结果
        for h in hypotheses:
            result = data.get(h.hypothesis_id, {})
            if not result:
                logger.warning(f"假设 {h.hypothesis_id} 无批量评估结果")
                continue
            
            is_falsified = result.get("is_falsified", False)
            h.supporting_evidence_count = result.get("supporting_evidence_count", 0)
            
            if is_falsified:
                refuting_indices = result.get("refuting_evidence_indices", [])
                rejection_reason = result.get("rejection_reason", "")
                
                confirmed, reason, _, _ = adjudicate_falsification(
                    h, refuting_indices, falsifiable_batch,
                    triggered_condition=rejection_reason, iteration=0
                )
                
                if confirmed:
                    h.status = HypothesisStatus.REJECTED
                    h.rejection_reason = reason
                    logger.warning(f"❌ 假设 [{h.hypothesis_id}] 被证伪: {reason}")
                else:
                    h.conflicting_evidence_count = len(refuting_indices)
                    logger.info(f"🛡️ 假设 [{h.hypothesis_id}] 证伪被仲裁驳回: {reason}")
            else:
                h.conflicting_evidence_count = result.get("conflicting_evidence_count", 0)
                logger.info(f"✅ 假设 [{h.hypothesis_id}] 保持活跃 (支持: {h.supporting_evidence_count})")
                
    except Exception as e:
        logger.error(f"批量评估假设失败: {e}")
        # 降级: 逐个评估
        for h in hypotheses:
            _evaluate_single_hypothesis(h, evidence_text, falsifiable_batch, [])

def _format_evidence(evidence_list: List[Evidence]) -> str:
    """格式化证据列表，优先展示归一化数据"""
    lines = []
    for i, e in enumerate(evidence_list):
        lines.append(f"Evidence {i+1} (Paper: {e.paper_id}):")
        lines.append(f"  Impl: {e.implementation}")
        
        if e.normalized_values:
            lines.append(f"  Data (Standardized): {e.normalized_values}")
            # lines.append(f"  Units: {e.unit_map}")
        else:
            lines.append(f"  Data (Raw): {e.key_variables} | {e.performance_results}")
            
        lines.append("---")
    return "\n".join(lines)

def _parse_json(text: str) -> dict:
    try:
        if "```" in text:
            pattern = r"```(?:json)?\s*(.*?)```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                text = match.group(1)
        
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            text = text[start:end+1]
            return json.loads(text)
        return json.loads(text)
    except Exception:
        return {}
