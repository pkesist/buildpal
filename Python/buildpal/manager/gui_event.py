from enum import Enum

class GUIEvent(Enum):
    update_node_info = 1
    update_global_timers = 2
    update_cache_stats = 3
    update_preprocessed_count = 4
    update_command_info = 5
    update_unassigned_tasks = 6
    exception_in_run = 7
