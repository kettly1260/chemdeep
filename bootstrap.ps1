# bootstrap.ps1
# 一键环境构建脚本
# Usage: .\bootstrap.ps1

# [Fix] 强制使用 UTF-8 输出以正确显示中文和 Emoji
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1. 自动切换到脚本所在目录 (Repo Root)
Set-Location $PSScriptRoot
Write-Host "🚀 Starting ChemDeep Bootstrap..." -ForegroundColor Cyan

# 2. 检查并安装 uv
if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Host "⚠️ uv command not found. Installing via pip..." -ForegroundColor Yellow
    try {
        # 尝试使用 py 启动器
        py -m pip install -U uv
    }
    catch {
        # 降级尝试直接使用 python
        try {
            python -m pip install -U uv
        }
        catch {
            Write-Host "❌ Failed to install uv. Please install Python and ensure pip is in PATH." -ForegroundColor Red
            exit 1
        }
    }
}
Write-Host "✅ uv is ready" -ForegroundColor Green

# 3. 创建/复用 .venv
if (-not (Test-Path ".venv")) {
    Write-Host "📦 Creating .venv..." -ForegroundColor Cyan
    uv venv .venv
}
else {
    Write-Host "📦 Using existing .venv..." -ForegroundColor Cyan
}

# 定义 Venv Python路径
$VENV_PYTHON = ".\.venv\Scripts\python.exe"

# 4. 安装 Python 依赖
if (Test-Path "requirements.lock.txt") {
    Write-Host "🔒 Found requirements.lock.txt. Syncing dependencies..." -ForegroundColor Cyan
    # 使用 lock 文件同步，确保绝对一致
    uv pip sync --python $VENV_PYTHON requirements.lock.txt
}
else {
    Write-Host "📝 No lock file found. Installing from requirements.txt..." -ForegroundColor Cyan
    # 按 loose requirements 安装
    uv pip install --python $VENV_PYTHON -r requirements.txt
    
    # 生成 Lock 文件作为落地物
    Write-Host "🔐 Generating requirements.lock.txt..." -ForegroundColor Cyan
    uv pip compile requirements.txt -o requirements.lock.txt
    
    Write-Host "💡 Hint: A new 'requirements.lock.txt' has been generated." -ForegroundColor Yellow
    Write-Host "💡 Please commit this file to the repository to ensure reproducibility." -ForegroundColor Yellow
}

# 5. 安装 Playwright 浏览器
Write-Host "🎭 Installing Playwright browsers..." -ForegroundColor Cyan
& $VENV_PYTHON -m playwright install

# 6. 构建 Node MCP Server (如果有 Node 环境)
if (Get-Command "npm" -ErrorAction SilentlyContinue) {
    if (Test-Path "paper-search-mcp-nodejs") {
        Write-Host "📦 Building Node MCP Server (paper-search-mcp-nodejs)..." -ForegroundColor Cyan
        Push-Location paper-search-mcp-nodejs
        try {
            # 使用 npm ci 保证一致性，如果 failed (比如没有 lock file) 则尝试 install
            if (Test-Path "package-lock.json") {
                npm ci
            }
            else {
                npm install
            }
            npm run build
        }
        catch {
            Write-Host "⚠️ Warning: MCP Build Failed. Search capabilities might be limited." -ForegroundColor Yellow
            Write-Host "Error: $_" -ForegroundColor DarkGray
        }
        Pop-Location
    }
}
else {
    Write-Host "⚠️ Node/npm not found. Skipping MCP server build." -ForegroundColor Yellow
}

# 7. Config 初始化兜底
if (-not (Test-Path "config\.env")) {
    Write-Host "⚙️ Config (.env) not found. Running initialization..." -ForegroundColor Cyan
    # 调用 main.py init (Typer command)
    & $VENV_PYTHON main.py init
}

# 8. 完整性自检
Write-Host "✅ Running Environment Self-Check..." -ForegroundColor Cyan
try {
    # 调用现有的 debug_import.py
    & $VENV_PYTHON debug_import.py
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "🎉 Bootstrap Complete! Environment is ready." -ForegroundColor Green
        Write-Host "💡 To start the bot:  $VENV_PYTHON main.py bot" -ForegroundColor Cyan
    }
    else {
        Write-Host "❌ Self-check failed. Missing dependencies detected." -ForegroundColor Red
        Write-Host "Please check console output above for missing packages." -ForegroundColor Red
        Write-Host "Add them to 'requirements.txt' and re-run bootstrap.ps1." -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "❌ Failed to execute self-check script: $_" -ForegroundColor Red
    exit 1
}
