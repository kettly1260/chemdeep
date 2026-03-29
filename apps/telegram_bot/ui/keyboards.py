"""
Telegram Bot Keyboards (Inline)
"""
import math

def build_models_keyboard(models: list, current_model: str, page: int = 1, page_size: int = 8):
    """构建模型分页键盘"""
    # 1. Pagination Logic
    total_models = len(models)
    total_pages = math.ceil(total_models / page_size) if total_models > 0 else 1
    page = max(1, min(page, total_pages))
    
    start = (page - 1) * page_size
    end = start + page_size
    page_items = models[start:end]
    
    keyboard = []
    
    # 2. Model Buttons (2 columns)
    row = []
    for m in page_items:
        # Checkmark for current
        # "✅ <model>" vs "使用 <model>"
        if m == current_model:
            label = f"✅ {m}"
        else:
            label = f"使用 {m}"
            
        if len(label) > 30: label = label[:27] + "..."
            
        row.append({"text": label, "callback_data": f"cmd:/model set {m}"})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    # 3. Navigation Row
    nav_row = []
    if total_pages > 1:
        if page > 1:
            nav_row.append({"text": "⬅️ 上一页", "callback_data": f"cmd:/models page {page-1}"})
        else:
             nav_row.append({"text": " ", "callback_data": "noop"}) # Placeholder
             
        nav_row.append({"text": f"{page}/{total_pages}", "callback_data": "noop"})
        
        if page < total_pages:
            nav_row.append({"text": "➡️ 下一页", "callback_data": f"cmd:/models page {page+1}"})
        else:
             nav_row.append({"text": " ", "callback_data": "noop"})
             
    if nav_row:
        keyboard.append(nav_row)
        
    # 4. Actions Row
    # [Search] [Refresh] [Back]
    actions = [
        {"text": "🔍 搜索模型", "callback_data": "interact:model_search"},
        {"text": "🔄 刷新列表", "callback_data": "cmd:/models refresh"},
        {"text": "🔙 返回配置", "callback_data": "cmd:/config"}
    ]
    keyboard.append(actions)
    
    return {"inline_keyboard": keyboard}

def build_config_keyboard():
    """配置面板键盘"""
    btns = [
        [
            {"text": "🤖 切换模型", "callback_data": "cmd:/models"},
            {"text": "🔑 设置 Key", "callback_data": "interact:key"}
        ],
        [
            {"text": "🔗 设置接口", "callback_data": "interact:endpoint"},
            {"text": "🔄 重置配置", "callback_data": "cmd:/config reset"}
        ],
        [
            {"text": "❓ 帮助菜单", "callback_data": "help:all"}
        ]
    ]
    return {"inline_keyboard": btns}

def build_run_actions_keyboard(run_id: str, status: str, interaction_options: list = None):
    """运行控制键盘"""
    # [Refresh] [Stop] [Report] [Analyze]
    btns = []
    
    # [P71] Interaction Options (Priority)
    if interaction_options:
         # Render interaction buttons first
         # Assuming options are ["Retry", "Switch Model", ...]
         # Callback: interact:sel:<job_id>:<option> (matches logic in execution.py)
         row_opts = []
         for opt in interaction_options:
             row_opts.append({"text": opt, "callback_data": f"interact:sel:{run_id}:{opt}"})
             if len(row_opts) >= 2:
                 btns.append(row_opts)
                 row_opts = []
         if row_opts:
             btns.append(row_opts)
    
    # Status Row
    row1 = [
        {"text": "🔄 刷新状态", "callback_data": f"cmd:/status {run_id}"}
    ]
    if status in ["running", "pending", "waiting_input"]:
        row1.append({"text": "🛑 停止任务", "callback_data": f"cmd:/stop {run_id}"})
    btns.append(row1)
    
    # Actions Row (if valid)
    if status in ["completed", "failed", "stopped"]:
        row2 = [
             {"text": "📄 下载报告", "callback_data": f"cmd:/report {run_id}"},
             {"text": "🧠 分析摘要", "callback_data": f"cmd:/analyze {run_id}"}
        ]
        btns.append(row2)
        
    return {"inline_keyboard": btns}

def build_help_menu(groups: list):
    """帮助菜单"""
    # Grid of groups
    
    # Map common groups to Chinese
    group_map = {
        "Basic": "📌 基础",
        "Config": "⚙️ 配置",
        "Execution": "🚀 任务",
        "Reporting": "📄 报告"
    }
    
    keyboard = []
    row = []
    for g in groups:
        label = group_map.get(g, g)
        row.append({"text": label, "callback_data": f"help:{g}"})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    # All / Back
    keyboard.append([
        {"text": "📚 全部命令", "callback_data": "help:all"}
    ])
    
    return {"inline_keyboard": keyboard}


def build_reuse_options_keyboard(prev_run: dict, goal: str):
    """
    [P22] 任务重用选项键盘
    根据历史任务状态展示不同选项
    """
    status = prev_run.get("status", "").lower()
    run_id = prev_run.get("run_id", "")
    
    keyboard = []
    
    if status in ["running", "pending", "waiting_input"]:
        # 进行中的任务 - [P86] 增加从检查点恢复选项
        keyboard.append([
            {"text": "📥 从检查点恢复", "callback_data": f"reuse:resume:{run_id}"},
            {"text": "👀 查看状态", "callback_data": f"reuse:continue:{run_id}"}
        ])
        keyboard.append([
            {"text": "🆕 开启新任务", "callback_data": "reuse:new"}
        ])
    elif status in ["completed"]:
        # 已完成的任务
        keyboard.append([
            {"text": "📄 提取已有报告", "callback_data": f"reuse:report:{run_id}"},
            {"text": "🔬 基于报告深化", "callback_data": f"reuse:refine:{run_id}"}
        ])
        keyboard.append([
            {"text": "🆕 开启新任务", "callback_data": "reuse:new"}
        ])
    elif status in ["failed", "stopped", "cancelled"]:
        # 失败/停止的任务
        keyboard.append([
            {"text": "🔄 重试任务", "callback_data": f"reuse:retry:{run_id}"},
            {"text": "🆕 开启新任务", "callback_data": "reuse:new"}
        ])
    else:
        # 未知状态，默认选项
        keyboard.append([
            {"text": "🆕 开启新任务", "callback_data": "reuse:new"}
        ])
    
    # 取消按钮
    keyboard.append([
        {"text": "❌ 取消", "callback_data": "reuse:cancel"}
    ])
    
    return {"inline_keyboard": keyboard}

