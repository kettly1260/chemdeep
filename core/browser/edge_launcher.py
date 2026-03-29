"""
Edge 浏览器启动器

职责:
- 启动真实 Edge 浏览器 (带 CDP)
- 检查浏览器状态
- 连接到运行中的浏览器
"""
import logging
import subprocess
import time
import httpx

logger = logging.getLogger('fetcher')


def launch_real_edge_with_cdp(port: int = 9222) -> tuple[bool, str]:
    """
    启动真实 Edge 浏览器并开启远程调试端口
    
    Returns:
        (success, message)
    """
    import os
    import platform
    
    # 检查是否已经运行
    if is_real_browser_running(port):
        return True, f"Edge 浏览器已在端口 {port} 运行"
        
    # [P73] Check for potential Profile Lock (Edge running without CDP)
    if check_edge_process_running():
        logger.warning(f"检测到 msedge.exe 正在运行但端口 {port} 未开放 (Profile Locked)")
        return False, "PROFILE_LOCKED"
    
    # 查找 Edge 路径
    edge_paths = []
    
    if platform.system() == "Windows":
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]
    elif platform.system() == "Darwin":
        edge_paths = ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    else:
        edge_paths = ["/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable"]
    
    edge_path = None
    for path in edge_paths:
        if os.path.exists(path):
            edge_path = path
            break
    
    if not edge_path:
        return False, "未找到 Microsoft Edge 浏览器"
    
    # 启动 Edge
    try:
        # [Revert P65] Use Isolated Profile to avoid conflicts with running Edge
        # Previous P65 logic used settings.PROFILE_DIR which might point to system profile
        from config.settings import settings
        import os
        
        # Force isolated profile under project directory
        # This ensures we don't conflict with user's main browser
        isolated_profile = settings.BASE_DIR / "profiles" / "isolated_edge_bot"
        isolated_profile.mkdir(parents=True, exist_ok=True)
        user_data_dir = str(isolated_profile)
        
        # NOTE: If user provides absolute path in env var, fine.
        # If not, we might need to be careful.
        # But settings.PROFILE_DIR is defined as Path.
        
        # Ensure dir exists? Edge will create if not.
        
        cmd = [
            edge_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            # "--disable-background-networking", # Don't disable networking for read browser
            # "--disable-sync", # Don't disable sync if we want user state
        ]
        
        # Windows 后台启动
        if platform.system() == "Windows":
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        
        # 等待启动 (增加等待时间 - P70 Fix: Heavy profile needs more time)
        for i in range(60):  # 60 秒超时 (previous 15)
            time.sleep(1)
            if is_real_browser_running(port):
                return True, f"Edge 浏览器已启动在端口 {port}"
        
        # 最后再检查一次
        if is_real_browser_running(port):
            return True, f"Edge 浏览器已启动在端口 {port}"
            
        return False, "Edge 启动超时 (请手动在 Edge 地址栏输入 edge://flags 确认可访问)"
        
    except Exception as e:
        return False, f"启动 Edge 失败: {e}"


def is_real_browser_running(port: int = 9222) -> bool:
    """检查真实浏览器是否已启动 (检查 CDP 端口)"""
    try:
        with httpx.Client(timeout=2) as client:
            resp = client.get(f"http://127.0.0.1:{port}/json/version")
            return resp.status_code == 200
    except Exception:
        return False

def check_edge_process_running() -> bool:
    """[P73] 检查系统是否有 msedge.exe 进程"""
    import platform
    import subprocess
    
    try:
        # Windows only for now (since user is on Windows)
        if platform.system() == "Windows":
            # Use tasklist
            output = subprocess.check_output('tasklist /FI "IMAGENAME eq msedge.exe"', shell=True).decode('gbk', 'ignore')
            return "msedge.exe" in output
        else:
            # Linux/Mac
            output = subprocess.check_output(['pgrep', '-f', 'microsoft-edge'], stderr=subprocess.DEVNULL)
            return bool(output.strip())
    except Exception:
        return False

def kill_edge_process():
    """[P73] 强制关闭所有 Edge 进程"""
    import platform
    import subprocess
    import time
    
    try:
        if platform.system() == "Windows":
            subprocess.run('taskkill /F /IM msedge.exe', shell=True, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(['pkill', '-f', 'microsoft-edge'], stderr=subprocess.DEVNULL)
        
        # Give it a moment to die
        time.sleep(2)
        return True
    except Exception as e:
        logger.error(f"Failed to kill Edge: {e}")
        return False


def _wait_for_cdp_ready(port: int = 9222, timeout_seconds: float = 20.0) -> tuple[bool, str]:
    """等待 CDP HTTP 端点真正就绪，并拿到可用的浏览器 WebSocket 地址。"""
    version_url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout_seconds
    last_error = "CDP endpoint not ready"
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        try:
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(version_url)
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}"
                    logger.info(f"CDP 就绪探测未通过 (attempt={attempt}): {last_error}")
                    time.sleep(0.5)
                    continue

                data = resp.json()
                ws_url = data.get("webSocketDebuggerUrl")
                browser_name = data.get("Browser", "unknown")
                protocol = data.get("Protocol-Version", "unknown")
                if ws_url:
                    logger.info(
                        "CDP 就绪: browser=%s protocol=%s ws=%s",
                        browser_name,
                        protocol,
                        ws_url,
                    )
                    return True, ws_url

                last_error = "missing webSocketDebuggerUrl"
                logger.info(f"CDP 就绪探测未通过 (attempt={attempt}): {last_error}")
        except Exception as e:
            last_error = str(e)
            logger.info(f"CDP 就绪探测异常 (attempt={attempt}): {e}")

        time.sleep(0.5)

    return False, last_error



def connect_to_real_browser(p, port: int = 9222):
    """
    连接到真实的 Edge 浏览器（通过 CDP）
    
    Args:
        p: Playwright 实例
        port: CDP 端口
    
    Returns:
        context: 浏览器上下文，失败返回 None
    """
    try:
        ready, ready_detail = _wait_for_cdp_ready(port, timeout_seconds=20.0)
        if not ready:
            logger.error(f"❌ CDP 端点未就绪，放弃连接: {ready_detail}")
            return None

        max_retries = 6
        connect_timeout_ms = 8000
        connect_url = f"http://127.0.0.1:{port}"

        for attempt in range(max_retries):
            try:
                logger.info(
                    "尝试连接浏览器 (CDP) - 尝试 %s/%s, timeout=%sms",
                    attempt + 1,
                    max_retries,
                    connect_timeout_ms,
                )
                browser = p.chromium.connect_over_cdp(connect_url, timeout=connect_timeout_ms)

                for context_wait_round in range(1, 5):
                    contexts = browser.contexts
                    if contexts:
                        logger.info(
                            "✅ 已连接到真实 Edge 浏览器，获得现有上下文 %s 个 (wait_round=%s)",
                            len(contexts),
                            context_wait_round,
                        )
                        return contexts[0]

                    logger.info(
                        "CDP 已连接但上下文暂未出现，等待默认上下文 (wait_round=%s/4)",
                        context_wait_round,
                    )
                    time.sleep(0.5)

                logger.info("未拿到现有上下文，创建新的 CDP 上下文")
                return browser.new_context()
            except Exception as e:
                logger.warning(f"连接尝试 {attempt+1} 失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)

        logger.error("❌ 所有 CDP 连接尝试均失败")
        return None
    except Exception as e:
        logger.warning(f"连接真实浏览器致命错误: {e}")
        return None


def open_in_real_edge(url: str) -> bool:
    """
    在真实 Edge 浏览器中打开 URL（完全无自动化标识）
    
    Returns:
        bool: 是否成功
    """
    import webbrowser
    
    try:
        webbrowser.open(url)
        return True
    except Exception as e:
        logger.error(f"打开浏览器失败: {e}")
        return False
