from time import time
from operator import itemgetter

class ConsolePrinter:
    def __init__(self, node_info_getter, ui_data):
        self.node_info_getter = node_info_getter
        self.ui_data = ui_data
        self.last_print = None

    @classmethod
    def __print_times(cls, times):
        sorted_times = [(name, total, count, total / count) for name, (total, count) in times.items()]
        sorted_times.sort(key=itemgetter(1), reverse=True)
        for name, tm, count, average in sorted_times:
            print('{:-<45} Total {:->14.2f} Num {:->5} Average {:->14.2f}'.format(name, tm, count, average))

    def __call__(self):
        try:
            current_time = time()
            if self.last_print and (current_time - self.last_print) < 2:
                return
            self.last_print = current_time
            node_info = self.node_info_getter()
            print("================")
            print("Build nodes:")
            print("================")
            for node in node_info:
                print('{:30} - Tasks sent {:<3} '
                    'Completed {:<3} Failed '
                    '{:<3} Running {:<3} Avg. Tasks {:<3.2f} '
                    'Avg. Time {:<3.2f}'
                .format(
                    node.node_dict()['address'],
                    node.tasks_sent       (),
                    node.tasks_completed  (),
                    node.tasks_failed     (),
                    node.tasks_pending    (),
                    node.average_tasks    (),
                    node.average_task_time()))
            print("================")
            for node in node_info:
                times = node.timer().as_dict()
                if not times:
                    continue
                print("Statistics for '{}'".format(node.node_dict()['address']))
                print("================")
                self.__print_times(times)
                print("================")
            if hasattr(self.ui_data, 'timer'):
                print("Global timers")
                print("================")
                self.__print_times(self.ui_data.timer.as_dict())
                print("================")
            if hasattr(self.ui_data, 'cache_stats'):
                hits, misses, ratio = self.ui_data.cache_stats()
                print("Hits: {:8} Misses: {:8} Ratio: {:>.2f}".format(
                    hits, misses, ratio))
                print("================")
        except:
            import traceback
            traceback.print_exc()
