"""
Reporting Commands

/report, /analyze
"""
import json
from pathlib import Path
from apps.telegram_bot.command_registry import CommandRegistry

def register_reporting_commands(registry: CommandRegistry):

    @registry.register(
        command="/report",
        description="获取报告文件",
        usage="/report <run_id|current>",
        examples=["/report current"],
        group="Reporting"
    )
    def cmd_report(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        db = ctx["db"]
        
        args = payload["args"]
        run_id = args[0] if args else "current"
        
        if run_id == "current":
            run_id = db.kv_get(f"last_job_{chat_id}")
            
        if not run_id:
            tg.send_message(chat_id, "❌ 无指定任务")
            return
            
        # Path: runs/<run_id>/report.md
        # [P59] Support unified PROJECTS_DIR first, then legacy paths
        from config.settings import settings
        
        search_paths = [
            settings.PROJECTS_DIR / run_id,      # New standard
            settings.REPORTS_DIR / run_id,       # Legacy 1
            Path(f"runs/{run_id}")               # Legacy 2
        ]
        
        run_dir = None
        for p in search_paths:
            if p.exists() and p.is_dir():
                run_dir = p
                break
        
        if not run_dir:
            tg.send_message(chat_id, f"❌ 找不到运行目录: {run_id}")
            return

        # Find newest .md file
        md_files = list(run_dir.glob("*.md"))
        # Sort by mtime desc
        md_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        md_file = md_files[0] if md_files else (run_dir / "report.md") # Fallback
        
        json_file = run_dir / "report.json"
            
        sent = False
        if md_file.exists():
            tg.send_document(chat_id, md_file, caption=f"📄 Report MD ({run_id})")
            sent = True
        
        if json_file.exists():
            tg.send_document(chat_id, json_file, caption=f"📊 Report JSON ({run_id})")
            sent = True
            
        if not sent:
            tg.send_message(chat_id, "⚠️ 报告文件尚未生成")

    @registry.register(
        command="/analyze",
        description="分析报告摘要",
        usage="/analyze <run_id|current>",
        examples=["/analyze current"],
        group="Reporting"
    )
    def cmd_analyze(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        db = ctx["db"]
        
        args = payload["args"]
        run_id = args[0] if args else "current"
        
        if run_id == "current":
            run_id = db.kv_get(f"last_job_{chat_id}")
            
        # [P101] Fix path resolution to support PROJECTS_DIR
        from config.settings import settings
        
        search_paths = [
            settings.PROJECTS_DIR / run_id,      # New standard
            settings.REPORTS_DIR / run_id,       # Legacy 1
            Path(f"runs/{run_id}")               # Legacy 2
        ]
        
        run_dir = None
        for p in search_paths:
            if p.exists() and p.is_dir():
                run_dir = p
                break
                
        if not run_dir:
            tg.send_message(chat_id, f"❌ 找不到运行目录: {run_id}")
            return
            
        json_file = run_dir / "report.json"
        
        if not json_file.exists():
            tg.send_message(chat_id, f"❌ 找不到报告 JSON: {run_id}")
            return
            
        try:
            data = json.loads(json_file.read_text("utf-8"))
            # Basic analysis
            hypotheses = data.get("hypotheses_and_evidence", [])
            gap = data.get("gap_analysis", {})
            recs = data.get("recommendations", [])
            
            summary = (
                f"🧐 **分析摘要 ({run_id})**\n\n"
                f"🔖 假设数量: {len(hypotheses)}\n"
                f"🚧 证据缺口: {len(gap.get('critical_missing_evidence', []))}\n"
                f"💡 建议条目: {len(recs)}\n\n"
                f"**首要建议**:\n" + 
                ("\n".join([f"- {r['action']}" for r in recs[:3]]) if recs else "无")
            )
            tg.send_message(chat_id, summary, parse_mode="Markdown")
        except Exception as e:
            tg.send_message(chat_id, f"❌ 分析失败: {e}")

