# !python3.3
from tkinter import *
import tkinter.font as font
from tkinter.ttk import *

import threading

from operator import itemgetter

from . import TaskProcessor

class MyTreeView(Treeview):
    def __init__(self, parent):
        Treeview.__init__(self, parent,
            columns=tuple(c['cid'] for c in self.columns[1:]))
        heading_font = font.nametofont('TkHeadingFont')
        for c in self.columns:
            self.column(c['cid'], width=max(heading_font.measure(c['text']) + 15, c['minwidth']), minwidth=c['minwidth'], anchor=c['anchor'])
            self.heading(c['cid'], text=c['text'])


class NodeList(MyTreeView):
    columns = (
        {'cid' : "#0"       , 'text' : "Address"      , 'minwidth' : 100, 'anchor' : W  },
        {'cid' : "MaxTasks" , 'text' : "Max Tasks"    , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "TasksSent", 'text' : "Tasks Sent"   , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Completed", 'text' : "Completed"    , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Failed"   , 'text' : "Failed"       , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Running"  , 'text' : "Running"      , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "AvgTasks" , 'text' : "Average Tasks", 'minwidth' : 40 , 'anchor' : CENTER},
        {'cid' : "AvgTime"  , 'text' : "Average Time" , 'minwidth' : 40 , 'anchor' : CENTER})

    def __init__(self, parent, node_info):
        MyTreeView.__init__(self, parent)
        self.node_info = node_info
        for node in self.node_info:
            text = node.node_dict()['address']
            self.insert('', 'end', text=node.node_dict()['address'],
                values=(node.node_dict()['max_tasks'],))

        self.refresh()

    def refresh(self):
        items = self.get_children('')
        assert len(items) == len(self.node_info)
        for node, item in zip(self.node_info, items):
            # Make sure the order did not change somehow.
            assert self.item(item)['text'] == node.node_dict()['address']
            values = (
                node.node_dict()['max_tasks'], 
                node.tasks_sent       (),
                node.tasks_completed  (),
                node.tasks_failed     (),
                node.tasks_processing (),
                "{:.2f}".format(node.average_tasks()),
                "{:.2f}".format(node.average_task_time()))
            self.item(item, values=values)


class NodeTimes(MyTreeView):
    columns = (
        { 'cid' : '#0'       , 'text' : 'Timer Name'  , 'minwidth' : 100, 'anchor' : W      },
        { 'cid' : 'TotalTime', 'text' : 'Total Time'  , 'minwidth' : 30 , 'anchor' : CENTER },
        { 'cid' : 'Count'    , 'text' : 'Count'       , 'minwidth' : 20 , 'anchor' : CENTER },
        { 'cid' : 'AvgTime'  , 'text' : 'Average Time', 'minwidth' : 30 , 'anchor' : CENTER })

    def update(self, timer_dict):
        self.delete(*self.get_children(''))
        sorted_times = [(name, total, count, total / count) for name, (total, count) in timer_dict.items()]
        sorted_times.sort(key=itemgetter(1), reverse=True)
        for timer_name, total, count, average in sorted_times:
            values = (
                "{:.2f}".format(total),
                count,
                "{:.2f}".format(average))
            self.insert('', 'end', text=timer_name, values=values)

class NodeDisplay(Frame):
    def __init__(self, parent, node_info):
        Frame.__init__(self)
        self.node_info = node_info
        self.node_index = None
        self.draw()

    def draw(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.paned_window = PanedWindow(self, orient=VERTICAL)

        self.node_list = NodeList(self.paned_window, self.node_info)
        self.paned_window.add(self.node_list)
        self.node_list.bind('<<TreeviewSelect>>', self.node_selected)
        
        self.node_times = NodeTimes(self.paned_window)
        self.paned_window.add(self.node_times)

        self.paned_window.grid(row=0, column=0, sticky=N+S+W+E)

    def node_selected(self, event):
        selection = self.node_list.selection()
        if not selection:
            self.node_index = None
        else:
            self.node_index = self.node_list.index(self.node_list.selection()[0])
        self.refresh()

    def refresh(self):
        self.node_list.refresh()
        if self.node_index is None:
            timer_dict = {}
        else:
            timer_dict = self.node_info[self.node_index].timer().as_dict()
        self.rowconfigure(1, weight=len(timer_dict))
        self.node_times.update(timer_dict)

def called_from_foreign_thread(func):
    return func

class DBManagerApp(Tk):
    state_stopped = 0
    state_started = 1

    def __init__(self, node_info, port):
        Tk.__init__(self, None)
        self.port = port
        self.node_info = node_info
        self.state = self.state_stopped
        self.initialize()
        self.refresh_event = threading.Event()
        self.refresh_event.clear()
        self.__periodic_refresh()

    def __periodic_refresh(self):
        if self.refresh_event.is_set():
            self.refresh()
            self.refresh_event.clear()
        self.after(100, self.__periodic_refresh)

    def initialize(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(4, weight=1)

        self.port_frame = Frame(self)
        self.port_frame.grid(row=0, column=0, columnspan=5, sticky=E+W)
        self.port_label = Label(self.port_frame, text="Port")
        self.port_label.grid(row=0, column=0)
        self.port_sb = Spinbox(self.port_frame, from_=1024, to=65536, increment=1)
        self.port_sb.delete(0, "end")
        self.port_sb.insert(0, self.port)
        self.port_sb.grid(row=0, column=1)

        self.rowconfigure(1, weight=1)
        self.node_display = NodeDisplay(self, self.node_info)
        self.node_display.grid(row=1, column=0, columnspan=5, sticky=N+S+W+E)
        self.start_but = Button(self, text="Start", command=self.start)
        self.start_but.grid(row=2, column=1, sticky=E+W)
        self.stop_but = Button(self, text="Stop", command=self.stop, state=DISABLED)
        self.stop_but.grid(row=2, column=2, sticky=E+W)
        self.exit = Button(self, text="Exit", command=self.destroy)
        self.exit.grid(row=2, column=3, sticky=E+W)

    @called_from_foreign_thread
    def signal_refresh(self):
        self.refresh_event.set()

    def refresh(self):
        self.node_display.refresh()

    def update_state(self, state):
        self.state = state
        self.stop_but['state'] = 'enable' if self.state == self.state_started else 'disable'
        self.start_but['state'] = 'enable' if self.state == self.state_stopped else 'disable'
        self.port_sb['state'] = 'normal' if self.state == self.state_stopped else 'disable'

    def destroy(self):
        if self.state == self.state_started:
            self.stop()
        Tk.destroy(self)

    def start(self):
        if self.state != self.state_stopped:
            return
        self.task_processor = TaskProcessor(self.node_info, self.port_sb.get())
        self.thread = threading.Thread(target=self.__run_task_processor)
        self.thread.start()
        self.update_state(self.state_started)

    def __run_task_processor(self):
        self.task_processor.run(self.signal_refresh)

    def stop(self):
        if self.state != self.state_started:
            return
        self.task_processor.stop()
        self.thread.join()
        self.update_state(self.state_stopped)
