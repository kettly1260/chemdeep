"""
Run Research Command Handler
Triggers the iterative research flow
"""
import logging
from core.services.research.iterative_main import run_iterative_research
from core.services.research.core_types import IterativeResearchState

logger = logging.getLogger('main')

def handle_run_research(chat_id: int, args: str, tg, db) -> None:
    """处理 /researchflow 命令"""
    if not args:
        tg.send_message(chat_id, "⚠️ 请提供研究问题。\n例如: `/researchflow 荧光探针的设计原则`")
        return
        
    question = args.strip()
    tg.send_message(chat_id, f"🚀 正在启动迭代式深度研究...\n❓ 问题: {question}\n\n⏳ 这可能需要几分钟，请耐心等待...")
    
    try:
        from core.commands.stop import is_cancelled, clear_cancel_flag
        
        # 清除之前的取消标志
        clear_cancel_flag(chat_id)
        
        # Run iterative research flow
        state: IterativeResearchState = run_iterative_research(
            question, 
            max_iterations=3,
            cancel_callback=lambda: is_cancelled(chat_id)
        )
        
        # Check if cancelled (state returned early)
        if is_cancelled(chat_id):
             tg.send_message(chat_id, "🛑 研究任务已终止。")
             return
        
        # Report results
        if state.final_report:
            report = state.final_report
            
            # 1. 智能分段 (按段落切分，每段 < 3000 字符以留出 HTML 标签空间)
            chunks = _smart_split(report, max_chars=3000)
            
            tg.send_message(chat_id, "✅ 研究完成! 以下是详细报告:")
            
            for chunk in chunks:
                # 2. 转换为 Telegram HTML
                html_chunk = _convert_md_to_html(chunk)
                # 3. 发送 (指定 parse_mode="HTML")
                tg.send_message(chat_id, html_chunk, parse_mode="HTML")
                
        else:
             tg.send_message(chat_id, "⚠️ 研究完成，但未生成最终报告。")
             
    except Exception as e:
        logger.error(f"Research run failed: {e}", exc_info=True)
        tg.send_message(chat_id, f"❌ 研究运行出错: {e}")


def _smart_split(text: str, max_chars: int) -> list[str]:
    """按段落切分文本，确保每段不超过 max_chars"""
    chunks = []
    current_chunk = []
    current_len = 0
    
    # 按行分割，保留空行作为段落分隔
    lines = text.split('\n')
    
    for line in lines:
        line_len = len(line) + 1 # +1 for newline
        
        if current_len + line_len > max_chars:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            
            # 如果单行本身就超过 max_chars (罕见)，强制切分
            if line_len > max_chars:
                # 简单处理：作为单独一块（可能会再次被 splitter 切分，或者由 bot.py 强制切分）
                chunks.append(line)
                continue
        
        current_chunk.append(line)
        current_len += line_len
    
    if current_chunk:
        chunks.append("\n".join(current_chunk))
        
    return chunks


def _convert_md_to_html(text: str) -> str:
    """将 Markdown 转换为 Telegram 支持的 HTML"""
    import re
    
    # 1. 转义 HTML 特殊字符
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # 2. 也是最重要的: 处理 Code Block (避免内部被后续规则替换)
    # 暂时简单处理： Telegram 支持 <pre><code>...</code></pre>
    # 使用占位符保护代码块
    code_blocks = {}
    
    def save_code_block(match):
        key = f"__CODE_BLOCK_{len(code_blocks)}__"
        code_blocks[key] = f"<pre><code>{match.group(1)}</code></pre>"
        return key
        
    text = re.sub(r'```(.*?)```', save_code_block, text, flags=re.DOTALL)
    
    # 3. 处理 Inline Code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # 4. Bold: **text** -> <b>text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    
    # 5. Italic: *text* -> <i>text</i> (Lookbehind/Lookahead ensure not matching **)
    # 简单起见，假设 ** 已经被替换完了
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)
    
    # 6. Headers: ### Title -> <b>Title</b>
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    
    # 7. Unordered List: * Item -> • Item
    text = re.sub(r'^(\s*)[-*]\s+', r'\1• ', text, flags=re.MULTILINE)
    
    # 8. Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    
    # 9. 还原代码块
    for key, val in code_blocks.items():
        text = text.replace(key, val)
        
    return text
