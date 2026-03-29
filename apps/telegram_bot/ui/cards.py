"""
Telegram Bot Cards (Markdown Renderers)
"""
from apps.telegram_bot.services.runtime_config import UserConfig

def render_config_card(cfg: UserConfig) -> str:
    """渲染配置卡片"""
    src = lambda s: "📝 Runtime" if s == "runtime" else "🌍 Env"
    
    return (
        f"🔧 **Configuration**\n\n"
        f"🤖 **Model**: `{cfg.model}`\n"
        f"   └ Source: {src(cfg.model_source)}\n"
        f"🔗 **Base URL**: `{cfg.base_url}`\n"
        f"   └ Source: {src(cfg.base_url_source)}\n"
        f"🔑 **API Key**: `{cfg.masked_key()}`\n"
        f"   └ Source: {src(cfg.key_source)}\n\n"
        f"💡 提示：点击下方按钮进行修改"
    )

def render_run_card(job: dict) -> str:
    """渲染任务卡片 (Compact)"""
    if not job:
        return "❌ Task not found"
        
    status_icon = {
        "pending": "⏳",
        "running": "🏃",
        "completed": "✅",
        "failed": "❌",
        "stopped": "🛑"
    }.get(job.get("status", "unknown"), "❓")
    
    # Calculate duration if possible (depends on job dict fields)
    # job['created_at'] is string usually.
    
    from apps.telegram_bot.ui.utils import escape_markdown
    
    # Safe render of potentially dangerous strings
    goal = escape_markdown(job.get('goal', 'Unknown'))
    status = escape_markdown(job.get('status', 'unknown')).upper()
    
    lines = [
        f"{status_icon} **Task [{job['job_id']}]**",
        f"🎯 {goal}",
        f"📊 **Status**: `{status}`"
    ]
    
    if job.get("message"):
         safe_msg = escape_markdown(job['message'])
         lines.append(f"💬 **Message**: {safe_msg}")
         
    if job.get("error"):
         err = escape_markdown(job['error'])
         if len(err) > 50: err = err[:47] + "..."
         lines.append(f"⚠️ **Error**: `{err}`")
         
    created = escape_markdown(str(job.get('created_at', '?')))
    lines.append(f"⏰ **Created**: {created}")
    lines.append("\n💡 提示：可用按钮刷新/停止/报告/分析")
    
    return "\n".join(lines)
