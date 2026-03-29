"""
Run History Index for Smart Cache & Reuse (P22)
Maintains an index of past research runs to detect duplicates.
"""
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from config.settings import settings

logger = logging.getLogger("run_history")


class RunHistoryIndex:
    """
    Manages an index of past research runs.
    - Path: data/run_history.json
    - Structure: {"goal_hash": [run_metadata, ...]}
    """
    
    INDEX_FILE = settings.BASE_DIR / "data" / "run_history.json"
    
    def __init__(self):
        self._index: Dict[str, List[Dict]] = {}
        self._load()
    
    def _load(self):
        """Load index from disk"""
        if self.INDEX_FILE.exists():
            try:
                with open(self.INDEX_FILE, 'r', encoding='utf-8') as f:
                    self._index = json.load(f)
                logger.debug(f"Loaded run history: {len(self._index)} goal hashes")
            except Exception as e:
                logger.warning(f"Failed to load run history: {e}")
                self._index = {}
        else:
            self._index = {}
    
    def _save(self):
        """Persist index to disk"""
        try:
            self.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.INDEX_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save run history: {e}")
    
    @staticmethod
    def _normalize_goal(goal: str) -> str:
        """Normalize goal text for consistent hashing (ignore punctuation/whitespace)"""
        import re
        # Remove all whitespace
        text = "".join(goal.split()).lower()
        # Keep only alphanumeric and Chinese characters
        # \w matches [a-zA-Z0-9_], plus Chinese range
        # Note: In Python re, \w might include some depending on locale, 
        # but let's be explicit to avoid issues: alphanumeric + Chinese + basic Greek if needed?
        # Actually, simpler is to strip specific punctuation OR keep only valid chars.
        # User goal: "B(9,12)-(芘-5-噻吩-2)2-邻-碳硼烷..."
        # Parentheses and dashes ARE IMPORTANT in chemical names!
        
        # WE SHOULD NOT STRIP DASHES/PARENS inside chemical names.
        # But user might have typed "B(9, 12)" vs "B(9,12)".
        
        # Strategy:
        # 1. Remove all whitespace (handles spaces around punctuation)
        # 2. Convert to lower case
        # 3. Strip trailing punctuation (question marks, periods)
        
        # Remove all whitespace
        text = "".join(goal.lower().split())
        
        # [P47] Aggressive normalization: Remove punctuation globally to ensure robustness
        # Remove: ? ! . , 。 ？ ！ ，
        import re
        text = re.sub(r'[?!.,。？！，]', '', text)
        
        return text
    
    @staticmethod
    def _hash_goal(goal: str) -> str:
        """Generate MD5 hash of normalized goal"""
        normalized = RunHistoryIndex._normalize_goal(goal)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    # [P38] 对外暴露的规范化/哈希方法，供 Bot 与其他模块复用
    @classmethod
    def normalize_goal(cls, goal: str) -> str:
        return cls._normalize_goal(goal)

    # [P38] 对外暴露的目标哈希方法（与历史索引一致）
    @classmethod
    def hash_goal(cls, goal: str) -> str:
        return cls._hash_goal(goal)
    
    def add_run(self, goal: str, run_id: str, status: str, summary_preview: str = "", report_path: str = ""):
        """Add a completed run to the index"""
        goal_hash = self._hash_goal(goal)
        
        run_meta = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "goal": goal,
            "status": status,
            "summary_preview": summary_preview[:200] if summary_preview else "",
            "report_path": report_path
        }
        
        if goal_hash not in self._index:
            self._index[goal_hash] = []
        
        # Prepend (most recent first)
        self._index[goal_hash].insert(0, run_meta)
        
        # Keep only last 5 runs per goal
        self._index[goal_hash] = self._index[goal_hash][:5]
        
        self._save()
        logger.info(f"Added run to history: {run_id} (goal hash: {goal_hash[:8]}...)")
    
    def add_running_task(self, goal: str, run_id: str, original_goal: str = ""):
        """
        [P86] 立即记录开始的任务 (状态为 running)
        用于支持任务恢复
        
        [P93] 新增 original_goal 参数，存储澄清前的原始目标
        """
        goal_hash = self._hash_goal(goal)
        
        # [P93] 同时存储原始目标，便于匹配
        run_meta = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "goal": goal,
            "original_goal": original_goal or goal,  # 如果未提供，使用 goal 本身
            "status": "running",
            "summary_preview": "",
            "report_path": ""
        }
        
        if goal_hash not in self._index:
            self._index[goal_hash] = []
        
        # 检查是否已存在该 run_id
        for existing in self._index[goal_hash]:
            if existing.get("run_id") == run_id:
                # 更新而非重复添加
                existing.update(run_meta)
                self._save()
                return
        
        # Prepend (most recent first)
        self._index[goal_hash].insert(0, run_meta)
        self._index[goal_hash] = self._index[goal_hash][:5]
        
        self._save()
        logger.info(f"Started run recorded: {run_id} (goal hash: {goal_hash[:8]}...)")
    
    def find_match(self, goal: str) -> Optional[Dict]:
        """
        Find the most recent completed run for a given goal.
        Returns None if no match or only failed runs exist.
        """
        goal_hash = self._hash_goal(goal)
        
        # [P52] Strategy 1: Direct Hash Lookup (Fast)
        if goal_hash in self._index:
            runs = self._index[goal_hash]
            for run in runs:
                if run.get("status") in ["COMPLETED", "completed"]:
                    return run

        # [P52] Strategy 2: Legacy Scan (Slow but Robust)
        # Iterate through all keys to handle cases where hash algorithm changed (P47)
        # but the goal text is substantively the same.
        normalized_input = self._normalize_goal(goal)
        
        for stored_hash, runs in self._index.items():
            if stored_hash == goal_hash: continue # Already checked
            
            for run in runs:
                stored_goal = run.get("goal", "")
                if self._normalize_goal(stored_goal) == normalized_input:
                    if run.get("status") in ["COMPLETED", "completed"]:
                        logger.info(f"Found match via legacy scan: {run.get('run_id')} (old hash: {stored_hash})")
                        return run
        
        return None
    
    def find_all_matches(self, goal: str) -> List[Dict]:
        """
        [P22] Find all runs matching the goal (any status).
        [P93] Also checks original_goal field for matches (澄清后目标匹配)
        Returns list sorted by timestamp (most recent first).
        """
        goal_hash = self._hash_goal(goal)
        results = []
        
        # Direct hash lookup
        if goal_hash in self._index:
            results.extend(self._index[goal_hash])
        
        # Legacy scan for hash mismatches + original_goal matching
        normalized_input = self._normalize_goal(goal)
        for stored_hash, runs in self._index.items():
            if stored_hash == goal_hash:
                continue
            for run in runs:
                # Check both goal and original_goal
                stored_goal = run.get("goal", "")
                stored_original = run.get("original_goal", "")
                
                # 1. Check direct goal match
                if self._normalize_goal(stored_goal) == normalized_input:
                    if run not in results:
                        results.append(run)
                
                # 2. Check original_goal match (P93 feature)
                elif stored_original and self._normalize_goal(stored_original) == normalized_input:
                    if run not in results:
                        results.append(run)
                        
                # 3. [P94] Check for backward compatibility with clarification suffixes
                # Existing runs might have stored_goal="Topic (补充要求: ...)" but no original_goal
                else:
                    # Try stripping common suffixes
                    raw_stored = stored_goal
                    if "(补充要求:" in raw_stored or "(Supplementary Requirements:" in raw_stored:
                        # Split by suffix markers
                        parts = raw_stored.split("(补充要求:")
                        if len(parts) > 1:
                            clean_part = parts[0]
                        else:
                            clean_part = raw_stored.split("(Supplementary Requirements:")[0]
                            
                        if self._normalize_goal(clean_part) == normalized_input:
                             if run not in results:
                                results.append(run)
                                logger.info(f"Found match via suffix stripping: {run.get('run_id')}")

        return results
    
    def get_run_metadata(self, run_id: str) -> Optional[Dict]:
        """Get metadata for a specific run ID"""
        for runs in self._index.values():
            for run in runs:
                if run.get("run_id") == run_id:
                    return run
        return None


# Singleton instance
_instance: Optional[RunHistoryIndex] = None

def get_run_history() -> RunHistoryIndex:
    global _instance
    if _instance is None:
        _instance = RunHistoryIndex()
    return _instance
