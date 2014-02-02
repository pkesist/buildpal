from .task_processor import TaskProcessor
from .gui import DBManagerApp
from .node_info import NodeInfo

__all__ = ['TaskProcessor', 'NodeInfo', 'run_gui']

def run_gui(node_info, port):
    app = DBManagerApp(node_info, port)
    app.title('DistriBuild Manager Console')
    app.mainloop()
