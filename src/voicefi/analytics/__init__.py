"""
VoiceFi Local Analytics & Developer Observability Package.
Provides local SQLite storage, time-saved calculators, and terminal stats visualizations.
"""

from voicefi.analytics.store import (
    AnalyticsStore,
    get_analytics_store,
    get_default_db_path,
)
from voicefi.analytics.queries import (
    get_analytics_summary,
    get_daily_turn_volume,
    get_tool_usage_breakdown,
    get_agent_distribution,
    calculate_time_saved_hours,
    calculate_time_saved_breakdown,
    get_cognitive_flow_breakdown,
)
from voicefi.analytics.terminal import (
    format_stats_dashboard,
    print_stats_dashboard,
)
from voicefi.analytics.exporter import (
    export_events_json,
    export_events_csv,
    clean_analytics_data,
    reset_analytics_data,
)

__all__ = [
    "AnalyticsStore",
    "get_analytics_store",
    "get_default_db_path",
    "get_analytics_summary",
    "get_daily_turn_volume",
    "get_tool_usage_breakdown",
    "get_agent_distribution",
    "calculate_time_saved_hours",
    "calculate_time_saved_breakdown",
    "get_cognitive_flow_breakdown",
    "format_stats_dashboard",
    "print_stats_dashboard",
    "export_events_json",
    "export_events_csv",
    "clean_analytics_data",
    "reset_analytics_data",
]

