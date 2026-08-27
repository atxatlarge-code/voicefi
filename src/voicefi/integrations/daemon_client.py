"""
Compatibility shim: voicefi.integrations.daemon_client -> voicefi.integrations.server_client.

All server IPC forwarding functions are now unified under voicefi.integrations.server_client.
This module is preserved for backwards compatibility.
"""

from voicefi.integrations import server_client

is_server_running = server_client.is_server_running
is_daemon_running = server_client.is_daemon_running
ensure_server_running = server_client.ensure_server_running
ensure_daemon_running = server_client.ensure_daemon_running
forward_hook_to_server = server_client.forward_hook_to_server
forward_hook_to_daemon = server_client.forward_hook_to_daemon

__all__ = [
    "is_server_running",
    "is_daemon_running",
    "ensure_server_running",
    "ensure_daemon_running",
    "forward_hook_to_server",
    "forward_hook_to_daemon",
]
