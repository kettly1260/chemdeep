"""
/help 命令处理器
"""

import logging
from core.ai import MODEL_STATE

logger = logging.getLogger("main")


def handle_help(chat_id: int, tg) -> None:
    """处理 /help 命令"""
    help_text = (
        f"🔬 Deep Research Bot\n\n"
        f"📋 命令列表:\n\n"
        f"【深度研究】\n"
        f"/deepresearch <问题> - AI 深度研究\n"
        f"/dr <问题> - 同上（简写）\n"
        f"  可选参数:\n"
        f"    --year5  只看近5年文献\n"
        f"    --year10 只看近10年文献\n"
        f"    --year 2020 只看2020年及以后\n"
        f"    --score 5 只看评分≥5分的文献\n\n"
        f"【搜索】\n"
        f"/search <关键词> - 多源搜索\n"
        f"/scholar <关键词> - Google Scholar\n"
        f"/wos <检索式> - WoS 搜索\n\n"
        f"【AI 模型】\n"
        f"/models - 查看全部可用模型\n"
        f"/currentmodel - 查看模型配置\n"
        f"/setmodel <model> - 切换模型\n\n"
        f"【论文分析】\n"
        f"/analyze [job_id] [cloud] - 分析\n"
        f"/report [job_id] - 生成报告\n\n"
        f"【任务管理】\n"
        f"/autorun - 自动抓取论文\n"
        f"/status - 查看任务状态\n"
        f"/stop - 终止任务\n\n"
        f"【浏览器】\n"
        f"/startedge - 启动真实 Edge\n\n"
        f"⚙️ 模型: {MODEL_STATE.openai_model}"
    )
    tg.send_message(chat_id, help_text)
