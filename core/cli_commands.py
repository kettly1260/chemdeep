"""
CLI 命令模块

包含所有命令行接口命令
"""
import typer
from pathlib import Path


def register_cli_commands(app: typer.Typer):
    """注册所有 CLI 命令到 Typer 应用"""
    
    @app.command("search")
    def cli_search(
        query: str,
        sources: str = typer.Option("openalex,crossref", help="数据源，逗号分隔"),
        max_results: int = typer.Option(50, help="最大结果数")
    ):
        """命令行搜索"""
        from core.scholar_search import UnifiedSearcher
        
        typer.echo(f"搜索: {query}")
        typer.echo(f"数据源: {sources}")
        
        searcher = UnifiedSearcher(notify_callback=lambda x: typer.echo(x))
        result = searcher.search(query, sources=sources.split(","), max_results=max_results)
        
        if result["success"]:
            typer.echo(f"\n找到 {result['count']} 篇论文")
            for i, p in enumerate(result["papers"][:10], 1):
                typer.echo(f"{i}. {p.get('title', '无标题')[:60]}")
                typer.echo(f"   DOI: {p.get('doi', '无')}")
        else:
            typer.echo(f"搜索失败: {result.get('errors')}")

    @app.command("models")
    def list_models(show_all: bool = typer.Option(False, "--all", help="显示全部模型")):
        """列出可用的 AI 模型"""
        from core.ai import AIClient
        
        typer.echo("正在获取模型列表...")
        ai = AIClient(notify_callback=lambda x: typer.echo(x))
        result = ai.list_models(show_all=show_all)
        typer.echo(result)

    @app.command("test-ai")
    def test_ai(
        prompt: str = typer.Option("你好，请用一句话介绍自己", help="测试 prompt"),
        model: str = typer.Option(None, help="指定模型")
    ):
        """测试 AI 连接"""
        from core.ai import AIClient, MODEL_STATE
        
        ai = AIClient(notify_callback=lambda x: typer.echo(x))
        
        if model:
            MODEL_STATE.set_openai_model(model)
            typer.echo(f"使用模型: {model}")
        else:
            typer.echo(f"使用模型: {MODEL_STATE.openai_model}")
        
        typer.echo(f"Prompt: {prompt}")
        typer.echo("正在调用 AI...")
        
        result = ai.call(prompt, json_mode=False)
        
        if result.success:
            typer.echo(f"\n✅ 调用成功!")
            typer.echo(f"Provider: {result.provider}")
            typer.echo(f"Model: {result.model}")
            typer.echo(f"Response:\n{result.data.get('text', result.data)}")
        else:
            typer.echo(f"\n❌ 调用失败: {result.error}")

    @app.command("status")
    def show_status(limit: int = 5):
        """显示最近任务状态"""
        from utils.db import DB
        
        db = DB()
        rows = db.list_jobs(limit=limit)
        
        if not rows:
            typer.echo("暂无任务记录")
            return
        
        typer.echo("最近任务:")
        for r in rows:
            typer.echo(f"  {r['job_id']}  {r['status']:9s}  goal={r['goal']:<11s}  msg={r['message'] or ''}")

    @app.command("init")
    def init_config():
        """初始化配置文件"""
        env_template = """# Telegram Bot 配置
CHEMDEEP_TELEGRAM_TOKEN=your_bot_token_here
CHEMDEEP_TELEGRAM_PROXY=socks5h://127.0.0.1:7890
CHEMDEEP_TELEGRAM_CHAT_ID=your_chat_id
CHEMDEEP_TELEGRAM_ALLOWED_CHAT_IDS=your_chat_id

# AI Provider 配置 (openai | gemini | auto)
CHEMDEEP_AI_PROVIDER=openai

# OpenAI 兼容 API
CHEMDEEP_OPENAI_API_KEY=sk-xxx
CHEMDEEP_OPENAI_API_BASE=https://api.openai.com/v1
CHEMDEEP_OPENAI_MODEL=gpt-4-turbo-preview

# Google Gemini
CHEMDEEP_GEMINI_API_KEY=
CHEMDEEP_GEMINI_MODEL=gemini-1.5-pro

# AI 请求行为
CHEMDEEP_AI_TIMEOUT=60
CHEMDEEP_AI_MAX_RETRIES=3

# 路径配置
CHEMDEEP_PROFILE_DIR=profiles/msedge
CHEMDEEP_LIBRARY_DIR=data/library
CHEMDEEP_REPORTS_DIR=data/reports

# 浏览器行为配置
CHEMDEEP_RATE_SECONDS=75
CHEMDEEP_HEADLESS=0
CHEMDEEP_BROWSER_CHANNEL=msedge

# Google Scholar
CHEMDEEP_ENABLE_GOOGLE_SCHOLAR=1
CHEMDEEP_GOOGLE_SCHOLAR_DELAY=5
"""
        env_path = Path("config/.env")
        if env_path.exists():
            typer.echo(f"配置文件已存在: {env_path}")
            overwrite = typer.confirm("是否覆盖?")
            if not overwrite:
                return
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(env_template, encoding="utf-8")
        typer.echo(f"✅ 已创建配置文件: {env_path}")
        typer.echo("请编辑配置文件填入你的 API 密钥和 Telegram 信息")

    @app.command("config")
    def show_config():
        """显示当前配置"""
        from config.settings import settings
        typer.echo(settings.summary())

    @app.command("login")
    def login_browser(url: str = typer.Option("https://www.webofscience.com", help="登录网址")):
        """打开浏览器登录 WoS/Scholar"""
        from core.wos_search import WoSSearcher
        typer.echo(f"正在打开浏览器: {url}")
        typer.echo("请在浏览器中完成登录，完成后关闭窗口")
        searcher = WoSSearcher(notify_callback=lambda x: typer.echo(x))
        searcher.login_interactive()

    @app.command("setmodel")
    def cli_setmodel(model: str):
        """设置 AI 模型"""
        from core.ai import MODEL_STATE
        old = MODEL_STATE.openai_model
        MODEL_STATE.set_openai_model(model)
        typer.echo(f"模型已切换: {old} -> {model}")

    @app.command("currentmodel")
    def cli_currentmodel():
        """显示当前模型"""
        from core.ai import MODEL_STATE
        from config.settings import settings
        typer.echo(f"OpenAI 模型: {MODEL_STATE.openai_model}")
        typer.echo(f"Gemini 模型: {MODEL_STATE.gemini_model}")
        typer.echo(f"API Base: {settings.OPENAI_API_BASE}")
        typer.echo(f"Provider: {settings.AI_PROVIDER}")

    @app.command("research")
    def cli_research(
        query: str,
        max_results: int = typer.Option(20, help="最大文献数量"),
        quick: bool = typer.Option(False, help="快速模式，跳过计划确认")
    ):
        """执行深度研究"""
        from core.services.research.main import DeepResearcher
        
        typer.echo(f"🔬 开始深度研究: {query}")
        typer.echo(f"📊 最大文献数: {max_results}")
        typer.echo(f"⚡ 快速模式: {quick}")
        typer.echo("-" * 50)
        
        researcher = DeepResearcher(notify_callback=lambda x: typer.echo(x))
        
        try:
            # 1. 生成研究计划
            typer.echo("📋 正在生成研究计划...")
            plan = researcher.generate_plan(query)
            
            # 创建兼容的计划对象，包含question属性
            class CompatiblePlan:
                def __init__(self, plan_v2, question):
                    self.question = question
                    # 复制其他属性
                    for attr in dir(plan_v2):
                        if not attr.startswith('_'):
                            setattr(self, attr, getattr(plan_v2, attr))
            
            compatible_plan = CompatiblePlan(plan, query)
            
            if not quick:
                # 显示计划并等待确认
                plan_text = researcher.format_plan(compatible_plan)
                typer.echo("\n" + "="*50)
                typer.echo("📋 研究计划:")
                typer.echo("="*50)
                typer.echo(plan_text)
                typer.echo("="*50)
                
                if not typer.confirm("是否按此计划执行研究?"):
                    typer.echo("❌ 已取消")
                    return
            
            # 2. 执行搜索
            typer.echo("\n🔍 正在执行文献搜索...")
            search_result = researcher.execute_search(compatible_plan, max_per_source=50, top_n=max_results)
            
            papers = search_result.get("papers", [])
            typer.echo(f"\n✅ 搜索完成!")
            typer.echo(f"📚 找到文献: {len(papers)} 篇")
            typer.echo(f"🔗 数据源: {', '.join(search_result.get('sources_used', []))}")
            
            if papers:
                typer.echo("\n📖 文献列表:")
                for i, paper in enumerate(papers[:10], 1):  # 只显示前10篇
                    title = paper.get('title', '无标题')[:60]
                    authors = paper.get('authors', ['未知'])[0] if paper.get('authors') else '未知'
                    year = paper.get('year', '未知')
                    score = paper.get('screening', {}).get('total_score', 'N/A')
                    typer.echo(f"  {i}. [{score}] {title}...")
                    typer.echo(f"     作者: {authors} | 年份: {year}")
                
                if len(papers) > 10:
                    typer.echo(f"  ... 还有 {len(papers) - 10} 篇文献")
            
            # 3. 生成报告 (如果有足够的文献)
            if len(papers) >= 3:
                typer.echo("\n📝 正在生成研究报告...")
                # 这里可以添加报告生成逻辑
                typer.echo("📄 报告生成功能开发中...")
            else:
                typer.echo("\n⚠️ 文献数量不足，无法生成完整报告")
            
            typer.echo("\n🎉 深度研究完成!")
            
        except Exception as e:
            typer.echo(f"❌ 研究失败: {e}")
            import traceback
            typer.echo(traceback.format_exc())
