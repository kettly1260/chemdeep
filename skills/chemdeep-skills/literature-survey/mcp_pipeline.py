"""
文献调研-机理假设-证据提取-评估-方法归并-验证设计的MCP自动流程
"""
from core.mcp_client import MCPClient
import os

# MCP Server配置（可根据实际环境调整）
MCP_COMMAND = os.environ.get("CHEMDEEP_MCP_COMMAND", "python")
MCP_ARGS = os.environ.get("CHEMDEEP_MCP_ARGS", "mcp_server/server.py").split()
MCP_ENV = os.environ.copy()
MCP_CWD = os.environ.get("CHEMDEEP_MCP_CWD", None)

class ChemDeepPipeline:
    def __init__(self):
        self.client = MCPClient(MCP_COMMAND, MCP_ARGS, env=MCP_ENV, cwd=MCP_CWD)

    def run_full_pipeline(self, query, language='zh', field='chemistry', min_year=None, max_results=20, min_score=5):
        # 1. search_papers
        papers = self.client.call_tool("search_papers", {
            "query": query,
            "max_results": max_results,
            **({"min_year": min_year} if min_year else {})
        })
        # 2. score_papers
        scored = self.client.call_tool("score_papers", {
            "papers": papers,
            "min_score": min_score
        })
        # 3. formalize_research_goal
        problem_spec = self.client.call_tool("formalize_research_goal", {
            "goal": query
        })
        # 4. generate_hypotheses
        hypotheses = self.client.call_tool("generate_hypotheses", {
            "problem_spec": problem_spec,
            "abstracts": [p.get("abstract", "") for p in scored]
        })
        # 5. extract_evidence
        evidence = self.client.call_tool("extract_evidence", {
            "papers": scored,
            "problem_spec": problem_spec
        })
        # 6. evaluate_hypotheses
        eval_result = self.client.call_tool("evaluate_hypotheses", {
            "hypotheses": hypotheses,
            "evidence": evidence
        })
        # 7. cluster_methods
        method_clusters = self.client.call_tool("cluster_methods", {
            "evidence": evidence
        })
        # 8. design_verification_plan
        verification_plan = self.client.call_tool("design_verification_plan", {
            "goal": query,
            "hypotheses": hypotheses,
            "evidence": evidence,
            "method_clusters": method_clusters
        })
        return {
            "papers": papers,
            "scored": scored,
            "problem_spec": problem_spec,
            "hypotheses": hypotheses,
            "evidence": evidence,
            "eval_result": eval_result,
            "method_clusters": method_clusters,
            "verification_plan": verification_plan
        }
