# !python3.3
from tkinter import *
import tkinter.font as font
from tkinter.ttk import *

import threading

from operator import itemgetter

from . import TaskProcessor

class MyTreeView(Treeview):
    def __init__(self, parent, columns, **kwargs):
        Treeview.__init__(self, parent,
            columns=tuple(c['cid'] for c in columns[1:]), **kwargs)
        heading_font = font.nametofont('TkHeadingFont')
        for c in columns:
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

    def __init__(self, parent, node_info, **kwargs):
        MyTreeView.__init__(self, parent, self.columns, **kwargs)
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


class TimerDisplay(MyTreeView):
    columns = (
        { 'cid' : '#0'       , 'text' : 'Timer Name'  , 'minwidth' : 100, 'anchor' : W      },
        { 'cid' : 'TotalTime', 'text' : 'Total Time'  , 'minwidth' : 30 , 'anchor' : CENTER },
        { 'cid' : 'Count'    , 'text' : 'Count'       , 'minwidth' : 20 , 'anchor' : CENTER },
        { 'cid' : 'AvgTime'  , 'text' : 'Average Time', 'minwidth' : 30 , 'anchor' : CENTER })

    def __init__(self, parent, **kwargs):
        return MyTreeView.__init__(self, parent, self.columns, **kwargs)

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
        self.label_frame = LabelFrame(self, text="Node Information")
        self.label_frame.columnconfigure(0, weight=1)
        self.label_frame.rowconfigure(0, weight=1)
        self.paned_window = PanedWindow(self.label_frame, orient=VERTICAL)

        self.node_list = NodeList(self.paned_window, self.node_info, height=6)
        self.node_list.bind('<<TreeviewSelect>>', self.node_selected)
        self.paned_window.add(self.node_list)
        
        self.node_times = TimerDisplay(self.paned_window, height=6)
        self.paned_window.add(self.node_times)

        self.paned_window.grid(row=0, column=0, sticky=N+S+W+E)
        self.label_frame.grid(row=0, column=0, sticky=N+S+W+E, padx=5, pady=5)

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
            node_time_dict = {}
        else:
            node_time_dict = self.node_info[self.node_index].timer().as_dict()
        self.node_times.update(node_time_dict)

def called_from_foreign_thread(func):
    return func

class DBManagerApp(Tk):
    state_stopped = 0
    state_started = 1

    def __init__(self, node_info, timer, port):
        Tk.__init__(self, None)
        self.node_info = node_info
        self.timer = timer
        self.port = port
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

        # Row 0
        self.settings_frame = LabelFrame(self, text="Settings")
        self.settings_frame.grid(row=0, column=0, columnspan=5, sticky=E+W, padx=5, pady=(0, 5))
        self.port_label = Label(self.settings_frame, text="Port")
        self.port_label.grid(row=0, column=0, padx=(5, 20))
        self.port_sb = Spinbox(self.settings_frame, from_=1024, to=65536, increment=1)
        self.port_sb.delete(0, "end")
        self.port_sb.insert(0, self.port)
        self.port_sb.grid(row=0, column=1)

        self.start_but = Button(self.settings_frame, text="Start", command=self.start)
        self.start_but.grid(row=0, column=2, sticky=E+W)
        self.stop_but = Button(self.settings_frame, text="Stop", command=self.stop, state=DISABLED)
        self.stop_but.grid(row=0, column=3, sticky=E+W)

        # Row 1
        self.pane = PanedWindow(self, orient=VERTICAL)
        self.global_data_frame = LabelFrame(self.pane, text="Global Data")
        self.global_times = TimerDisplay(self.global_data_frame, height=5)
        self.global_data_frame.rowconfigure(0, weight=1)
        self.global_data_frame.columnconfigure(0, weight=1)
        self.global_times.grid(row=0, column=0, sticky=N+S+W+E)

        self.cache_frame = LabelFrame(self.global_data_frame, text="Cache Statistics")
        self.cache_hits_label = Label(self.cache_frame, text="Hits")
        self.cache_hits_label.grid(row=0, sticky=W)
        self.cache_hits_text = Entry(self.cache_frame, state=DISABLED)
        self.cache_hits_text.grid(row=0, column=1)
        self.cache_misses_label = Label(self.cache_frame, text="Misses")
        self.cache_misses_label.grid(row=1, sticky=W)
        self.cache_misses_text = Entry(self.cache_frame, state=DISABLED)
        self.cache_misses_text.grid(row=1, column=1)
        self.cache_separator = Separator(self.cache_frame)
        self.cache_separator.grid(row=2, column=0, columnspan=2, pady=5, sticky=E+W)
        self.cache_ratio_label = Label(self.cache_frame, text="Ratio")
        self.cache_ratio_label.grid(row=3, sticky=W)
        self.cache_ratio_text = Entry(self.cache_frame, state=DISABLED)
        self.cache_ratio_text.grid(row=3, column=1)
        self.cache_frame.grid(row=0, column=1, sticky=N+S+W+E)


        self.global_data_frame.grid(row=1, column=0, columnspan=5, sticky=N+S+W+E)
        self.pane.add(self.global_data_frame)
        self.node_display = NodeDisplay(self.pane, self.node_info)
        self.node_display.grid(row=2, column=0, columnspan=5, sticky=N+S+W+E)
        self.pane.add(self.node_display)
        self.rowconfigure(1, weight=1)
        self.pane.grid(row=1, column=0, columnspan=5, sticky=N+S+W+E)

        # Row 3
        self.sizegrip = Sizegrip(self)
        self.sizegrip.grid(row=3, column=0, columnspan=5, sticky=S+E)


    @called_from_foreign_thread
    def signal_refresh(self):
        self.refresh_event.set()

    def refresh(self):
        self.global_times.update(self.timer.as_dict())
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
        self.task_processor = TaskProcessor(self.node_info, self.timer,
            self.port_sb.get())
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
