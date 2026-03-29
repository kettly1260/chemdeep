"""
Research Tree Recorder [P62]
Records the decision tree and progress of the iterative research.
Saves to data/projects/{job_id}/research_tree.json
"""
import logging
import json
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from config.settings import settings

logger = logging.getLogger('deep_research')

@dataclass
class ResearchNode:
    node_id: str
    parent_id: Optional[str]
    type: str  # "root", "iteration_start", "query_execution", "evaluation", "learnings"
    depth: int
    iteration: int
    created_at: float = field(default_factory=time.time)
    
    # Optional content fields
    content: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    # Status
    status: str = "completed"

class ResearchTreeRecorder:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.project_dir = settings.PROJECTS_DIR / job_id
        self.tree_file = self.project_dir / "research_tree.json"
        
        self.nodes: List[ResearchNode] = []
        self._ensure_dir()
        
    def _ensure_dir(self):
        self.project_dir.mkdir(parents=True, exist_ok=True)
        
    def add_node(self, node: ResearchNode):
        self.nodes.append(node)
        self.save()
        
    def save(self):
        try:
            data = [asdict(n) for n in self.nodes]
            with open(self.tree_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Save research tree failed: {e}")

    def load(self):
        if self.tree_file.exists():
            try:
                with open(self.tree_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.nodes = [ResearchNode(**d) for d in data]
            except Exception as e:
                logger.error(f"Load research tree failed: {e}")

    # Helper methods for common events
    
    def record_root(self, goal: str):
        self.add_node(ResearchNode(
            node_id="root",
            parent_id=None,
            type="root",
            depth=0,
            iteration=0,
            content=f"Initial Goal: {goal}"
        ))
        
    def record_iteration_start(self, iteration: int):
        self.add_node(ResearchNode(
            node_id=f"iter_{iteration}",
            parent_id="root",
            type="iteration_start",
            depth=1,
            iteration=iteration,
            content=f"Iteration {iteration} Started"
        ))
        
    def record_search_execution(self, iteration: int, stats: List[Dict]):
        # Parent is current iteration
        parent_id = f"iter_{iteration}"
        
        for i, s in enumerate(stats):
            node_id = f"query_{iteration}_{i}"
            self.add_node(ResearchNode(
                node_id=node_id,
                parent_id=parent_id,
                type="query_execution",
                depth=2,
                iteration=iteration,
                content=f"Query: {s.get('query')}",
                metadata=s
            ))

    def record_evaluation(self, iteration: int, is_sufficient: bool, reason: str):
        self.add_node(ResearchNode(
            node_id=f"eval_{iteration}",
            parent_id=f"iter_{iteration}",
            type="evaluation",
            depth=2,
            iteration=iteration,
            content=f"Sufficient: {is_sufficient}",
            metadata={"reason": reason}
        ))
        
    def record_learnings(self, iteration: int, new_learnings: List[str]):
        if not new_learnings:
            return
        self.add_node(ResearchNode(
            node_id=f"learn_{iteration}",
            parent_id=f"iter_{iteration}",
            type="learnings",
            depth=2,
            iteration=iteration,
            content=f"Added {len(new_learnings)} learnings",
            metadata={"items": new_learnings}
        ))
