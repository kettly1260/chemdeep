@echo off
echo ========================================
echo ChemDeep MCP Server 启动测试
echo ========================================
echo.

cd /d G:\LLM\chemdeep

echo 检查 Python 环境...
python --version
if errorlevel 1 (
    echo 错误: Python 未安装或不在 PATH 中
    pause
    exit /b 1
)

echo.
echo 检查依赖...
python -c "import mcp; print('MCP 模块 OK')"
if errorlevel 1 (
    echo 错误: MCP 模块未安装
    echo 请运行: pip install mcp
    pause
    exit /b 1
)

echo.
echo 测试服务器导入...
python -c "from mcp_server.server import server; print('服务器导入成功')"
if errorlevel 1 (
    echo 错误: 服务器导入失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo 所有检查通过!
echo ========================================
echo.
echo 在 Cherry Studio / OpenClaw 中配置:
echo.
echo 命令: python
echo 参数: G:\LLM\chemdeep\mcp_server\server.py
echo 工作目录: G:\LLM\chemdeep
echo.
echo 或者使用此脚本启动服务器进行测试...
echo.
pause

echo 启动 MCP 服务器...
python mcp_server\server.py
