import os
import json
import logging
import subprocess
import threading
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("mcp_client")

@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]

class MCPClient:
    """
    一个简单的 Python MCP 客户端，通过 Stdio 与 MCP 服务器通信。
    实现了 MCP 协议的核心部分：initialize, tools/list, tools/call。
    """
    
    def __init__(self, command: str, args: List[str], env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None):
        self.command = command
        self.args = args
        self.env = env or os.environ.copy()
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._pending_requests: Dict[int, Any] = {}
        self._lock = threading.Lock()
        self._connected = False
        
        # 启动服务器进程
        self._start_server()
        
    def _start_server(self):
        """启动 MCP 服务器子进程"""
        try:
            full_command = [self.command] + self.args
            logger.info(f"正在启动 MCP 服务器: {' '.join(full_command)} (cwd={self.cwd})")
            
            self.process = subprocess.Popen(
                full_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                cwd=self.cwd,
                text=True,
                bufsize=0,  # 无缓冲
                encoding='utf-8'
            )
            
            # 启动读取线程
            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()
            
            # 初始化连接
            self._initialize()
            
        except Exception as e:
            logger.error(f"启动 MCP 服务器失败: {e}")
            raise

    def _initialize(self):
        """发送 initialize 请求"""
        response = self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "chemdeep-python-client",
                "version": "1.0.0"
            }
        })
        
        if response:
            self._connected = True
            logger.info(f"MCP 服务器已连接: {response.get('serverInfo', {}).get('name')}")
            # 发送 notifications/initialized
            self.send_notification("notifications/initialized", {})
        else:
            raise RuntimeError("MCP 初始化失败")

    def _read_stdout(self):
        """读取服务器 stdout"""
        if not self.process or not self.process.stdout:
            return
            
        buffer = ""
        while True:
            try:
                # 按行读取 JSON-RPC 消息
                line = self.process.stdout.readline()
                if not line:
                    break
                    
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    message = json.loads(line)
                    self._handle_message(message)
                except json.JSONDecodeError:
                    logger.warning(f"无法解析 JSON 消息: {line}")
                    
            except Exception as e:
                logger.error(f"读取 stdout 错误: {e}")
                break

    def _read_stderr(self):
        """读取服务器 stderr (日志)"""
        if not self.process or not self.process.stderr:
            return
            
        while True:
            try:
                line = self.process.stderr.readline()
                if not line:
                    break
                logger.debug(f"MCP Server Log: {line.strip()}")
            except Exception:
                break

    def _handle_message(self, message: Dict[str, Any]):
        """处理接收到的消息"""
        if "id" in message:
            # 这是一个响应
            req_id = message["id"]
            if req_id in self._pending_requests:
                # 这是一个请求的响应
                # 这里我们简单地不需要做太多，因为 send_request 在等待
                # 但如果是异步实现，这里会触发回调
                pass
        else:
            # 这是一个通知或请求
            method = message.get("method")
            if method == "ping":
                # 回复 ping
                pass

    def send_request(self, method: str, params: Optional[Dict] = None, timeout: int = 30) -> Any:
        """发送 JSON-RPC 请求并等待响应 (同步实现)"""
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("MCP 服务器未运行")
            
        req_id = self._request_id
        self._request_id += 1
        
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method
        }
        if params is not None:
            request["params"] = params
            
        message_str = json.dumps(request)
        
        # 我们需要一种机制来等待特定的响应
        # 在这个简化的同步实现中，我们直接写入并期望读取线程处理
        # 但标准输入输出是异步的，所以我们需要一个事件或队列
        
        # 重新设计：为了简化，我们在这里直接从 stdout 读取，但这会与 _read_stdout 冲突
        # 正确的做法是使用 Future/Event
        
        # 这里使用一个简单的 Event 机制
        result_container = {}
        event = threading.Event()
        
        def response_handler(msg):
            if msg.get("id") == req_id:
                result_container["response"] = msg
                event.set()
        
        # 注册临时的处理器 (这需要修改 _handle_message 逻辑)
        # 为了简单，我们使用一个字典来存储 pending requests 的 completion events
        self._pending_requests[req_id] = event
        self._pending_requests[f"{req_id}_result"] = result_container
        
        try:
            logger.debug(f"发送请求: {message_str}")
            with self._lock:
                self.process.stdin.write(message_str + "\n")
                self.process.stdin.flush()
            
            # 等待响应
            if not event.wait(timeout):
                raise TimeoutError(f"请求 {method} 超时")
            
            response = result_container.get("response", {})
            
            if "error" in response:
                raise RuntimeError(f"MCP 错误: {response['error']}")
                
            return response.get("result")
            
        finally:
            # 清理
            self._pending_requests.pop(req_id, None)
            self._pending_requests.pop(f"{req_id}_result", None)

    # 覆盖 _handle_message 以支持同步等待
    def _handle_message(self, message: Dict[str, Any]):
        """处理接收到的消息"""
        logger.debug(f"收到消息: {json.dumps(message)[:200]}...")
        
        if "id" in message:
            req_id = message["id"]
            if req_id in self._pending_requests:
                # 找到了等待的请求
                result_container = self._pending_requests.get(f"{req_id}_result")
                if result_container is not None:
                    result_container["response"] = message
                    
                event = self._pending_requests.get(req_id)
                if event:
                    event.set()
        else:
            # 通知处理
            logger.debug(f"收到通知: {message.get('method')}")

    def send_notification(self, method: str, params: Optional[Dict] = None):
        """发送通知（不等待响应）"""
        if not self.process:
            return
            
        notification = {
            "jsonrpc": "2.0",
            "method": method
        }
        if params is not None:
            notification["params"] = params
            
        with self._lock:
            self.process.stdin.write(json.dumps(notification) + "\n")
            self.process.stdin.flush()

    def list_tools(self) -> List[MCPTool]:
        """列出可用工具"""
        result = self.send_request("tools/list")
        tools_data = result.get("tools", [])
        return [
            MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {})
            )
            for t in tools_data
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any], timeout: int = 600) -> Any:
        """调用工具"""
        result = self.send_request("tools/call", {
            "name": name,
            "arguments": arguments
        }, timeout=timeout)
        
        return result

    def close(self):
        """关闭连接"""
        if self.process:
            self.process.terminate()
            self.process.wait()
            self.process = None
