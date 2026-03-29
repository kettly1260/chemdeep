"""
数据归一化模块 (Data Normalizer)
负责将提取的非结构化/多单位数据转换为标准数值，便于后续校验
"""
import logging
import json
import re
from typing import List, Dict, Any
from core.ai import simple_chat
from .core_types import Evidence
from .prompts import DATA_NORMALIZATION_PROMPT

logger = logging.getLogger('deep_research')

def normalize_evidence_set(evidence_list: List[Evidence]) -> List[Evidence]:
    """
    批量归一化证据集 (In-place update)
    """
    count = 0
    for ev in evidence_list:
        # 如果尚未归一化 (通过检查 normalized_values 是否为空)
        # 注意: 即使归一化后为空(无数据)，也应该标记。这里暂简单判断。
        if not ev.normalized_values and (ev.key_variables or ev.performance_results):
            normalize_single_evidence(ev)
            count += 1
            
    if count > 0:
        logger.info(f"⚖️ 已归一化 {count} 条新证据的数据")
        
    return evidence_list


def normalize_single_evidence(evidence: Evidence) -> Evidence:
    """对单个证据进行数据归一化"""
    
    # 合并待处理数据
    raw_data = {**evidence.key_variables, **evidence.performance_results}
    if not raw_data:
        return evidence

    prompt = DATA_NORMALIZATION_PROMPT.format(
        data_json=json.dumps(raw_data, ensure_ascii=False, indent=2)
    )

    try:
        resp = simple_chat(prompt, json_mode=True)
        norm_map = _parse_json(resp)
        
        norm_values = {}
        units = {}
        
        for k, v in norm_map.items():
            if isinstance(v, dict):
                val = v.get("value")
                unit = v.get("unit")
                
                # 仅存储有效的数值
                if val is not None:
                    try:
                        norm_values[k] = float(val)
                    except (ValueError, TypeError):
                        pass
                        
                if unit:
                    units[k] = unit
        
        evidence.normalized_values = norm_values
        evidence.unit_map = units
        
    except Exception as e:
        logger.warning(f"数据归一化失败 (Paper {evidence.paper_id}): {e}")
        
    return evidence


def _parse_json(text: str) -> dict:
    try:
        if "```" in text:
            pattern = r"```(?:json)?\s*(.*?)```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                text = match.group(1)
        
        # 尝试查找 JSON 对象
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            text = text[start:end+1]
            return json.loads(text)
            
        return json.loads(text)
    except Exception:
        return {}
