"""
深度研究命令处理器

处理: /deepresearch, /dr, /confirm
"""
import threading
import json
import time
import logging
from pathlib import Path

logger = logging.getLogger('main')


def handle_deepresearch(chat_id: int, text: str, tg, db) -> None:
    """处理 /deepresearch 或 /dr 命令"""
    from core.services.research import DeepResearcher
    
    # 解析问题
    if text.startswith("/deepresearch"):
        parts = text.split(maxsplit=1)
    else:
        parts = text.split(maxsplit=1)
    
    if len(parts) < 2 or not parts[1].strip():
        tg.send_message(chat_id, 
            "用法: /deepresearch <研究问题>\n\n"
            "示例:\n"
            "/deepresearch 碳硼烷荧光探针的合成方法有哪些?\n"
            "/dr AIE材料在生物成像中的应用"
        )
        return
    
    question = parts[1].strip()
    tg.send_message(chat_id, f"🔬 正在分析问题:\n\n{question}")
    
    def run_deep_research():
        try:
            researcher = DeepResearcher(
                notify_callback=lambda x: tg.send_message(chat_id, x)
            )
            
            # 生成研究计划
            plan = researcher.generate_plan(question)
            
            # 格式化并发送计划
            plan_text = researcher.format_plan(plan)
            tg.send_message(chat_id, plan_text)
            
            # 保存状态供 /confirm 使用
            research_state = {
                "stage": "plan_ready",
                "question": question,
                "plan": plan.to_dict(),
            }
            db.kv_set(f"research_{chat_id}", json.dumps(research_state))
            
            # 创建确认按钮
            inline_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ 确认执行", "callback_data": f"confirm_research:{chat_id}"},
                        {"text": "❌ 取消", "callback_data": "cancel_research"}
                    ]
                ]
            }
            
            tg.send_message(chat_id, 
                "📋 研究计划已生成\n\n"
                "点击「确认执行」开始搜索，或发送 /confirm 继续",
                reply_markup=inline_keyboard
            )
            
        except Exception as e:
            logger.error(f"深度研究失败: {e}", exc_info=True)
            tg.send_message(chat_id, f"❌ 研究失败: {e}")
    
    threading.Thread(target=run_deep_research, daemon=True).start()


def handle_confirm(chat_id: int, tg, db) -> None:
    """处理 /confirm 命令 - 确认执行研究计划"""
    from core.services.research import DeepResearcher, ResearchPlan
    
    # 获取保存的研究状态
    state_json = db.kv_get(f"research_{chat_id}")
    if not state_json:
        tg.send_message(chat_id, "❌ 没有待确认的研究计划\n\n请先使用 /deepresearch 生成计划")
        return
    
    try:
        research_state = json.loads(state_json)
    except Exception as e:
        tg.send_message(chat_id, f"❌ 状态解析失败: {e}")
        return
    
    if research_state.get("stage") != "plan_ready":
        tg.send_message(chat_id, "❌ 当前阶段不需要确认")
        return
    
    tg.send_message(chat_id, "🚀 开始执行研究计划...")
    
    def execute_research():
        try:
            researcher = DeepResearcher(
                notify_callback=lambda x: tg.send_message(chat_id, x)
            )
            
            plan = ResearchPlan.from_dict(research_state["plan"])
            plan.question = research_state["question"]
            
            # 执行搜索
            search_result = researcher.execute_search(plan)
            
            if search_result["count"] == 0:
                tg.send_message(chat_id, "❌ 未找到相关论文")
                return
            
            # 保存结果
            research_id = f"dr_{int(time.time())}"
            papers_file = researcher.save_search_results(research_id, search_result["papers"])
            
            # 创建 inline keyboard
            inline_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "📥 抓取论文", "callback_data": f"run:{papers_file}"},
                        {"text": "📊 生成报告", "callback_data": f"report:{research_id}"}
                    ],
                    [
                        {"text": "📋 查看论文列表", "callback_data": f"list:{papers_file}"}
                    ]
                ]
            }
            
            tg.send_message(chat_id, 
                f"✅ 搜索完成!\n\n"
                f"📊 找到 {search_result['count']} 篇论文\n"
                f"📁 来源: {', '.join(search_result['sources_used'])}\n"
                f"💾 已保存: {papers_file}\n\n"
                f"点击下方按钮继续操作:",
                reply_markup=inline_keyboard
            )
            
            # 更新状态
            research_state["stage"] = "done"
            research_state["papers_file"] = str(papers_file)
            research_state["research_id"] = research_id
            db.kv_set(f"research_{chat_id}", json.dumps(research_state))
            
        except Exception as e:
            logger.error(f"执行研究失败: {e}", exc_info=True)
            tg.send_message(chat_id, f"❌ 执行失败: {e}")
    
    threading.Thread(target=execute_research, daemon=True).start()
