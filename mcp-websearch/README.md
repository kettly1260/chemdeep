# search-mcp: Minimal Web Search MCP Server

A simple, reliable MCP server for web search using DuckDuckGo. No API keys required.
Totally vibe-coded in ~25 minutes. Don't trust this app (even if it works for me).

## Features

- **Single tool**: `web_search` - search the web via DuckDuckGo
- **No API keys needed** - uses free DuckDuckGo API
- **Timeout handling** - 10-second timeout per request to prevent hanging
- **Minimal dependencies** - only `mcp` and `requests`
- **Proper MCP protocol** - correct stdio transport implementation

## Installation

```bash
cd ~/Code/search-mcp
pip install -e .
```

Or with uv:

```bash
cd ~/Code/search-mcp
uv pip install -e .
```

## Usage

### Direct Testing

```bash
python search_mcp.py
```

Then send JSON-RPC requests via stdin:

```json
{"jsonrpc": "2.0", "method": "tools/list", "id": 1}
```

### Amazon Q Configuration

Add to your `~/.config/cursor/mcp.json` or Kiro-CLI config:

```json
{
  "mcpServers": {
    "WebSearch": {
      "type": "stdio",
      "command": "python3",
      "args": ["/Users/USERNAME/Code/search-mcp/search_mcp.py"],
      "timeout": 120000,
      "disabled": false
    }
  }
}
```

## Tool: `web_search`

**Parameters:**
- `query` (string, required): The search query
- `max_results` (integer, optional): Max results to return (default: 5)

**Example:**
```python
await client.call_tool("web_search", {"query": "Python async programming", "max_results": 3})
```

## Why This Works

1. **Correct MCP protocol** - properly implements stdio transport with persistent connection
2. **Timeout handling** - 10-second timeout on requests to prevent Amazon Q hangs
3. **Error handling** - gracefully handles network errors and timeouts
4. **Simple codebase** - ~150 lines, easy to debug or modify
5. **No external service** - uses DuckDuckGo's free API, no rate limiting issues

## Troubleshooting

### Module not found errors

Make sure you installed with `pip install -e .`:

```bash
python3 venv .venv
source .venv/bin/activate
pip install -e .
```

### Server not responding

Check that the Python path is correct in your config:

```bash
which python3
python3 search_mcp.py
```

### Timeout issues

The server has a 10-second timeout per request. If searches are timing out:
- Check your internet connection
- Verify DuckDuckGo is accessible
- Try simpler/shorter search queries

## License

MIT
