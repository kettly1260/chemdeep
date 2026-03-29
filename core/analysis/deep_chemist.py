"""
Deep Chemist Module (P25)
First-principles chemical analysis engine.
"""
import logging
from typing import Optional, Dict, Any, List

from core.ai.base import create_ai_engine
from core.analysis.prompts import build_deep_analysis_prompt, PROMPT_CITATION_RULES
from core.reporting.context_manager import ContextManager

logger = logging.getLogger('deep_research')


class DeepChemist:
    """
    Deep Chemical Analysis Engine.
    
    Transforms from "Literature Summarization" to "First-Principles Analysis".
    Uses structure-property reasoning with supporting literature evidence.
    """
    
    def __init__(self, ai_engine=None):
        self.ai = ai_engine or create_ai_engine()
        self.context_manager = ContextManager()
    
    def analyze(
        self,
        molecule: str,
        goal: str,
        papers: List[Dict[str, Any]] = None,
        target_analyte: str = ""
    ) -> str:
        """
        Perform deep chemical analysis.
        
        Args:
            molecule: Target molecule name/structure
            goal: Research goal/question
            papers: List of paper dicts from search
            target_analyte: Specific analyte (e.g., "Fe3+")
        
        Returns:
            Markdown report with inline citations
        """
        logger.info(f"🔬 Starting deep chemical analysis: {molecule[:50]}...")
        
        # Step 1: Index literature sources (P26)
        if papers:
            added = self.context_manager.add_sources_from_papers(papers)
            logger.info(f"📚 Indexed {added} unique sources for citation")
        
        # Step 2: Build context string with citation rules
        literature_context = self.context_manager.get_context_string(max_sources=15)
        
        # Step 3: Build deep analysis prompt (P25)
        prompt = build_deep_analysis_prompt(
            molecule=molecule,
            goal=goal,
            target_analyte=target_analyte,
            literature_context=literature_context
        )
        
        # Step 4: Add system-level citation enforcement
        system_prompt = f"""You are a Deep Chemical Reasoning Engine.
{PROMPT_CITATION_RULES}

Respond ONLY in Chinese (简体中文) for the main content.
Section headers may remain in English for clarity."""
        
        # Step 5: Call AI for analysis
        logger.info("🤖 Generating deep analysis...")
        
        try:
            response = self.ai.chat(
                message=prompt,
                system_prompt=system_prompt
            )
            
            report = response.get("content", "") if isinstance(response, dict) else str(response)
            
            # Step 6: Append auto-generated references if not present
            if "## References" not in report and "## 参考文献" not in report:
                report += "\n\n" + self.context_manager.get_references()
            
            logger.info("✅ Deep analysis complete")
            return report
            
        except Exception as e:
            logger.error(f"Deep analysis failed: {e}")
            return f"**分析失败**: {str(e)}"
    
    def get_source_count(self) -> int:
        """Return number of indexed sources."""
        return self.context_manager.get_source_count()


def run_deep_analysis(
    goal: str,
    papers: List[Dict[str, Any]] = None,
    target_analyte: str = ""
) -> str:
    """
    Convenience function for running deep analysis.
    Extracts molecule from goal automatically.
    """
    # Simple molecule extraction (can be enhanced)
    molecule = goal  # Use full goal as molecule description
    
    chemist = DeepChemist()
    return chemist.analyze(
        molecule=molecule,
        goal=goal,
        papers=papers,
        target_analyte=target_analyte
    )
