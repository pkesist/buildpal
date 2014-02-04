from time import time
from operator import itemgetter

class ConsolePrinter:
    def __init__(self, node_info, ui_data):
        self.node_info = node_info
        self.ui_data = ui_data
        self.last_print = None

    def __call__(self):
        current_time = time()
        if self.last_print and (current_time - self.last_print) < 2:
            return
        self.last_print = current_time
        print("================")
        print("Build nodes:")
        print("================")
        for index in range(len(self.node_info)):
            node = self.node_info[index]
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
        def print_times(times):
            sorted_times = [(name, total, count, total / count) for name, (total, count) in times.items()]
            sorted_times.sort(key=itemgetter(1), reverse=True)
            for name, tm, count, average in sorted_times:
                print('{:-<30} Total {:->14.2f} Num {:->5} Average {:->14.2f}'.format(name, tm, count, average))
        print_times(self.ui_data.timer.as_dict())
        print("================")
        print("Hits: {:8} Misses: {:8} Ratio: {:>.2f}".format(
            self.ui_data.cache_stats.hits, self.ui_data.cache_stats.misses,
            self.ui_data.cache_stats.ratio))
        print("================")
        for index in range(len(self.node_info)):
            node = self.node_info[index]
            times = node.timer().as_dict()
            if not times:
                continue
            print("================")
            print("Statistics for '{}'".format(node.node_dict()['address']))
            print("================")
            print_times(times)
            print("================")
            print("Server time difference - {}".format(times.get('server_time', (0, 0))[0] - times.get('server.server_time', (0, 0))[0]))
            total = 0
            for x in (
                'wait_for_header_list',
                'process_hdr_list',
                'wait_for_headers',
                'shared_prepare_dir',
                'async_compiler_delay',
                'compiler_prep',
                'compiler',):
                total += times.get('server.' + x, (0,0))[0]
            print("Discrepancy - {}".format(times.get('server_time', (0, 0))[0] - total))
