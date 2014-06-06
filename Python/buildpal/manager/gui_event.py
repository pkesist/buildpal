from enum import Enum

class GUIEvent(Enum):
    update_node_info = 1
    update_global_timers = 2
    update_cache_stats = 3
    update_command_info = 4
    update_unassigned_tasks = 5
    exception_in_run = 6
