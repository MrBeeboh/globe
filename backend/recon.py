"""Lightweight network recon helpers (DNS, HTTP headers, common port probe)."""
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

UA = {"User-Agent": "globe-monitor/1.0 (personal research tool)"}
TIMEOUT = httpx.Timeout(8.0)
COMMON_PORTS = [80, 443, 22, 8080, 8443]
PROBE_TIMEOUT = 2.0


def _clean_host(host: str) -> str:
    h = host.strip().lower()
    for prefix in ("https://", "http://"):
        if h.startswith(prefix):
            h = h[len(prefix):]
    return h.split("/")[0].split(":")[0]


def dns_lookup(host: str) -> dict:
    host = _clean_host(host)
    if not host:
        return {"error": "empty host"}
    records = []
    try:
        for family, _, _, _, addr in socket.getaddrinfo(host, None):
            fam = "A" if family == socket.AF_INET else "AAAA" if family == socket.AF_INET6 else str(family)
            records.append({"type": fam, "value": addr[0]})
    except socket.gaierror as e:
        return {"host": host, "error": str(e), "records": []}
    # dedupe
    seen = set()
    uniq = []
    for r in records:
        k = (r["type"], r["value"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return {"host": host, "records": uniq}


def http_headers(host: str) -> dict:
    host = _clean_host(host)
    if not host:
        return {"error": "empty host"}
    url = f"https://{host}/"
    try:
        with httpx.Client(timeout=TIMEOUT, headers=UA, follow_redirects=True) as client:
            r = client.head(url)
            headers = {k: v for k, v in r.headers.items()}
            return {
                "host": host,
                "url": str(r.url),
                "status": r.status_code,
                "headers": headers,
            }
    except Exception as e:
        try:
            with httpx.Client(timeout=TIMEOUT, headers=UA, follow_redirects=True) as client:
                r = client.get(f"http://{host}/")
                headers = {k: v for k, v in r.headers.items()}
                return {
                    "host": host,
                    "url": str(r.url),
                    "status": r.status_code,
                    "headers": headers,
                    "note": f"HTTPS failed ({e}); used HTTP",
                }
        except Exception as e2:
            return {"host": host, "error": str(e2)}


def _probe_port(host: str, port: int) -> dict:
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
            return {"port": port, "open": True}
    except Exception:
        return {"port": port, "open": False}


def port_scan(host: str, ports: list[int] | None = None) -> dict:
    host = _clean_host(host)
    if not host:
        return {"error": "empty host"}
    targets = ports or COMMON_PORTS
    results = []
    with ThreadPoolExecutor(max_workers=min(len(targets), 6)) as pool:
        futs = {pool.submit(_probe_port, host, p): p for p in targets}
        for fut in as_completed(futs):
            results.append(fut.result())
    results.sort(key=lambda x: x["port"])
    open_ports = [r["port"] for r in results if r["open"]]
    return {"host": host, "ports": results, "open": open_ports}


def run_recon(host: str, action: str) -> dict:
    action = (action or "dns").lower()
    if action == "dns":
        return dns_lookup(host)
    if action in ("headers", "http"):
        return http_headers(host)
    if action in ("ports", "scan"):
        return port_scan(host)
    if action == "all":
        return {
            "dns": dns_lookup(host),
            "headers": http_headers(host),
            "ports": port_scan(host),
        }
    return {"error": f"unknown action: {action}"}