import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.mcp_client import MCPClient
from config.settings import settings

logger = logging.getLogger("mcp_search")


class MCPSearcher:
    """
    MCP 搜索客户端封装。
    负责初始化 MCP 连接并暴露特定的搜索方法。
    """

    _instance = None
    _client: Optional[MCPClient] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MCPSearcher, cls).__new__(cls)
        return cls._instance

    def _get_client(self) -> MCPClient:
        """获取或创建 MCP 客户端实例（懒加载）"""
        if self._client is None:
            try:
                # 确定 MCP 服务器路径
                server_dir = settings.BASE_DIR / settings.MCP_SERVER_DIR
                if not server_dir.exists():
                    raise FileNotFoundError(f"MCP 服务器目录不存在: {server_dir}")

                # 构建环境
                env = os.environ.copy()
                if settings.MCP_WOS_API_KEY:
                    env["WOS_API_KEY"] = settings.MCP_WOS_API_KEY
                    env["WOS_API_VERSION"] = settings.MCP_WOS_API_VERSION

                # [P78] Proxy Support for Node MCP (OpenAlex/SciHub/WoS)
                if settings.CHEMDEEP_WEBSEARCH_PROXY:
                    logger.info(
                        f"Setting Node MCP Proxy: {settings.CHEMDEEP_WEBSEARCH_PROXY}"
                    )
                    env["HTTP_PROXY"] = settings.CHEMDEEP_WEBSEARCH_PROXY
                    env["HTTPS_PROXY"] = settings.CHEMDEEP_WEBSEARCH_PROXY
                    env["ALL_PROXY"] = settings.CHEMDEEP_WEBSEARCH_PROXY

                # OpenAlex Polite Pool (higher rate limits)
                if hasattr(settings, "OPENALEX_MAILTO") and settings.OPENALEX_MAILTO:
                    env["OPENALEX_MAILTO"] = settings.OPENALEX_MAILTO
                if hasattr(settings, "OPENALEX_API_KEY") and settings.OPENALEX_API_KEY:
                    env["OPENALEX_API_KEY"] = settings.OPENALEX_API_KEY

                # 创建客户端
                self._client = MCPClient(
                    command=settings.MCP_SERVER_COMMAND,
                    args=settings.MCP_SERVER_ARGS,
                    env=env,
                    cwd=str(server_dir),  # 设置工作目录为 MCP 项目根目录
                )
            except Exception as e:
                logger.error(f"MCP 客户端初始化失败: {e}")
                raise

        return self._client

    def _ensure_client_with_cwd(self):
        """确保 Client 初始化，并处理 CWD 问题"""
        if self._client:
            return self._client

        # 修改 MCPClient 需要 step，这里我们直接创建一个新的 MCPClient 类变体或者
        # 意识到我们应该在之前的步骤中添加 cwd 支持。
        # 既然我有 write_to_file 权限，我可以直接重写 mcp_client.py 添加 cwd 支持。
        # 但我不想中断这个 write。

        # 让我们先不要在这里实现，而是先修正 mcp_client.py。
        return None

    def _parse_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """解析 MCP 工具返回的结果"""
        try:
            content_list = result.get("content", [])
            if not content_list:
                return {"success": False, "error": "Empty content in MCP response"}

            text_content = ""
            for item in content_list:
                if item.get("type") == "text":
                    text_content += item.get("text", "")

            # 尝试提取 JSON
            # 格式通常是 "Found X papers.\n\n[...]"
            json_start = text_content.find("[")
            if json_start == -1:
                json_start = text_content.find("{")

            if json_start != -1:
                json_str = text_content[json_start:]
                # 简单的清理
                json_str = json_str.strip()
                if json_str.endswith("`"):  # 处理 markdown block
                    json_str = json_str.rstrip("`")

                try:
                    data = json.loads(json_str)
                    return {
                        "success": True,
                        "papers": data if isinstance(data, list) else [data],
                    }
                except json.JSONDecodeError as e:
                    # [P78] Return raw error for debugging
                    logger.warning(
                        f"MCP Response JSON Parse Failed: {e}. Content: {text_content[:200]}..."
                    )
                    return {
                        "success": False,
                        "error": f"Could not parse JSON from response: {text_content}",
                    }

            # No JSON found?
            return {
                "success": False,
                "error": f"No JSON content found in response: {text_content[:200]}...",
            }

        except Exception as e:
            return {"success": False, "error": f"Error parsing result: {e}"}

    def search_papers(
        self, query: str, platform: str = "all", max_results: int = 10, **kwargs
    ) -> Dict[str, Any]:
        """
        [P69] 通用搜索 (Enhanced)
        逻辑: 默认使用 Lanfanshu（烂番薯学术，国内友好）。如果结果不足，自动扩展搜索 OpenAlex 和 Crossref。
        """
        client = self._get_client()

        # Helper to execute search safely
        def _do_search(plat):
            try:
                # WoS via specialized method
                if plat == "wos":
                    # Call dedicated method ensuring correct tool usage
                    return self.search_wos(query, max_results, **kwargs)

                # Others via 'search_papers' tool
                args = {
                    "query": query,
                    "platform": plat,
                    "maxResults": max_results,
                    **kwargs,
                }
                res = client.call_tool("search_papers", args)
                return self._parse_result(res)
            except Exception as e:
                logger.error(f"Search error ({plat}): {e}")
                return {"success": False, "papers": []}

        # 1. Primary Search: Lanfanshu（烂番薯学术）优先
        # 'all' implies default behavior -> Lanfanshu
        initial_plat = "lanfanshu" if platform == "all" else platform

        start_result = _do_search(initial_plat)
        if not start_result.get("success", False):
            # If primary fails, define papers as empty and continue expansion if 'all'
            papers = []
        else:
            papers = start_result.get("papers", [])

        # [P69] Auto-Expansion Logic - 扩展搜索 OpenAlex 和 Crossref
        if platform == "all" and len(papers) < max_results:
            logger.info(
                f"  [Auto-Expand] Results low ({len(papers)} < {max_results}), querying OpenAlex & Crossref..."
            )

            # 2. OpenAlex
            res_openalex = _do_search("openalex")
            new_o = res_openalex.get("papers", [])
            if new_o:
                logger.info(f"    + OpenAlex: {len(new_o)}")
                papers.extend(new_o)

            # 3. Crossref
            res_crossref = _do_search("crossref")
            new_c = res_crossref.get("papers", [])
            if new_c:
                logger.info(f"    + Crossref: {len(new_c)}")
                papers.extend(new_c)

        # Deduplication
        unique_papers = []
        seen = set()
        for p in papers:
            # key: doi > title
            key = (p.get("doi") or p.get("title", "")).lower()
            # If no key, keep it? No, skip duplicates.
            if not key:
                unique_papers.append(p)
                continue

            if key not in seen:
                seen.add(key)
                unique_papers.append(p)

        return {
            "success": True,
            "papers": unique_papers,
            "expanded_sources": ["wos", "springer"]
            if len(papers) > len(start_result.get("papers", []))
            else [],
        }

    def search_google_scholar(
        self, query: str, max_results: int = 10, **kwargs
    ) -> Dict[str, Any]:
        """Google Scholar 搜索"""
        try:
            client = self._get_client()
            args = {"query": query, "maxResults": max_results, **kwargs}
            result = client.call_tool("search_google_scholar", args)
            return self._parse_result(result)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_lanfanshu(
        self, query: str, max_results: int = 10, **kwargs
    ) -> Dict[str, Any]:
        """
        烂番薯学术搜索
        显式调用下游通用 search_papers 工具，并固定 platform=lanfanshu。
        """
        try:
            client = self._get_client()
            args = {
                "query": query,
                "platform": "lanfanshu",
                "maxResults": max_results,
                **kwargs,
            }
            logger.info(
                "Upstream search_lanfanshu -> downstream tool=search_papers, platform=lanfanshu, query=%s, max_results=%s",
                query,
                max_results,
            )
            result = client.call_tool("search_papers", args)
            parsed = self._parse_result(result)
            if parsed.get("success"):
                logger.info(
                    "Lanfanshu search completed via downstream search_papers: papers=%s",
                    len(parsed.get("papers", [])),
                )
            else:
                logger.warning(
                    "Lanfanshu search returned failure via downstream search_papers: error=%s",
                    parsed.get("error"),
                )
            return parsed
        except Exception as e:
            logger.error(
                "烂番薯学术搜索失败: upstream=search_lanfanshu, downstream=search_papers, platform=lanfanshu, error=%s",
                e,
            )
            return {"success": False, "error": str(e)}

    def search_wos(self, query: str, max_results: int = 10, **kwargs) -> Dict[str, Any]:
        """Web of Science 搜索"""
        try:
            client = self._get_client()
            args = {"query": query, "maxResults": max_results, **kwargs}
            # 注意: WoS 需要 API Key，已在 mcp_client 初始化时注入环境变量
            result = client.call_tool("search_webofscience", args)
            return self._parse_result(result)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_openalex(
        self, query: str, max_results: int = 10, **kwargs
    ) -> Dict[str, Any]:
        """OpenAlex 搜索"""
        try:
            client = self._get_client()
            args = {"query": query, "maxResults": max_results, **kwargs}
            result = client.call_tool("search_openalex", args)
            return self._parse_result(result)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def download_paper(
        self, paper_id: str, platform: str, save_path: str
    ) -> Dict[str, Any]:
        """下载论文 PDF (Node.js MCP) - [P84] Made synchronous"""
        try:
            client = self._get_client()
            args = {"paperId": paper_id, "platform": platform, "savePath": save_path}
            result = client.call_tool("download_paper", args, timeout=120)
            return self._parse_result(result)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_scihub(
        self, doi_or_url: str, download_pdf: bool = True, save_path: str = ""
    ) -> Dict[str, Any]:
        """Sci-Hub 搜索/下载 (Node.js MCP) - [P84] Made synchronous"""
        try:
            client = self._get_client()
            args = {
                "doiOrUrl": doi_or_url,
                "downloadPdf": download_pdf,
                "savePath": save_path,
            }
            result = client.call_tool("search_scihub", args, timeout=120)
            return self._parse_result(result)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_paper_by_doi(self, doi: str) -> Dict[str, Any]:
        """通过 DOI获取论文"""
        try:
            client = self._get_client()
            result = client.call_tool("get_paper_by_doi", {"doi": doi})
            parsed = self._parse_result(result)
            if parsed["success"]:
                # 根据 DeepResearch 期望的格式，这里可能不需要改动太多
                return parsed
            return parsed
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def search_hybrid(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """
        P20: 并行混合搜索 (Academic Node + Web Scout)
        同时执行学术数据库搜索和开放网络搜索，通过 DOI 智能合并结果。
        """
        import asyncio
        from core.scout.web_scout import WebScout
        from core.scout.result_merger import ResultMerger

        try:
            logger.info(f"🚀 启动混合搜索: {query}")
            web_scout = WebScout()

            # 定义两个并行任务

            # 任务 A: 学术数据库搜索 (Node MCP)
            # 注意: self.search_papers 是同步调用 (call_tool 是同步的，因为 MCPClient 目前是同步 IO)
            # 为了实现真正的并行，我们需要将同步 IO 放到线程池中，或者 MCPClient 本身支持 async
            # 当前 MCPClient 是基于 subprocess.Popen 的同步实现。
            # 临时方案: 使用 asyncio.to_thread 包装同步调用

            async def run_node_search():
                logger.info("  Starting Node Search...")
                return self.search_papers(query, max_results=max_results)

            # 任务 B: Web Scout 搜索 (Python MCP)
            # WebScout.search 也是同步调用 (因为 mcp_client.py 是同步的)
            async def run_web_search():
                logger.info("  Starting Web Scout...")
                # 使用 to_thread 避免阻塞事件循环
                # 注意: search 方法内部也有 logging
                return await asyncio.to_thread(
                    web_scout.search, query, max_results=max_results
                )

            # 并行执行
            # run_node_search 也要包装在 to_thread?
            # self.search_papers -> client.call_tool -> subprocess read/write (blocking)
            # 是的，必须包装。

            node_future = asyncio.to_thread(
                self.search_papers, query, max_results=max_results
            )
            web_future = asyncio.to_thread(
                web_scout.search, query, max_results=max_results
            )

            results = await asyncio.gather(
                node_future, web_future, return_exceptions=True
            )

            node_res, web_res = results[0], results[1]

            # 处理结果异常
            final_node_list = []
            if isinstance(node_res, Exception):
                logger.error(f"Node Search Error: {node_res}")
            elif isinstance(node_res, dict):
                if node_res.get("success"):
                    final_node_list = node_res.get("papers", [])
                else:
                    logger.warning(f"Node Search Failed: {node_res.get('error')}")

            final_web_list = []
            if isinstance(web_res, Exception):
                logger.error(f"Web Scout Error: {web_res}")
            elif isinstance(web_res, list):
                final_web_list = web_res

            # 智能合并
            merged_results = ResultMerger.merge(final_node_list, final_web_list)

            return {
                "success": True,
                "papers": merged_results,
                "meta": {
                    "node_count": len(final_node_list),
                    "web_count": len(final_web_list),
                    "total_count": len(merged_results),
                },
            }

        except Exception as e:
            logger.error(f"Hybrid Search Failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


# [P40] Singleton Instance
mcp_searcher = MCPSearcher()
