"""
论文分析模块 - 使用预处理模型提取信息，云端 LLM 生成报告
支持：本地模型（Ollama/LM Studio）或便宜的云端模型进行预处理
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable
from dataclasses import dataclass
from config.settings import settings

logger = logging.getLogger('analyzer')


@dataclass
class AnalysisResult:
    """分析结果"""
    success: bool
    paper_id: int
    doi: str
    data: dict | None = None
    error: str | None = None


class PreprocessLLMClient:
    """预处理 LLM 客户端（可以是本地 Ollama/LM Studio 或便宜的云端模型）"""
    
    def __init__(self, 
                 api_base: str = None, 
                 model: str = None, 
                 api_key: str = None,
                 notify_callback: Callable[[str], None] | None = None):
        self.api_base = api_base or settings.LOCAL_LLM_API_BASE
        self.model = model or settings.LOCAL_LLM_MODEL
        self.api_key = api_key or settings.LOCAL_LLM_API_KEY
        self.notify = notify_callback or (lambda x: logger.info(x))
        self._client = None
        
        self._init_client()
    
    def _init_client(self):
        """初始化 OpenAI 兼容客户端"""
        try:
            import openai
            self._client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
                timeout=180  # 预处理可能较慢
            )
            logger.info(f"预处理 LLM 客户端初始化成功: {self.api_base}")
        except Exception as e:
            logger.error(f"预处理 LLM 客户端初始化失败: {e}")
    
    def set_model(self, model: str):
        """设置模型"""
        self.model = model
        logger.info(f"预处理模型已设置为: {model}")
    
    def set_api_base(self, api_base: str):
        """设置 API 地址"""
        self.api_base = api_base
        self._init_client()
        logger.info(f"预处理 LLM API 已设置为: {api_base}")
    
    def set_api_key(self, api_key: str):
        """设置 API Key"""
        self.api_key = api_key
        self._init_client()
        logger.info("预处理 LLM API Key 已更新")
    
    def list_models(self) -> list[str]:
        """列出可用模型"""
        if not self._client:
            return []
        try:
            models = self._client.models.list()
            return [m.id for m in models.data]
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []
    
    def call(self, prompt: str, system_prompt: str = None, json_mode: bool = False) -> str | None:
        """调用 LLM"""
        if not self._client:
            logger.error("预处理 LLM 客户端未初始化")
            return None
        
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.3,
            }
            
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            
            response = self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"预处理 LLM 调用失败: {e}")
            return None


class PaperAnalyzer:
    """论文分析器"""
    
    def __init__(self, 
                 preprocess_llm: PreprocessLLMClient = None,
                 notify_callback: Callable[[str], None] | None = None):
        self.preprocess_llm = preprocess_llm
        self.notify = notify_callback or (lambda x: logger.info(x))
    
    def _get_extraction_prompt(self, goal: str, html_content: str) -> tuple[str, str]:
        """根据目标生成提取提示词"""
        
        # 截断内容避免超出 token 限制
        max_chars = 15000
        if len(html_content) > max_chars:
            html_content = html_content[:max_chars] + "\n...[内容已截断]..."
        
        if goal == "synthesis":
            system_prompt = """你是一个化学论文分析助手。你的任务是从论文中提取合成相关信息。
请用中文回答，以 JSON 格式输出。"""
            
            user_prompt = f"""请从以下论文内容中提取合成相关信息：

{html_content}

请提取以下信息（JSON格式）：
{{
    "compound_name": "化合物名称或代号",
    "synthesis_method": "合成方法概述（50字以内）",
    "reagents": ["主要试剂列表"],
    "conditions": {{
        "temperature": "反应温度",
        "time": "反应时间",
        "solvent": "溶剂"
    }},
    "yield": "产率",
    "characterization": ["表征方法列表，如NMR, MS等"],
    "key_steps": ["关键合成步骤，每步一句话"],
    "summary": "合成方法总结（100字以内）"
}}

如果某项信息未提及，填写 null。"""

        elif goal == "performance":
            system_prompt = """你是一个化学论文分析助手。你的任务是从论文中提取性能相关信息。
请用中文回答，以 JSON 格式输出。"""
            
            user_prompt = f"""请从以下论文内容中提取荧光性能相关信息：

{html_content}

请提取以下信息（JSON格式）：
{{
    "compound_name": "化合物名称或代号",
    "target_analyte": "检测目标物",
    "fluorescence": {{
        "excitation_wavelength": "激发波长 (nm)",
        "emission_wavelength": "发射波长 (nm)",
        "quantum_yield": "量子产率",
        "stokes_shift": "斯托克斯位移"
    }},
    "sensing_performance": {{
        "detection_limit": "检测限",
        "linear_range": "线性范围",
        "response_time": "响应时间",
        "selectivity": "选择性说明"
    }},
    "application": "应用场景",
    "advantages": ["主要优点"],
    "summary": "性能总结（100字以内）"
}}

如果某项信息未提及，填写 null。"""

        else:
            # 通用提取
            system_prompt = """你是一个化学论文分析助手。请用中文回答，以 JSON 格式输出。"""
            
            user_prompt = f"""请从以下论文内容中提取关键信息：

{html_content}

请提取以下信息（JSON格式）：
{{
    "title": "论文标题",
    "abstract": "摘要内容（200字以内）",
    "keywords": ["关键词列表"],
    "main_findings": ["主要发现，每条一句话"],
    "methods": ["使用的方法"],
    "conclusions": "结论（100字以内）"
}}

如果某项信息未提及，填写 null。"""
        
        return system_prompt, user_prompt
    
    def analyze_paper(self, paper_id: int, doi: str, html_path: Path, goal: str = "synthesis",
                      use_cloud: bool = False) -> AnalysisResult:
        """分析单篇论文
        
        Args:
            use_cloud: 如果为 True，直接使用云端模型分析（跳过预处理模型）
        """
        
        if not html_path.exists():
            return AnalysisResult(
                success=False,
                paper_id=paper_id,
                doi=doi,
                error=f"文件不存在: {html_path}"
            )
        
        try:
            # 读取 HTML 内容
            html_content = html_path.read_text(encoding='utf-8', errors='ignore')
            
            # 尝试读取 clean markdown 如果存在
            md_path = html_path.with_suffix('.md')
            if md_path.exists():
                html_content = md_path.read_text(encoding='utf-8', errors='ignore')
            
            # 获取提示词
            system_prompt, user_prompt = self._get_extraction_prompt(goal, html_content)
            
            # 选择使用预处理模型还是云端模型
            if use_cloud or not self.preprocess_llm:
                # 直接使用云端模型
                from core.ai import AIClient
                cloud_ai = AIClient()
                full_prompt = f"{system_prompt}\n\n{user_prompt}"
                response_obj = cloud_ai.call(full_prompt, json_mode=True)
                
                if not response_obj.success:
                    return AnalysisResult(
                        success=False,
                        paper_id=paper_id,
                        doi=doi,
                        error=f"云端模型调用失败: {response_obj.error}"
                    )
                response = response_obj.raw_response
            else:
                # 使用预处理模型
                response = self.preprocess_llm.call(user_prompt, system_prompt, json_mode=True)
            
            if not response:
                return AnalysisResult(
                    success=False,
                    paper_id=paper_id,
                    doi=doi,
                    error="LLM 调用失败"
                )
            
            # 解析 JSON
            try:
                data = json.loads(response)
            except json.JSONDecodeError:
                # 尝试提取 JSON
                import re
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    data = {"raw_response": response}
            
            return AnalysisResult(
                success=True,
                paper_id=paper_id,
                doi=doi,
                data=data
            )
            
        except Exception as e:
            logger.error(f"分析论文失败 {doi}: {e}")
            return AnalysisResult(
                success=False,
                paper_id=paper_id,
                doi=doi,
                error=str(e)
            )
    
    def batch_analyze(self, papers: list[dict], library_dir: Path, goal: str = "synthesis",
                      use_cloud: bool = False,
                      progress_callback: Callable[[int, int], None] | None = None) -> list[AnalysisResult]:
        """批量分析论文
        
        Args:
            use_cloud: 如果为 True，直接使用云端模型分析
        """
        results = []
        total = len(papers)
        
        for i, paper in enumerate(papers, 1):
            paper_id = paper.get("id")
            doi = paper.get("doi", "")
            html_path_str = paper.get("raw_html_path")
            
            if not html_path_str:
                results.append(AnalysisResult(
                    success=False,
                    paper_id=paper_id,
                    doi=doi,
                    error="无 HTML 文件路径"
                ))
                continue
            
            html_path = Path(html_path_str)
            
            # 智能处理路径：
            # 1. 如果文件直接存在，使用它
            # 2. 如果路径已经包含 data/library 前缀，不再拼接
            # 3. 否则尝试拼接 library_dir
            if not html_path.exists():
                # 检查路径是否已经包含 library 目录
                path_str = str(html_path)
                if "data\\library\\" in path_str or "data/library/" in path_str:
                    # 路径已经包含 library_dir，直接使用相对于项目根目录的路径
                    pass
                elif not html_path.is_absolute():
                    # 尝试拼接
                    candidate = library_dir / html_path
                    if candidate.exists():
                        html_path = candidate
            
            logger.info(f"[{i}/{total}] 分析: {doi}")
            result = self.analyze_paper(paper_id, doi, html_path, goal, use_cloud=use_cloud)
            results.append(result)
            
            if progress_callback:
                progress_callback(i, total)
        
        return results
    
    def generate_report(self, analysis_results: list[AnalysisResult], goal: str, 
                        cloud_ai = None) -> str:
        """使用云端 AI 生成综合报告"""
        
        if not cloud_ai:
            from core.ai import AIClient
            cloud_ai = AIClient()
        
        # 准备分析数据
        successful_analyses = [r for r in analysis_results if r.success]
        
        if not successful_analyses:
            return "❌ 没有成功分析的论文，无法生成报告"
        
        # 构建报告数据
        papers_data = []
        for r in successful_analyses:
            papers_data.append({
                "doi": r.doi,
                "analysis": r.data
            })
        
        # 生成报告提示词
        if goal == "synthesis":
            prompt = f"""请基于以下 {len(papers_data)} 篇论文的分析结果，生成一份综合研究报告。

分析数据：
{json.dumps(papers_data, ensure_ascii=False, indent=2)}

请生成报告，包含以下内容：
1. **合成方法总览**：各论文使用的主要合成方法对比
2. **试剂和条件**：常用试剂、反应条件的共性和差异
3. **产率比较**：各方法的产率对比
4. **关键发现**：最值得关注的合成技术或创新点
5. **建议**：基于这些研究，对后续合成工作的建议

请用中文撰写，使用 Markdown 格式。"""

        elif goal == "performance":
            prompt = f"""请基于以下 {len(papers_data)} 篇论文的分析结果，生成一份综合研究报告。

分析数据：
{json.dumps(papers_data, ensure_ascii=False, indent=2)}

请生成报告，包含以下内容：
1. **检测目标**：各探针的检测目标物对比
2. **荧光性能**：发射波长、量子产率等性能对比表格
3. **检测性能**：检测限、线性范围等的对比
4. **应用领域**：各探针的实际应用或潜在应用
5. **发展趋势**：基于这些研究看到的研究趋势
6. **建议**：对后续研究的建议

请用中文撰写，使用 Markdown 格式。"""
        else:
            prompt = f"""请基于以下 {len(papers_data)} 篇论文的分析结果，生成一份综合研究报告。

分析数据：
{json.dumps(papers_data, ensure_ascii=False, indent=2)}

请生成综合报告，总结主要发现、方法、结论，并提出见解。
请用中文撰写，使用 Markdown 格式。"""
        
        # 调用云端 AI
        response = cloud_ai.call(prompt, json_mode=False)
        
        if response.success and response.raw_response:
            return response.raw_response
        else:
            return f"❌ 报告生成失败: {response.error}"


# 全局预处理 LLM 状态
class PreprocessLLMState:
    """预处理 LLM 状态管理（单例）"""
    _instance = None
    _lock = __import__('threading').Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.api_base = settings.LOCAL_LLM_API_BASE
                    cls._instance.model = settings.LOCAL_LLM_MODEL
                    cls._instance.api_key = settings.LOCAL_LLM_API_KEY
        return cls._instance
    
    def set_model(self, model: str):
        self.model = model
    
    def set_api_base(self, api_base: str):
        self.api_base = api_base
    
    def set_api_key(self, api_key: str):
        self.api_key = api_key


PREPROCESS_LLM_STATE = PreprocessLLMState()

# 兼容旧名称
LocalLLMClient = PreprocessLLMClient
LocalLLMState = PreprocessLLMState
LOCAL_LLM_STATE = PREPROCESS_LLM_STATE