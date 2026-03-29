"""
停止/中断命令处理器

处理: /stop
"""
import threading
import logging

logger = logging.getLogger('main')

# 全局任务取消标志
_cancel_flags = {}
_cancel_lock = threading.Lock()


def set_cancel_flag(chat_id: int) -> None:
    """设置取消标志"""
    with _cancel_lock:
        _cancel_flags[chat_id] = True
        logger.info(f"设置取消标志: chat_id={chat_id}")


def clear_cancel_flag(chat_id: int) -> None:
    """清除取消标志"""
    with _cancel_lock:
        _cancel_flags[chat_id] = False


def is_cancelled(chat_id: int) -> bool:
    """检查是否已取消"""
    with _cancel_lock:
        return _cancel_flags.get(chat_id, False)


def handle_stop(chat_id: int, tg, db) -> None:
    """处理 /stop 命令 - 终止当前任务"""
    
    # 设置取消标志
    set_cancel_flag(chat_id)
    
    # 检查是否有进行中的研究任务
    research_state = db.kv_get(f"research_{chat_id}")
    if research_state:
        db.kv_delete(f"research_{chat_id}")
        tg.send_message(chat_id, "🛑 已取消深度研究任务")
    
    # 检查运行中的 job
    all_jobs = db.list_jobs(limit=10)
    running_jobs = [j for j in all_jobs if j["status"] == "running"]
    if running_jobs:
        cancelled_count = 0
        for job in running_jobs:
            job_id = job["job_id"]
            if job_id:
                db.update_job_status(job_id, "cancelled", "用户手动取消")
                cancelled_count += 1
        
        if cancelled_count > 0:
            tg.send_message(chat_id, f"🛑 已取消 {cancelled_count} 个运行中的任务")
            return
    
    tg.send_message(chat_id, 
        "✋ 已发送停止信号\n\n"
        "正在运行的任务将在下一个检查点停止。\n"
        "如任务未响应，可能需要重启 Bot。"
    )
