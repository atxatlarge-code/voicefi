"""
Compatibility shim: voicefi.daemon -> voicefi.server.

All daemon management functions and constants are now unified under voicefi.server.
This module is preserved for backwards compatibility.
"""

from voicefi.server import (
    LAUNCHAGENT_LABEL,
    LAUNCHAGENT_PLIST,
    LOCK_FILE,
    PID_FILE,
    get_current_uid,
    is_pid_running,
    get_process_info_by_pid,
    find_running_voicefi_processes,
    get_port_listener,
    get_launchagent_status,
    get_full_server_status,
    get_full_daemon_status,
    stop_all_voicefi_servers,
    stop_all_voicefi_daemons,
    clean_lock_files,
    clean_caches,
    link_dev_environment,
)

__all__ = [
    "LAUNCHAGENT_LABEL",
    "LAUNCHAGENT_PLIST",
    "LOCK_FILE",
    "PID_FILE",
    "get_current_uid",
    "is_pid_running",
    "get_process_info_by_pid",
    "find_running_voicefi_processes",
    "get_port_listener",
    "get_launchagent_status",
    "get_full_server_status",
    "get_full_daemon_status",
    "stop_all_voicefi_servers",
    "stop_all_voicefi_daemons",
    "clean_lock_files",
    "clean_caches",
    "link_dev_environment",
]
