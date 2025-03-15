# DNSDumpster - MCP Server

A Model Context Protocol (MCP) server for interacting with the DNSDumpster API, enabling AI assistants to perform detailed DNS reconnaissance through natural language requests.

## Features

- Query domain DNS records through AI assistants
- Retrieve detailed information about:
  - A records (with associated IP and ASN information)
  - CNAME records
  - MX records
  - TXT records
  - NS records
  - Banner information where available
- Support for pagination (Plus accounts)
- Support for domain map generation (Plus accounts)
- Rate limiting and caching

[![PyPI version](https://badge.fury.io/py/mcp-dnsdumpster.svg)](https://pypi.org/project/mcp-dnsdumpster/)

## Installation

```bash
# Install from PyPI
uv pip install mcp-dnsdumpster

# Or from source
git clone https://github.com/yourusername/mcp-dnsdumpster.git
cd mcp-dnsdumpster
uv pip install -e .
```

## Claude Desktop Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%AppData%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "dnsdumpster": {
      "command": "uvx",
      "args": ["mcp-dnsdumpster"],
      "env": {
        "DNSDUMPSTER_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

## Usage

1. Set your API key:
```bash
export DNSDUMPSTER_API_KEY=your_api_key_here
```

2. Run the server:
```bash
# Using uvx (recommended)
uvx mcp-dnsdumpster

# Or if installed from source
uv run server.py
```

### Example Prompts

- "Show me all subdomains for example.com"
- "What are the mail servers for microsoft.com?"
- "Tell me about the DNS infrastructure for twitter.com"
- "Generate a visual map of Facebook's domain structure"

## Development

- Python 3.10+
- Uses `uv` for dependency management
- Built with MCP SDK 1.4+

## License

MIT

