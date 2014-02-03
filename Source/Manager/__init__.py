from .task_processor import TaskProcessor
from .gui import DBManagerApp
from .node_info import NodeInfo
from .timer import Timer

__all__ = ['TaskProcessor', 'NodeInfo', 'run_gui', 'Timer']

def run_gui(node_info, timer, port):
    app = DBManagerApp(node_info, timer, port)
    app.title('DistriBuild Manager Console')
    app.mainloop()
