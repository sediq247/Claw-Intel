#!/usr/bin/env python3
"""
🧰 utils/helpers.py
The Utility Toolbox.
Shared helper functions for string normalization, timestamp conversion,
address validation, currency formatting, and large number display;
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union
import hashlib


def normalize_symbol(symbol: str) -> str:
    """
    Standardize token symbol for consistent display.
    Uppercase, strip whitespace, remove special chars EXCEPT dots.
    Preserves dots for wrapped tokens like USDC.e
    """
    if not symbol:
        return "???"
    cleaned = re.sub(r'[^a-zA-Z0-9.]', '', symbol.strip())
    return cleaned.upper()[:12] if cleaned else "???"


def normalize_name(name: str) -> str:
    """
    Clean token name for display.
    Strip whitespace, limit length, remove control chars.
    """
    if not name:
        return "Unknown Token"
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', name.strip())
    return cleaned[:50] if cleaned else "Unknown Token"


def truncate_address(address: str, prefix: int = 6, suffix: int = 4) -> str:
    """
    Truncate blockchain address for display.
    0x1234...5678
    """
    if not address or len(address) <= prefix + suffix + 3:
        return address or "unknown"
    return f"{address[:prefix]}...{address[-suffix:]}"


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text with ellipsis."""
    if not text or len(text) <= max_length:
        return text or ""
    return text[:max_length - 3] + "..."


# ═══════════════════════════════════════════════════
# TIMESTAMP CONVERSION
# ═══════════════════════════════════════════════════

def unix_to_human(timestamp: Union[int, float]) -> str:
    """
    Convert Unix timestamp to human-readable string.
    Returns: "2 min ago", "1 hour ago", "May 2, 09:30"
    """
    if not timestamp:
        return "unknown"

    now = datetime.now(timezone.utc)
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    diff = now - dt

    seconds = int(diff.total_seconds())

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        mins = seconds // 60
        return f"{mins} min{'s' if mins > 1 else ''} ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif seconds < 604800:
        days = seconds // 86400
        return f"{days} day{'s' if days > 1 else ''} ago"
    else:
        return dt.strftime("%b %d, %H:%M")


def unix_to_datetime(timestamp: Union[int, float]) -> str:
    """Convert Unix timestamp to ISO datetime string."""
    if not timestamp:
        return ""
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_duration(seconds: Union[int, float]) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    elif seconds < 86400:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"
    else:
        return f"{int(seconds // 86400)}d {int((seconds % 86400) // 3600)}h"


# ═══════════════════════════════════════════════════
# ADDRESS VALIDATION
# ═══════════════════════════════════════════════════

def is_valid_evm_address(address: str) -> bool:
    """
    Validate Ethereum/BSC/Base address format.
    Must be 42 chars, start with 0x, followed by 40 hex chars.
    """
    if not address or not isinstance(address, str):
        return False
    return bool(re.match(r'^0x[a-fA-F0-9]{40}$', address))


def is_valid_solana_address(address: str) -> bool:
    """
    Validate Solana address format.
    Base58 encoded, 32-44 characters.
    """
    if not address or not isinstance(address, str):
        return False
    if len(address) < 32 or len(address) > 44:
        return False
    base58_chars = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')
    return set(address).issubset(base58_chars)


def validate_address(address: str, chain: str) -> bool:
    """
    Validate address for specific chain.
    """
    chain = chain.lower()
    if chain in ['ethereum', 'eth', 'bsc', 'binance', 'base', 'mantle']:
        return is_valid_evm_address(address)
    elif chain in ['solana', 'sol']:
        return is_valid_solana_address(address)
    return False


def checksum_address(address: str) -> str:
    """
    Return EIP-55 checksummed Ethereum address.
    """
    if not is_valid_evm_address(address):
        return address
    try:
        from web3 import Web3
        return Web3.to_checksum_address(address)
    except ImportError:
        return address


# ═══════════════════════════════════════════════════
# NUMBER FORMATTING
# ═══════════════════════════════════════════════════

def format_currency(value: Union[int, float, Decimal, str], 
                     symbol: str = "$", 
                     decimals: int = 2) -> str:
    """
    Format number as currency string.
    $1,234.56  |  $1.2M  |  $450K  |  $0.00042
    """
    if value is None:
        return f"{symbol}0.00"

    try:
        num = Decimal(str(value))
    except:
        return f"{symbol}{value}"

    abs_num = abs(num)

    # Large numbers: use K, M, B, T
    if abs_num >= 1000000000000:
        return f"{symbol}{num / Decimal('1000000000000'):.{decimals}f}T"
    elif abs_num >= 1000000000:
        return f"{symbol}{num / Decimal('1000000000'):.{decimals}f}B"
    elif abs_num >= 1000000:
        return f"{symbol}{num / Decimal('1000000'):.{decimals}f}M"
    elif abs_num >= 1000:
        return f"{symbol}{num / Decimal('1000'):.{decimals}f}K"
    elif abs_num >= 1:
        return f"{symbol}{num:,.{decimals}f}"
    elif abs_num >= 0.01:
        return f"{symbol}{num:.{decimals}f}"
    else:
        # Very small numbers: show more decimals
        return f"{symbol}{num:.6f}"


def format_large_number(value: Union[int, float, Decimal, str]) -> str:
    """
    Format large numbers with K/M/B/T suffixes.
    1234567 -> 1.23M
    """
    if value is None:
        return "0"

    try:
        num = Decimal(str(value))
    except:
        return str(value)

    abs_num = abs(num)

    if abs_num >= 1000000000000:
        return f"{num / Decimal('1000000000000'):.2f}T"
    elif abs_num >= 1000000000:
        return f"{num / Decimal('1000000000000'):.2f}B"
    elif abs_num >= 1000000:
        return f"{num / Decimal('1000000'):.2f}M"
    elif abs_num >= 1000:
        return f"{num / Decimal('1000'):.2f}K"
    else:
        return f"{num:,.0f}"


def format_percentage(value: Union[int, float, Decimal, str], 
                       include_sign: bool = True) -> str:
    """
    Format percentage with color indicator.
    +15.4%  |  -3.2%
    """
    if value is None:
        return "0.00%"

    try:
        num = Decimal(str(value))
    except:
        return f"{value}%"

    sign = "+" if num > 0 and include_sign else ""
    return f"{sign}{num:.2f}%"


def format_price(value: Union[int, float, Decimal, str]) -> str:
    """
    Format token price with appropriate decimals.
    $0.00004215  |  $1.23  |  $45,000.00
    """
    if value is None:
        return "$0.00"

    try:
        num = Decimal(str(value))
    except:
        return f"${value}"

    abs_num = abs(num)

    if abs_num >= 1:
        return f"${num:,.2f}"
    elif abs_num >= 0.01:
        return f"${num:.4f}"
    elif abs_num >= 0.0001:
        return f"${num:.6f}"
    else:
        return f"${num:.8f}"


# ═══════════════════════════════════════════════════
# CHAIN UTILITIES
# ═══════════════════════════════════════════════════

def get_chain_display_name(chain: str) -> str:
    """Get human-readable chain name."""
    chain_map = {
        'bsc': 'BSC',
        'binance': 'BSC',
        'ethereum': 'Ethereum',
        'eth': 'Ethereum',
        'solana': 'Solana',
        'sol': 'Solana',
        'base': 'Base',
        'mantle': 'Mantle',
    }
    return chain_map.get(chain.lower(), chain.upper())


# ═══════════════════════════════════════════════════
# DEXSCREENER / COINGECKO DATA NORMALIZATION
# ═══════════════════════════════════════════════════

def normalize_dexscreener_token(data: dict) -> dict:
    """
    Normalize DexScreener token data to standard format.
    """
    if not data:
        return {}

    return {
        'address': data.get('tokenAddress') or data.get('baseToken', {}).get('address'),
        'symbol': normalize_symbol(data.get('symbol') or data.get('baseToken', {}).get('symbol')),
        'name': normalize_name(data.get('name') or data.get('baseToken', {}).get('name')),
        'chain': data.get('chainId', 'unknown').lower(),
        'price': float(data.get('priceUsd', 0) or 0),
        'liquidity': float(data.get('liquidity', {}).get('usd', 0) or 0),
        'market_cap': float(data.get('marketCap', 0) or data.get('fdv', 0) or 0),
        'volume_24h': float(data.get('volume', {}).get('h24', 0) or 0),
        'price_change_24h': float(data.get('priceChange', {}).get('h24', 0) or 0),
        'dex': data.get('dexId', 'unknown'),
        'pair_address': data.get('pairAddress'),
        'created_at': data.get('pairCreatedAt'),
    }


def normalize_coingecko_token(data: dict) -> dict:
    """
    Normalize CoinGecko token data to standard format.
    """
    if not data:
        return {}

    return {
        'id': data.get('id'),
        'symbol': normalize_symbol(data.get('symbol')),
        'name': normalize_name(data.get('name')),
        'price': float(data.get('current_price', 0) or 0),
        'market_cap': float(data.get('market_cap', 0) or 0),
        'volume_24h': float(data.get('total_volume', 0) or 0),
        'price_change_24h': float(data.get('price_change_percentage_24h', 0) or 0),
        'price_change_7d': float(data.get('price_change_percentage_7d_in_currency', 0) or 0),
        'ath': float(data.get('ath', 0) or 0),
        'ath_change': float(data.get('ath_change_percentage', 0) or 0),
        'image': data.get('image'),
        'last_updated': data.get('last_updated'),
    }


# ═══════════════════════════════════════════════════
# CACHE UTILITIES
# ═══════════════════════════════════════════════════

class SimpleCache:
    """Simple in-memory cache with TTL."""

    def __init__(self, default_ttl: int = 300):
        self.cache = {}
        self.default_ttl = default_ttl

    def get(self, key: str):
        if key not in self.cache:
            return None
        entry = self.cache[key]
        if entry['expires'] < datetime.now(timezone.utc).timestamp():
            del self.cache[key]
            return None
        return entry['value']

    def set(self, key: str, value, ttl: Optional[int] = None):
        ttl = ttl or self.default_ttl
        self.cache[key] = {
            'value': value,
            'expires': datetime.now(timezone.utc).timestamp() + ttl,
        }

    def delete(self, key: str):
        self.cache.pop(key, None)

    def clear(self):
        self.cache.clear()

    def size(self) -> int:
        return len(self.cache)


# Export all utilities
__all__ = [
    # String
    'normalize_symbol', 'normalize_name', 'truncate_address', 'truncate_text',
    # Time
    'unix_to_human', 'unix_to_datetime', 'format_duration',
    # Address
    'is_valid_evm_address', 'is_valid_solana_address', 'validate_address', 'checksum_address',
    # Numbers
    'format_currency', 'format_large_number', 'format_percentage', 'format_price',
    # Chain
    'get_chain_display_name',
    'normalize_dexscreener_token', 'normalize_coingecko_token',
    'SimpleCache',
]
