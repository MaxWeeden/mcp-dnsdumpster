"""
DNSDumpster MCP Server implementation.

This module contains the main MCP server implementation for interacting with the DNSDumpster API.
"""

import os
import json
import time
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
import re

from mcp.server.fastmcp import FastMCP, Context, Image
from mcp.types import TextContent

# Rate limiting constants
MIN_REQUEST_INTERVAL = 2.0  # 1 request per 2 seconds
MAX_CACHE_AGE = timedelta(hours=1)  # Cache results for 1 hour

# Type alias for DNS records
DNSData = Dict[str, Any]

class APIRateLimiter:
    """Helper class to manage API rate limiting."""
    
    def __init__(self, min_interval: float = MIN_REQUEST_INTERVAL):
        """Initialize the rate limiter.
        
        Args:
            min_interval: Minimum interval between requests in seconds
        """
        self.min_interval = min_interval
        self.last_request_time = 0.0
        self._lock = asyncio.Lock()
    
    async def wait_for_rate_limit(self) -> None:
        """Wait until it's safe to make another request without exceeding rate limits."""
        async with self._lock:
            current_time = time.time()
            elapsed = current_time - self.last_request_time
            
            if elapsed < self.min_interval:
                # Wait for the remaining time
                await asyncio.sleep(self.min_interval - elapsed)
            
            # Update the last request time
            self.last_request_time = time.time()


class DNSCache:
    """Simple cache for DNS records to avoid duplicate API calls."""
    
    def __init__(self, max_age: timedelta = MAX_CACHE_AGE):
        """Initialize the cache.
        
        Args:
            max_age: Maximum age of cached entries
        """
        self.cache: Dict[str, Tuple[DNSData, datetime]] = {}
        self.max_age = max_age
        self._lock = asyncio.Lock()
    
    async def get(self, domain: str) -> Optional[DNSData]:
        """Get cached DNS data for a domain if available and not expired.
        
        Args:
            domain: Domain name to retrieve
        
        Returns:
            Cached DNS data or None if not available
        """
        async with self._lock:
            if domain in self.cache:
                data, timestamp = self.cache[domain]
                if datetime.now() - timestamp < self.max_age:
                    return data
                # Remove expired entry
                del self.cache[domain]
            return None
    
    async def set(self, domain: str, data: DNSData) -> None:
        """Cache DNS data for a domain.
        
        Args:
            domain: Domain name to cache
            data: DNS data to cache
        """
        async with self._lock:
            self.cache[domain] = (data, datetime.now())


class DNSDumpsterClient:
    """Client for the DNSDumpster API."""
    
    def __init__(self, api_key: str):
        """Initialize the DNSDumpster API client.
        
        Args:
            api_key: DNSDumpster API key
        """
        self.api_key = api_key
        self.api_base_url = "https://api.dnsdumpster.com/domain"
        self.rate_limiter = APIRateLimiter()
        self.cache = DNSCache()
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"X-API-Key": api_key}
        )
    
    async def get_dns_records(
        self, 
        domain: str,
        page: Optional[int] = None,
        generate_map: bool = False
    ) -> DNSData:
        """Query the DNSDumpster API for a domain's DNS records.
        
        Args:
            domain: Domain name to query
            page: Page number for pagination (Plus accounts only)
            generate_map: Whether to generate a domain map (Plus accounts only)
        
        Returns:
            Dictionary containing DNS records
        """
        # Check cache first
        cache_key = f"{domain}:{page or 1}:{int(generate_map)}"
        cached_data = await self.cache.get(cache_key)
        if cached_data:
            return cached_data
        
        # Wait for rate limiting
        await self.rate_limiter.wait_for_rate_limit()
        
        # Build URL with query parameters
        url = f"{self.api_base_url}/{domain}"
        params = {}
        
        if page is not None:
            params["page"] = str(page)
        
        if generate_map:
            params["map"] = "1"
        
        # Retry logic for network errors
        max_retries = 3
        retry_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                response = await self.client.get(url, params=params)
                
                if response.status_code == 429:
                    # Handle rate limiting
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    await asyncio.sleep(retry_after)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                # Cache the response
                await self.cache.set(cache_key, data)
                
                return data
                
            except httpx.HTTPError as e:
                if attempt == max_retries - 1:
                    raise Exception(f"Failed to query DNSDumpster API: {str(e)}")
                
                # Exponential backoff
                await asyncio.sleep(retry_delay * (2 ** attempt))
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


def is_valid_domain(domain: str) -> bool:
    """Validate a domain name.
    
    Args:
        domain: Domain name to validate
    
    Returns:
        True if the domain is valid, False otherwise
    """
    pattern = r"^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
    return bool(re.match(pattern, domain))


# Create MCP server
mcp = FastMCP(
    "mcp-dnsdumpster",
    dependencies=["httpx"],
    command="python3",
    args=["-m", "mcp_dnsdumpster.server"]
)


@mcp.tool()
async def query_domain(domain: str, ctx: Context) -> str:
    """Query DNSDumpster for all DNS records related to a domain.
    
    Args:
        domain: The domain name to query (e.g., example.com)
        ctx: Request context
    
    Returns:
        JSON string containing all DNS records
    """
    if not domain:
        return json.dumps({"error": "Domain is required"})
    
    # Validate domain
    if not is_valid_domain(domain):
        return json.dumps({"error": "Invalid domain name format"})
    
    try:
        api_key = os.environ.get("DNSDUMPSTER_API_KEY")
        if not api_key:
            return json.dumps({"error": "API key not configured. Set DNSDUMPSTER_API_KEY environment variable."})
        
        client = DNSDumpsterClient(api_key)
        
        try:
            ctx.info(f"Querying DNS records for {domain}")
            result = await client.get_dns_records(domain)
            return json.dumps(result, indent=2)
        finally:
            await client.close()
            
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_a_records(domain: str, ctx: Context) -> str:
    """Get A records for a domain.
    
    Args:
        domain: The domain name to query (e.g., example.com)
        ctx: Request context
    
    Returns:
        Formatted string containing A records
    """
    if not domain:
        return "Error: Domain is required"
    
    # Validate domain
    if not is_valid_domain(domain):
        return "Error: Invalid domain name format"
    
    try:
        api_key = os.environ.get("DNSDUMPSTER_API_KEY")
        if not api_key:
            return "Error: API key not configured. Set DNSDUMPSTER_API_KEY environment variable."
        
        client = DNSDumpsterClient(api_key)
        
        try:
            ctx.info(f"Querying A records for {domain}")
            result = await client.get_dns_records(domain)
            
            if "a" not in result or not result["a"]:
                return f"No A records found for {domain}"
            
            output_lines = [f"A Records for {domain}:"]
            
            for record in result["a"]:
                host = record.get("host", "")
                output_lines.append(f"\nHost: {host}")
                
                for ip_info in record.get("ips", []):
                    ip = ip_info.get("ip", "")
                    country = ip_info.get("country", "Unknown")
                    asn = ip_info.get("asn", "")
                    asn_name = ip_info.get("asn_name", "")
                    asn_range = ip_info.get("asn_range", "")
                    
                    output_lines.append(f"  IP: {ip}")
                    output_lines.append(f"  Country: {country}")
                    if asn:
                        output_lines.append(f"  ASN: {asn}")
                    if asn_name:
                        output_lines.append(f"  ASN Name: {asn_name}")
                    if asn_range:
                        output_lines.append(f"  ASN Range: {asn_range}")
                    
                    # If banner information is available
                    if "banners" in ip_info:
                        output_lines.append("  Banners:")
                        banners = ip_info["banners"]
                        
                        if "http" in banners:
                            http_banner = banners["http"]
                            output_lines.append("    HTTP:")
                            
                            if "title" in http_banner:
                                output_lines.append(f"      Title: {http_banner['title']}")
                            
                            if "server" in http_banner:
                                output_lines.append(f"      Server: {http_banner['server']}")
                                
                            if "apps" in http_banner:
                                output_lines.append(f"      Apps: {', '.join(http_banner['apps'])}")
                        
                        if "https" in banners:
                            https_banner = banners["https"]
                            output_lines.append("    HTTPS:")
                            
                            if "title" in https_banner:
                                output_lines.append(f"      Title: {https_banner['title']}")
                            
                            if "server" in https_banner:
                                output_lines.append(f"      Server: {https_banner['server']}")
                                
                            if "apps" in https_banner:
                                output_lines.append(f"      Apps: {', '.join(https_banner['apps'])}")
                                
                            if "cn" in https_banner:
                                output_lines.append(f"      CN: {https_banner['cn']}")
                                
                            if "alt_n" in https_banner:
                                output_lines.append(f"      Alt Names: {', '.join(https_banner['alt_n'])}")
            
            return "\n".join(output_lines)
        finally:
            await client.close()
            
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def get_mx_records(domain: str, ctx: Context) -> str:
    """Get MX (mail) records for a domain.
    
    Args:
        domain: The domain name to query (e.g., example.com)
        ctx: Request context
    
    Returns:
        Formatted string containing MX records
    """
    if not domain:
        return "Error: Domain is required"
    
    # Validate domain
    if not is_valid_domain(domain):
        return "Error: Invalid domain name format"
    
    try:
        api_key = os.environ.get("DNSDUMPSTER_API_KEY")
        if not api_key:
            return "Error: API key not configured. Set DNSDUMPSTER_API_KEY environment variable."
        
        client = DNSDumpsterClient(api_key)
        
        try:
            ctx.info(f"Querying MX records for {domain}")
            result = await client.get_dns_records(domain)
            
            if "mx" not in result or not result["mx"]:
                return f"No MX records found for {domain}"
            
            output_lines = [f"MX Records for {domain}:"]
            
            for record in result["mx"]:
                host = record.get("host", "")
                priority = record.get("priority", "")
                
                priority_str = f" (Priority: {priority})" if priority else ""
                output_lines.append(f"\nHost: {host}{priority_str}")
                
                for ip_info in record.get("ips", []):
                    ip = ip_info.get("ip", "")
                    country = ip_info.get("country", "Unknown")
                    asn = ip_info.get("asn", "")
                    asn_name = ip_info.get("asn_name", "")
                    
                    output_lines.append(f"  IP: {ip}")
                    output_lines.append(f"  Country: {country}")
                    if asn:
                        output_lines.append(f"  ASN: {asn}")
                    if asn_name:
                        output_lines.append(f"  ASN Name: {asn_name}")
            
            return "\n".join(output_lines)
        finally:
            await client.close()
            
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def get_ns_records(domain: str, ctx: Context) -> str:
    """Get NS (nameserver) records for a domain.
    
    Args:
        domain: The domain name to query (e.g., example.com)
        ctx: Request context
    
    Returns:
        Formatted string containing NS records
    """
    if not domain:
        return "Error: Domain is required"
    
    # Validate domain
    if not is_valid_domain(domain):
        return "Error: Invalid domain name format"
    
    try:
        api_key = os.environ.get("DNSDUMPSTER_API_KEY")
        if not api_key:
            return "Error: API key not configured. Set DNSDUMPSTER_API_KEY environment variable."
        
        client = DNSDumpsterClient(api_key)
        
        try:
            ctx.info(f"Querying NS records for {domain}")
            result = await client.get_dns_records(domain)
            
            if "ns" not in result or not result["ns"]:
                return f"No NS records found for {domain}"
            
            output_lines = [f"NS Records for {domain}:"]
            
            for record in result["ns"]:
                host = record.get("host", "")
                output_lines.append(f"\nHost: {host}")
                
                for ip_info in record.get("ips", []):
                    ip = ip_info.get("ip", "")
                    country = ip_info.get("country", "Unknown")
                    asn = ip_info.get("asn", "")
                    asn_name = ip_info.get("asn_name", "")
                    asn_range = ip_info.get("asn_range", "")
                    
                    output_lines.append(f"  IP: {ip}")
                    output_lines.append(f"  Country: {country}")
                    if asn:
                        output_lines.append(f"  ASN: {asn}")
                    if asn_name:
                        output_lines.append(f"  ASN Name: {asn_name}")
                    if asn_range:
                        output_lines.append(f"  ASN Range: {asn_range}")
            
            return "\n".join(output_lines)
        finally:
            await client.close()
            
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def get_txt_records(domain: str, ctx: Context) -> str:
    """Get TXT records for a domain.
    
    Args:
        domain: The domain name to query (e.g., example.com)
        ctx: Request context
    
    Returns:
        Formatted string containing TXT records
    """
    if not domain:
        return "Error: Domain is required"
    
    # Validate domain
    if not is_valid_domain(domain):
        return "Error: Invalid domain name format"
    
    try:
        api_key = os.environ.get("DNSDUMPSTER_API_KEY")
        if not api_key:
            return "Error: API key not configured. Set DNSDUMPSTER_API_KEY environment variable."
        
        client = DNSDumpsterClient(api_key)
        
        try:
            ctx.info(f"Querying TXT records for {domain}")
            result = await client.get_dns_records(domain)
            
            if "txt" not in result or not result["txt"]:
                return f"No TXT records found for {domain}"
            
            output_lines = [f"TXT Records for {domain}:"]
            
            for txt in result["txt"]:
                output_lines.append(f"\n{txt}")
            
            return "\n".join(output_lines)
        finally:
            await client.close()
            
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def get_cname_records(domain: str, ctx: Context) -> str:
    """Get CNAME records for a domain.
    
    Args:
        domain: The domain name to query (e.g., example.com)
        ctx: Request context
    
    Returns:
        Formatted string containing CNAME records
    """
    if not domain:
        return "Error: Domain is required"
    
    # Validate domain
    if not is_valid_domain(domain):
        return "Error: Invalid domain name format"
    
    try:
        api_key = os.environ.get("DNSDUMPSTER_API_KEY")
        if not api_key:
            return "Error: API key not configured. Set DNSDUMPSTER_API_KEY environment variable."
        
        client = DNSDumpsterClient(api_key)
        
        try:
            ctx.info(f"Querying CNAME records for {domain}")
            result = await client.get_dns_records(domain)
            
            if "cname" not in result or not result["cname"]:
                return f"No CNAME records found for {domain}"
            
            output_lines = [f"CNAME Records for {domain}:"]
            
            for record in result["cname"]:
                host = record.get("host", "")
                target = record.get("target", "")
                
                output_lines.append(f"\nHost: {host}")
                output_lines.append(f"Target: {target}")
            
            return "\n".join(output_lines)
        finally:
            await client.close()
            
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def generate_domain_map(domain: str, ctx: Context) -> Union[Image, str]:
    """Generate a visual map of a domain's DNS infrastructure (Plus accounts only).
    
    Args:
        domain: The domain name to query (e.g., example.com)
        ctx: Request context
    
    Returns:
        An image of the domain map or an error message
    """
    if not domain:
        return "Error: Domain is required"
    
    # Validate domain
    if not is_valid_domain(domain):
        return "Error: Invalid domain name format"
    
    try:
        api_key = os.environ.get("DNSDUMPSTER_API_KEY")
        if not api_key:
            return "Error: API key not configured. Set DNSDUMPSTER_API_KEY environment variable."
        
        client = DNSDumpsterClient(api_key)
        
        try:
            ctx.info(f"Generating domain map for {domain}")
            result = await client.get_dns_records(domain, generate_map=True)
            
            if "map" not in result or not result["map"]:
                return "Domain map generation not available. This feature requires a Plus account."
            
            # Return the map as an image
            map_data = result["map"]
            if isinstance(map_data, str):
                # If it's base64 encoded data
                return Image(data=map_data, format="png")
            elif isinstance(map_data, dict) and "url" in map_data:
                # If it's a URL to the image
                map_url = map_data["url"]
                async with httpx.AsyncClient() as client:
                    response = await client.get(map_url)
                    response.raise_for_status()
                    return Image(data=response.content, format="png")
            else:
                return "Unexpected format for domain map data"
        finally:
            await client.close()
            
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def search_subdomains(domain: str, ctx: Context, page: int = 1) -> str:
    """Search for subdomains of a given domain.
    
    Args:
        domain: The parent domain name to query (e.g., example.com)
        ctx: Request context
        page: Page number for pagination (Plus accounts only)
    
    Returns:
        Formatted string containing subdomains found
    """
    if not domain:
        return "Error: Domain is required"
    
    # Validate domain
    if not is_valid_domain(domain):
        return "Error: Invalid domain name format"
    
    try:
        api_key = os.environ.get("DNSDUMPSTER_API_KEY")
        if not api_key:
            return "Error: API key not configured. Set DNSDUMPSTER_API_KEY environment variable."
        
        client = DNSDumpsterClient(api_key)
        
        try:
            ctx.info(f"Searching subdomains for {domain} (page {page})")
            result = await client.get_dns_records(domain, page=page)
            
            # Extract subdomains from A records
            subdomains = set()
            
            if "a" in result:
                for record in result["a"]:
                    host = record.get("host", "").lower()
                    if host and host.endswith(domain.lower()) and host != domain.lower():
                        subdomains.add(host)
            
            # Extract subdomains from CNAME records
            if "cname" in result:
                for record in result["cname"]:
                    host = record.get("host", "").lower()
                    if host and host.endswith(domain.lower()) and host != domain.lower():
                        subdomains.add(host)
                    
                    target = record.get("target", "").lower()
                    if target and target.endswith(domain.lower()) and target != domain.lower():
                        subdomains.add(target)
            
            if not subdomains:
                return f"No subdomains found for {domain} on page {page}"
            
            output_lines = [f"Subdomains for {domain} (page {page}):"]
            
            for subdomain in sorted(subdomains):
                output_lines.append(f"\n{subdomain}")
            
            # Add pagination hint
            total_records = result.get("total_a_recs", 0)
            if total_records > 50 and len(subdomains) >= 50:  # Free tier limit
                output_lines.append(f"\n\nShowing {len(subdomains)} subdomains. There may be more results available.")
                output_lines.append(f"To see more results, use page parameter (e.g., page=2)")
            
            return "\n".join(output_lines)
        finally:
            await client.close()
            
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.prompt()
def lookup_domain(domain: str) -> str:
    """Look up DNS information for a domain."""
    return f"""I need comprehensive DNS information about the domain: {domain}

Please analyze:
1. A records and their IP details
2. CNAME records
3. MX records
4. NS records
5. TXT records

Include any interesting details about hosting infrastructure, mail servers, or unusual configurations."""


@mcp.prompt()
def check_dns_security(domain: str) -> str:
    """Check the DNS security configuration of a domain."""
    return f"""I want to analyze the DNS security configuration of {domain}.

Specifically, please check for:
1. SPF records
2. DMARC records
3. DKIM records
4. Other security-related TXT records
5. Any potential DNS misconfigurations or security issues

Please provide an assessment of the domain's DNS security posture."""


def main():
    """Entry point for the MCP server."""
    return mcp.run()


if __name__ == "__main__":
    main()
