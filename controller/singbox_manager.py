"""
Sing-box configuration manager.

Generates Sing-box JSON configuration files for active routes,
manages the Sing-box process lifecycle (start/stop/reload),
and provides config templates for VLESS + Reality + QUIC/TCP.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("asn.controller.singbox")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SINGBOX_BINARY = os.getenv("SINGBOX_BINARY", "sing-box")
DEFAULT_CONFIG_DIR = os.getenv("SINGBOX_CONFIG_DIR", "/tmp/asn_singbox")


class SingboxManager:
    """
    Manages Sing-box process and configuration generation.

    Attributes:
        binary:      Path to the sing-box binary.
        config_dir:  Directory for generated configuration files.
        process:     Running Sing-box subprocess (if active).
    """

    def __init__(
        self,
        binary: str = DEFAULT_SINGBOX_BINARY,
        config_dir: str = DEFAULT_CONFIG_DIR,
    ) -> None:
        """
        Initialize Sing-box manager.

        Args:
            binary:     Path to the sing-box executable.
            config_dir: Directory where configs will be written.
        """
        self.binary = binary
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.process: Optional[subprocess.Popen] = None
        self._current_config_path: Optional[Path] = None

    def generate_outbound(
        self,
        tag: str,
        server: str,
        port: int,
        protocol: str = "vless",
        transport: str = "quic",
        uuid: str = "",
        tls_enabled: bool = True,
        reality_public_key: str = "",
        reality_short_id: str = "",
        server_name: str = "",
    ) -> dict[str, Any]:
        """
        Generate a single Sing-box outbound configuration block.

        Supports VLESS with Reality TLS and QUIC/TCP transport.

        Args:
            tag:                 Outbound tag name.
            server:              Server IP or hostname.
            port:                Server port.
            protocol:            Protocol type (vless, shadowsocks).
            transport:           Transport type (quic, tcp).
            uuid:                User UUID for VLESS.
            tls_enabled:         Enable TLS.
            reality_public_key:  Reality public key.
            reality_short_id:    Reality short ID.
            server_name:         TLS SNI server name.

        Returns:
            Dict representing a Sing-box outbound entry.
        """
        outbound: dict[str, Any] = {
            "type": protocol,
            "tag": tag,
            "server": server,
            "server_port": port,
        }

        if protocol == "vless":
            outbound["uuid"] = uuid or "00000000-0000-0000-0000-000000000000"
            outbound["flow"] = "xtls-rprx-vision"

        if tls_enabled:
            tls_config: dict[str, Any] = {
                "enabled": True,
                "server_name": server_name or server,
                "utls": {"enabled": True, "fingerprint": "chrome"},
            }
            if reality_public_key:
                tls_config["reality"] = {
                    "enabled": True,
                    "public_key": reality_public_key,
                    "short_id": reality_short_id,
                }
            outbound["tls"] = tls_config

        if transport == "quic":
            outbound["transport"] = {"type": "quic"}
        elif transport != "tcp":
            # Websocket, gRPC, etc.
            outbound["transport"] = {"type": transport}

        return outbound

    def generate_config(
        self,
        route: dict,
        listen_port: int = 10808,
        dns_servers: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Generate a full Sing-box configuration for a route.

        Creates inbound SOCKS proxy, outbound chain through the
        route's nodes, and DNS configuration.

        Args:
            route:       Route dict with ``entry``, ``relay`` (optional),
                         ``exit`` node details.
            listen_port: Local SOCKS proxy port.
            dns_servers: Custom DNS servers.

        Returns:
            Complete Sing-box configuration dict.
        """
        if dns_servers is None:
            dns_servers = ["https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"]

        config: dict[str, Any] = {
            "log": {"level": "info", "timestamp": True},
            "dns": {
                "servers": [
                    {"tag": "dns-remote", "address": dns_servers[0], "detour": "proxy-out"},
                    {"tag": "dns-direct", "address": "local"},
                ],
                "rules": [{"outbound": "any", "server": "dns-direct"}],
            },
            "inbounds": [
                {
                    "type": "socks",
                    "tag": "socks-in",
                    "listen": "127.0.0.1",
                    "listen_port": listen_port,
                },
                {
                    "type": "http",
                    "tag": "http-in",
                    "listen": "127.0.0.1",
                    "listen_port": listen_port + 1,
                },
            ],
            "outbounds": [],
            "route": {
                "rules": [],
                "final": "proxy-out",
                "auto_detect_interface": True,
            },
        }

        outbounds = []

        # Build the outbound chain
        entry = route.get("entry")
        relay = route.get("relay")
        exit_node = route.get("exit")

        if entry:
            outbounds.append(
                self.generate_outbound(
                    tag="entry-out",
                    server=entry.get("ip", ""),
                    port=entry.get("port", 443),
                    protocol=entry.get("protocol", "vless"),
                    transport=entry.get("transport", "quic"),
                    uuid=entry.get("uuid", ""),
                    server_name=entry.get("server_name", ""),
                )
            )

        if relay:
            outbounds.append(
                self.generate_outbound(
                    tag="relay-out",
                    server=relay.get("ip", ""),
                    port=relay.get("port", 443),
                    protocol=relay.get("protocol", "vless"),
                    transport=relay.get("transport", "quic"),
                    uuid=relay.get("uuid", ""),
                    server_name=relay.get("server_name", ""),
                )
            )

        if exit_node:
            outbounds.append(
                self.generate_outbound(
                    tag="exit-out",
                    server=exit_node.get("ip", ""),
                    port=exit_node.get("port", 443),
                    protocol=exit_node.get("protocol", "vless"),
                    transport=exit_node.get("transport", "quic"),
                    uuid=exit_node.get("uuid", ""),
                    server_name=exit_node.get("server_name", ""),
                )
            )

        # If we have a chain, use the last outbound as proxy-out
        if outbounds:
            # The final hop is the proxy-out
            outbounds[-1]["tag"] = "proxy-out"
            # If chaining, configure detour
            if len(outbounds) > 1:
                for i in range(len(outbounds) - 1):
                    outbounds[i]["detour"] = outbounds[i + 1]["tag"]
                outbounds[0]["tag"] = "proxy-out"

        # Always add direct outbound
        outbounds.append({"type": "direct", "tag": "direct-out"})
        outbounds.append({"type": "block", "tag": "block-out"})

        config["outbounds"] = outbounds

        return config

    def write_config(
        self,
        config: dict[str, Any],
        filename: str = "config.json",
    ) -> Path:
        """
        Write a Sing-box configuration to disk.

        Args:
            config:   Configuration dict.
            filename: Output filename.

        Returns:
            Path to the written config file.
        """
        config_path = self.config_dir / filename
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        logger.info("Config written to %s", config_path)
        return config_path

    def apply_config(self, config_path: Optional[Path] = None) -> bool:
        """
        Start or restart Sing-box with the given configuration.

        If Sing-box is already running, it is stopped first.

        Args:
            config_path: Path to the config file. Uses last written if None.

        Returns:
            True if Sing-box started successfully.
        """
        path = config_path or self._current_config_path
        if path is None:
            logger.error("No config path specified")
            return False

        # Stop existing process
        self.stop()

        try:
            self.process = subprocess.Popen(
                [self.binary, "run", "-c", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._current_config_path = path
            pid = self.process.pid if self.process else -1
            logger.info(
                "✅ Sing-box started (PID=%d) with config %s",
                pid, path,
            )
            return True
        except FileNotFoundError:
            logger.error(
                "❌ Sing-box binary not found: %s. "
                "Install sing-box or set SINGBOX_BINARY env var.",
                self.binary,
            )
            return False
        except Exception as exc:
            logger.error("Failed to start Sing-box: %s", exc)
            return False

    def stop(self) -> None:
        """Stop the running Sing-box process."""
        proc = self.process
        if proc is not None and proc.poll() is None:
            logger.info("Stopping Sing-box (PID=%d)", proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            self.process = None

    def get_status(self) -> dict:
        """
        Get the current status of the Sing-box process.

        Returns:
            Dict with ``running``, ``pid``, and ``config_path`` keys.
        """
        proc = self.process
        running = proc is not None and proc.poll() is None
        return {
            "running": running,
            "pid": proc.pid if proc is not None and running else None,
            "config_path": str(self._current_config_path) if self._current_config_path else None,
        }

    def reload_config(self) -> bool:
        """
        Send SIGHUP to Sing-box to reload configuration.

        Returns:
            True if signal was sent successfully.
        """
        proc = self.process
        if proc is not None and proc.poll() is None:
            try:
                os.kill(proc.pid, signal.SIGHUP)
                logger.info("Sent SIGHUP to Sing-box (PID=%d)", proc.pid)
                return True
            except OSError as exc:
                logger.error("Failed to reload: %s", exc)
        return False
