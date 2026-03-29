"""
Iterative Research Flow Command Handler
"""
import threading
from core.services.research import DeepResearcher

def handle_research_flow(chat_id: int, text: str, tg, db) -> None:
    """处理 /research_flow 命令"""
    
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        tg.send_message(chat_id, "用法: /research_flow <研究目标>\n示例: /research_flow 提高锂金属电池库伦效率")
        return
    
    goal = parts[1].strip()
    tg.send_message(chat_id, f"🔄 启动迭代式研究工作流...\n目标: {goal}")
    
    def run_flow():
        try:
            researcher = DeepResearcher(notify_callback=lambda x: tg.send_message(chat_id, x))
            result = researcher.run_iterative_research(goal, max_iterations=3)
            
            report_path = result.get("report_path")
            tg.send_message(chat_id, f"✅ 工作流完成!\n报告已生成: {report_path}")
            
            # Send the report content excerpt
            report_text = result.get("result", {}).get("synthesis_text", "")
            if len(report_text) > 4000:
                report_text = report_text[:4000] + "\n...(too long to display full)"
            tg.send_message(chat_id, report_text)
            
        except Exception as e:
            tg.send_message(chat_id, f"❌ 工作流出错: {e}")
            
    threading.Thread(target=run_flow, daemon=True).start()
