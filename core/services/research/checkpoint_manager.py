"""
[P86] 检查点管理器
用于保存和恢复中断任务的状态
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import asdict, is_dataclass
from enum import Enum

from config.settings import settings

logger = logging.getLogger('deep_research')

CHECKPOINT_DIR = settings.BASE_DIR / "data" / "checkpoints"


def _serialize_value(obj: Any) -> Any:
    """递归序列化复杂对象"""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_serialize_value(item) for item in obj]
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, dict):
        return {k: _serialize_value(v) for k, v in obj.items()}
    if is_dataclass(obj) and not isinstance(obj, type):
        # dataclass 实例
        return {k: _serialize_value(v) for k, v in asdict(obj).items()}
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    # 其他无法序列化的对象转为字符串
    return str(obj)


def save_checkpoint(job_id: str, state: Any, phase: str = "unknown") -> bool:
    """
    保存检查点
    
    Args:
        job_id: 任务ID
        state: IterativeResearchState 对象
        phase: 当前阶段名称 (formalize/search/fetch/extract/evaluate)
    
    Returns:
        是否保存成功
    """
    try:
        checkpoint_path = CHECKPOINT_DIR / job_id
        checkpoint_path.mkdir(parents=True, exist_ok=True)
        
        # 序列化状态
        state_dict = _serialize_value(state)
        
        # 添加元数据
        checkpoint_data = {
            "job_id": job_id,
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
            "state": state_dict
        }
        
        # 保存 JSON
        checkpoint_file = checkpoint_path / "state.json"
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 检查点已保存: {job_id} (阶段: {phase})")
        return True
        
    except Exception as e:
        logger.error(f"保存检查点失败: {e}")
        return False


def load_checkpoint(job_id: str) -> Optional[Dict[str, Any]]:
    """
    加载检查点
    
    Args:
        job_id: 任务ID
    
    Returns:
        检查点数据字典，包含 job_id, phase, timestamp, state
        如果不存在则返回 None
    """
    try:
        checkpoint_file = CHECKPOINT_DIR / job_id / "state.json"
        
        if not checkpoint_file.exists():
            return None
        
        with open(checkpoint_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info(f"📂 检查点已加载: {job_id} (阶段: {data.get('phase', 'unknown')})")
        return data
        
    except Exception as e:
        logger.error(f"加载检查点失败: {e}")
        return None


def delete_checkpoint(job_id: str) -> bool:
    """
    删除检查点 (任务完成后清理)
    
    Args:
        job_id: 任务ID
    
    Returns:
        是否删除成功
    """
    try:
        checkpoint_path = CHECKPOINT_DIR / job_id
        
        if checkpoint_path.exists():
            import shutil
            shutil.rmtree(checkpoint_path)
            logger.info(f"🗑️ 检查点已删除: {job_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"删除检查点失败: {e}")
        return False


def find_checkpoint_by_goal(goal: str) -> Optional[Dict[str, Any]]:
    """
    根据目标查找检查点
    
    Args:
        goal: 研究目标文本
    
    Returns:
        最近的检查点数据，如果没有则返回 None
    """
    try:
        if not CHECKPOINT_DIR.exists():
            return None
        
        # 遍历所有检查点
        candidates = []
        for cp_dir in CHECKPOINT_DIR.iterdir():
            if not cp_dir.is_dir():
                continue
            
            state_file = cp_dir / "state.json"
            if not state_file.exists():
                continue
            
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 检查目标是否匹配
                state = data.get("state", {})
                problem_spec = state.get("problem_spec", {})
                stored_goal = problem_spec.get("goal", "")
                
                # 简单的模糊匹配 (去除空白后比较)
                if _normalize_goal(stored_goal) == _normalize_goal(goal):
                    candidates.append(data)
            except:
                continue
        
        if not candidates:
            return None
        
        # 返回最新的检查点
        candidates.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return candidates[0]
        
    except Exception as e:
        logger.error(f"查找检查点失败: {e}")
        return None


def _normalize_goal(goal: str) -> str:
    """规范化目标文本用于比较"""
    import re
    text = "".join(goal.lower().split())
    text = re.sub(r'[?!.,。？！，]', '', text)
    return text


def list_checkpoints() -> List[Dict[str, Any]]:
    """
    列出所有检查点
    
    Returns:
        检查点摘要列表
    """
    results = []
    
    try:
        if not CHECKPOINT_DIR.exists():
            return results
        
        for cp_dir in CHECKPOINT_DIR.iterdir():
            if not cp_dir.is_dir():
                continue
            
            state_file = cp_dir / "state.json"
            if not state_file.exists():
                continue
            
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                results.append({
                    "job_id": data.get("job_id"),
                    "phase": data.get("phase"),
                    "timestamp": data.get("timestamp"),
                    "goal": data.get("state", {}).get("problem_spec", {}).get("goal", "")[:50]
                })
            except:
                continue
        
        # 按时间排序
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
    except Exception as e:
        logger.error(f"列出检查点失败: {e}")
    
    return results
