from .task_processor import TaskProcessor
from .gui import BPManagerApp

__all__ = ['TaskProcessor', 'run_gui']

def run_gui(nodes, port):
    app = BPManagerApp(nodes, port)
    app.title('BuildPal Manager Console')
    app.mainloop()
