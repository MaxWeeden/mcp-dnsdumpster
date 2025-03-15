# MCP DNSDumpster

A Model Context Protocol (MCP) server for interacting with the DNSDumpster API, enabling AI assistants to perform detailed DNS reconnaissance through natural language requests.

## Features

- Query domain DNS records through AI assistants
- Retrieve detailed information about:
  - A records (with associated IP and ASN information)
  - CNAME records
  - MX records
  - TXT records
  - NS records (with associated IP and ASN information)
  - Banner information where available
- Support for pagination (Plus accounts)
- Support for domain map generation (Plus accounts)
- Rate limiting to respect DNSDumpster API restrictions
- Robust error handling

## Installation

### Quick Start with npx

```bash
npx @modelcontextprotocol/mcp-dnsdumpster
```

### Claude Desktop Configuration

Add this to your Claude Desktop configuration (usually found in `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%AppData%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "dnsdumpster": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/mcp-dnsdumpster"],
      "env": {
        "DNSDUMPSTER_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### From Source

```bash
# Clone the repository
git clone https://github.com/yourusername/mcp-dnsdumpster.git
cd mcp-dnsdumpster

# Install the package
pip install -e .
```

## Usage

### Environment Setup

First, set your DNSDumpster API key as an environment variable:

```bash
export DNSDUMPSTER_API_KEY=your_api_key_here
```

### Running the Server

```bash
# Run using npx (recommended)
npx @modelcontextprotocol/mcp-dnsdumpster

# Or run the server directly if installed from source
mcp-dnsdumpster

# Or using the MCP CLI
mcp run "python -m mcp_dnsdumpster.server"
```

### Using with Claude Desktop

1. Get Claude Desktop from [claude.ai/download](https://claude.ai/download)
2. Add the configuration shown above to your Claude Desktop config
3. Ask Claude to perform DNS reconnaissance for a domain

### Example Prompts

Once connected to the MCP server, Claude can handle requests like:

- "Show me all subdomains for example.com"
- "What are the mail servers for microsoft.com?"
- "Tell me about the DNS infrastructure for twitter.com"
- "Find all DNS records for this domain"
- "What ASN networks are hosting example.com's infrastructure?"
- "Are there any unusual TXT records for this domain?"
- "Generate a visual map of Facebook's domain structure"

## Development

### Requirements

- Python 3.8+
- MCP SDK 1.2.0+
- HTTPX 0.25.0+

### Testing with MCP Inspector

The MCP Inspector provides an interactive interface for testing your server:

```bash
mcp dev src/mcp_dnsdumpster/server.py
```

## Security and Privacy Considerations

- API keys are stored securely using environment variables
- Input domain names are validated before sending to the API
- Rate limiting is implemented to respect DNSDumpster's terms of service
- Query results are cached temporarily to reduce duplicate API calls
- All HTTP connections use proper timeouts and error handling

## License

MIT