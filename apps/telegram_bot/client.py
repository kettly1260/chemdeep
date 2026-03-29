import httpx
import logging
from pathlib import Path
from typing import Any
from config.settings import settings

logger = logging.getLogger('bot')


class TelegramClient:
    def __init__(self, token: str = None, proxy: str = None):
        self._token = token or settings.TELEGRAM_TOKEN
        self._base = f"https://api.telegram.org/bot{self._token}"
        self._proxy = proxy or settings.TELEGRAM_PROXY
        
        # [P55] Enhance stability
        timeout = httpx.Timeout(60.0, connect=20.0, read=60.0, write=30.0)
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10, keepalive_expiry=30)
        
        if self._proxy:
            try:
                self._client = httpx.Client(proxy=self._proxy, timeout=timeout, limits=limits)
            except TypeError:
                 # Older httpx or different signature fallback via kwargs hack if needed, 
                 # but 0.28 should support proxy arg or use 'proxies'.
                 # Note: httpx 0.24+ deprecated 'proxies' (plural) in init for 'proxy' (singular match) 
                 # or 'mounts'. But allow fallback.
                self._client = httpx.Client(proxies=self._proxy, timeout=timeout, limits=limits)
        else:
            self._client = httpx.Client(timeout=timeout, limits=limits)

    def _describe_api_error(self, err: Exception) -> str:
        if isinstance(err, httpx.HTTPStatusError) and err.response is not None:
            try:
                body = err.response.text
            except Exception:
                body = "<unavailable>"
            return f"{err} | response={body}"
        return str(err)

    def _should_retry_without_parse_mode(self, err: Exception, parse_mode: str | None) -> bool:
        if not parse_mode:
            return False
        if not isinstance(err, httpx.HTTPStatusError) or err.response is None:
            return False
        if err.response.status_code != 400:
            return False

        body = err.response.text.lower()
        return any(
            marker in body
            for marker in (
                "can't parse entities",
                "can't find end of",
                "is reserved and must be escaped",
                "unsupported start tag",
                "error parsing",
            )
        )

    def _post_json_with_parse_fallback(self, endpoint: str, payload: dict, action_name: str) -> dict | bool | None:
        try:
            r = self._client.post(f"{self._base}/{endpoint}", json=payload)
            r.raise_for_status()
            return r.json().get("result")
        except Exception as err:
            if self._should_retry_without_parse_mode(err, payload.get("parse_mode")):
                fallback_payload = dict(payload)
                failed_parse_mode = fallback_payload.pop("parse_mode", None)
                logger.warning(
                    "%s Markdown 解析失败，改为纯文本重试: parse_mode=%s, detail=%s",
                    action_name,
                    failed_parse_mode,
                    self._describe_api_error(err),
                )
                try:
                    r = self._client.post(f"{self._base}/{endpoint}", json=fallback_payload)
                    r.raise_for_status()
                    return r.json().get("result")
                except Exception as retry_err:
                    logger.error(f"{action_name}失败: {self._describe_api_error(retry_err)}")
                    return None

            logger.error(f"{action_name}失败: {self._describe_api_error(err)}")
            return None

    def send_message(self, chat_id: int, text: str, reply_markup: dict = None, parse_mode: str = None) -> dict | None:
        """发送消息，返回包含 message_id 的响应"""
        max_len = 4000
        if len(text) <= max_len:
            payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
            if reply_markup:
                payload["reply_markup"] = reply_markup
            if parse_mode:
                payload["parse_mode"] = parse_mode
            return self._post_json_with_parse_fallback("sendMessage", payload, "发送消息")

        parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
        result = None
        for i, part in enumerate(parts):
            payload = {"chat_id": chat_id, "text": part, "disable_web_page_preview": True}
            if parse_mode:
                payload["parse_mode"] = parse_mode

            # 只在最后一段添加按钮
            if i == len(parts) - 1 and reply_markup:
                payload["reply_markup"] = reply_markup

            result = self._post_json_with_parse_fallback("sendMessage", payload, "发送消息")
            if result is None:
                return None

        return result

    def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False) -> bool:
        """回应 callback 查询（消除按钮加载状态）"""
        try:
            payload = {"callback_query_id": callback_query_id}
            if text:
                payload["text"] = text
            if show_alert:
                payload["show_alert"] = show_alert
            r = self._client.post(f"{self._base}/answerCallbackQuery", json=payload)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"回应 callback 失败: {e}")
            return False
    
    def edit_message(self, chat_id: int, message_id: int, text: str, reply_markup: dict = None, parse_mode: str = None) -> bool:
        """编辑已发送的消息"""
        max_len = 4000
        text = text[:max_len]  # 截断过长的消息

        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "disable_web_page_preview": True
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode

        result = self._post_json_with_parse_fallback("editMessageText", payload, "编辑消息")
        if result is not None:
            return True

        # 消息内容相同时会报错，忽略此类错误
        try:
            self._client.post(f"{self._base}/editMessageText", json=payload).raise_for_status()
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return False

        return False

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        r = self._client.get(f"{self._base}/getUpdates", params=params)
        r.raise_for_status()
        return r.json().get("result", [])

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        """获取文件信息"""
        try:
            r = self._client.get(f"{self._base}/getFile", params={"file_id": file_id})
            r.raise_for_status()
            return r.json().get("result")
        except Exception as e:
            logger.error(f"获取文件信息失败: {e}")
            return None

    def download_file(self, file_id: str, save_path: Path) -> Path | None:
        """下载文件到本地"""
        try:
            file_info = self.get_file(file_id)
            if not file_info:
                return None
            file_path = file_info.get("file_path")
            if not file_path:
                return None
            download_url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
            r = self._client.get(download_url)
            r.raise_for_status()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(r.content)
            logger.info(f"文件已下载: {save_path}")
            return save_path
        except Exception as e:
            logger.error(f"下载文件失败: {e}")
            return None

    def send_document(self, chat_id: int, file_path: Path | str, caption: str = "") -> bool:
        """发送文件"""
        try:
            if isinstance(file_path, str):
                file_path = Path(file_path)
                
            with open(file_path, "rb") as f:
                files = {"document": (file_path.name, f)}
                data = {"chat_id": chat_id, "caption": caption}
                r = self._client.post(f"{self._base}/sendDocument", data=data, files=files)
                r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"发送文件失败: {e}")
            return False
