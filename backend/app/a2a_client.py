"""Restricted A2A client for War Room research collaboration only.

Endpoints are operator configured, HTTPS only, validated against private-network
targets, and never accepted from browser requests. Responses remain untrusted.
"""
import ipaddress
import json
import socket
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx


MAX_CARD_BYTES = 64_000
MAX_RESPONSE_BYTES = 256_000
MAX_TASK_CHARS = 4_000


def configured_cards(settings) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in settings.warroom_a2a_agent_cards.split(",") if value.strip()))[:20]


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("A2A endpoints must use an HTTPS URL without embedded credentials")
    if parsed.port not in (None, 443) or parsed.query or parsed.fragment:
        raise ValueError("A2A endpoint URL has a disallowed port, query, or fragment")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("A2A endpoint hostname is not public")
    try:
        addresses = {ipaddress.ip_address(host)} if ipaddress.ip_address(host) else set()
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except (OSError, ValueError):
            raise ValueError("A2A endpoint hostname did not resolve") from None
    if not addresses or any(not addr.is_global for addr in addresses):
        raise ValueError("A2A endpoint resolves to a non-public network")
    return urlunsplit(("https", host, parsed.path.rstrip("/"), "", ""))


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"https://{parsed.hostname.lower()}"


async def _bounded_json(client: httpx.AsyncClient, url: str, *, payload: dict | None = None, limit: int):
    response = await (client.post(url, json=payload) if payload is not None else client.get(url))
    response.raise_for_status()
    if len(response.content) > limit:
        raise ValueError("A2A response exceeded the configured size limit")
    return response.json()


async def discover(settings) -> list[dict]:
    urls = configured_cards(settings)
    timeout = httpx.Timeout(settings.a2a_timeout_seconds, connect=min(5, settings.a2a_timeout_seconds))
    results = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False,
                                 headers={"Accept": "application/json", "User-Agent": "Zecto-A2A/1.0"}) as client:
        for configured in urls:
            try:
                base = _safe_url(configured)
                parsed = urlsplit(base)
                card_url = base if parsed.path.endswith(".json") else f"{base}/.well-known/agent-card.json"
                card = await _bounded_json(client, card_url, limit=MAX_CARD_BYTES)
                if not isinstance(card, dict) or not isinstance(card.get("name"), str):
                    raise ValueError("Agent Card is missing a name")
                version = str(card.get("protocolVersion") or "")
                if not version.startswith("1."):
                    raise ValueError("Unsupported A2A protocol version")
                interfaces = card.get("supportedInterfaces")
                endpoint = None
                if isinstance(interfaces, list):
                    for entry in interfaces:
                        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
                            continue
                        candidate = _safe_url(entry["url"])
                        if _origin(candidate) == _origin(base):
                            endpoint = candidate
                            break
                if endpoint is None and isinstance(card.get("url"), str):
                    candidate = _safe_url(card["url"])
                    if _origin(candidate) == _origin(base):
                        endpoint = candidate
                if endpoint is None:
                    raise ValueError("Agent Card has no same-origin HTTPS endpoint")
                raw_skills = card.get("skills") if isinstance(card.get("skills"), list) else []
                skills = []
                for skill in raw_skills[:20]:
                    if not isinstance(skill, dict) or not isinstance(skill.get("name"), str):
                        continue
                    skills.append({
                        "id": str(skill.get("id") or "")[:80],
                        "name": skill["name"][:120],
                        "description": str(skill.get("description") or "")[:400],
                    })
                results.append({"configured_url": base, "name": card["name"][:120],
                                "description": str(card.get("description") or "")[:500],
                                "skills": skills,
                                "protocol_version": version or "unspecified", "endpoint": endpoint,
                                "status": "available"})
            except (ValueError, httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as exc:
                results.append({"configured_url": configured[:300], "status": "unavailable",
                                "reason": type(exc).__name__})
    return results


async def delegate(settings, agent: dict, prompt: str) -> dict:
    """Send a bounded user-role research message; never includes portfolio or trading state."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_TASK_CHARS:
        raise ValueError("Research prompt must be between 1 and 4000 characters")
    if agent.get("status") != "available" or not isinstance(agent.get("endpoint"), str):
        raise ValueError("A2A agent is unavailable")
    endpoint = _safe_url(agent["endpoint"])
    if _origin(endpoint) != _origin(agent["configured_url"]):
        raise ValueError("A2A endpoint origin does not match the configured Agent Card")
    body = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "SendMessage", "params": {
        "message": {"messageId": str(uuid4()), "role": "user", "parts": [{"text": prompt.strip()}]}
    }}
    timeout = httpx.Timeout(settings.a2a_timeout_seconds, connect=min(5, settings.a2a_timeout_seconds))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False,
                                 headers={"Accept": "application/json", "User-Agent": "Zecto-A2A/1.0"}) as client:
        result = await _bounded_json(client, endpoint, payload=body, limit=MAX_RESPONSE_BYTES)
    if not isinstance(result, dict) or result.get("jsonrpc") != "2.0" or result.get("id") != body["id"]:
        raise ValueError("A2A response failed JSON-RPC validation")
    if result.get("error") is not None:
        raise ValueError("External A2A agent returned an error")
    response = result.get("result")
    if not isinstance(response, dict):
        raise ValueError("A2A response did not contain a result")
    # Only bounded textual output is returned; it is explicitly untrusted to the caller.
    text_parts = []
    message_parts = response.get("parts") if isinstance(response.get("parts"), list) else []
    artifacts = response.get("artifacts") if isinstance(response.get("artifacts"), list) else []
    for artifact in artifacts[:20]:
        if isinstance(artifact, dict) and isinstance(artifact.get("parts"), list):
            message_parts = [*message_parts, *artifact["parts"][:20]]
    for part in message_parts[:40]:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            text_parts.append(part["text"][:4_000])
    task_status = response.get("status")
    status = task_status.get("state") if isinstance(task_status, dict) else task_status
    return {"agent_name": str(agent.get("name") or "External agent")[:120],
            "task_id": str(response.get("id") or response.get("taskId") or "")[:160],
            "status": str(status or "received")[:40],
            "text": "\n".join(text_parts)[:20_000], "untrusted": True}
