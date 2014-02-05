# !python3.3
from tkinter import *
import tkinter.font as font
import tkinter.messagebox as msgbox
from tkinter.ttk import *
import zmq

import threading

from operator import itemgetter
from time import time
from multiprocessing import cpu_count

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
        {'cid' : "#0"          , 'text' : "Hostname"     , 'minwidth' : 180, 'anchor' : W     },
        {'cid' : "JobSlots"    , 'text' : "Job Slots"    , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "TasksPending", 'text' : "Tasks Pending", 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Completed"   , 'text' : "Completed"    , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Failed"      , 'text' : "Failed"       , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Running"     , 'text' : "Running"      , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "AvgTasks"    , 'text' : "Average Tasks", 'minwidth' : 40 , 'anchor' : CENTER},
        {'cid' : "AvgTime"     , 'text' : "Average Time" , 'minwidth' : 40 , 'anchor' : CENTER})

    def __init__(self, parent, node_info, ui_data, **kwargs):
        MyTreeView.__init__(self, parent, self.columns, selectmode='browse', **kwargs)
        self.ui_data = ui_data
        for node in node_info:
            text = node.node_dict()['hostname']
            self.insert('', 'end', text=text,
                values=(node.node_dict()['job_slots'],))

    def refresh(self):
        items = self.get_children('')
        if not hasattr(self.ui_data, 'node_info'):
            return
        assert len(items) == len(self.ui_data.node_info)
        for node, item in zip(self.ui_data.node_info, items):
            # Make sure the order did not change somehow.
            assert self.item(item)['text'] == node.node_dict()['hostname']
            values = (
                node.node_dict()['job_slots'], 
                node.tasks_sent     (),
                node.tasks_completed(),
                node.tasks_failed   (),
                node.tasks_pending  (),
                "{:.2f}".format(node.average_tasks()),
                "{:.2f}".format(node.average_task_time()))
            self.item(item, values=values)

class NodeInfoDisplay(Frame):
    def __init__(self, parent, **kw):
        Frame.__init__(self, parent, **kw)
        self.draw()

    def label_and_entry(self, label_text, row, col=0):
        var = StringVar()
        label = Label(self, text=label_text)
        entry = Entry(self, state=DISABLED, foreground='black', textvariable=var)
        label.grid(row=row, column=2 * col + 0, sticky=E+W)
        entry.grid(row=row, column=2 * col + 1)
        return var

    def draw(self):
        self.address = self.label_and_entry("Address", 0)
        self.port = self.label_and_entry("Port", 0, 1)
        self.job_slots = self.label_and_entry("Job Slots", 1)
        self.tasks_pending = self.label_and_entry("Tasks Pending", 1, 1)
        self.tasks_sent = self.label_and_entry("Tasks Sent", 2)
        self.tasks_completed = self.label_and_entry("Tasks Completed", 3)
        self.tasks_failed = self.label_and_entry("Tasks Failed", 3, 1)
        self.average_tasks = self.label_and_entry("Average Tasks", 4)
        self.average_time = self.label_and_entry("Average Time", 4, 1)
        Separator(self).grid(row=5, column=0, columnspan=4, sticky=E+W, pady=5)
        self.ping_button = Button(self, text='PING', state=DISABLED)
        self.ping_button.grid(row=6, column=0)
        self.ping_result = StringVar()
        self.ping_result_entry = Entry(self, textvariable=self.ping_result,
            state=DISABLED, foreground='black')
        self.ping_result_entry.grid(row=6, column=1)

    def refresh(self, node):
        if node is None:
            self.address.set('')
            self.port.set('')
            self.job_slots.set('')
            self.tasks_sent.set('')
            self.tasks_completed.set('')
            self.tasks_failed.set('')
            self.tasks_pending.set('')
            self.average_tasks.set('')
            self.average_time.set('')
            self.ping_button['state'] = 'disabled'
        else:
            self.address.set(node.node_dict()['address'])
            self.port.set(node.node_dict()['port'])
            self.job_slots.set(node.node_dict()['job_slots'])
            self.tasks_sent.set(node.tasks_sent())
            self.tasks_completed.set(node.tasks_completed())
            self.tasks_failed.set(node.tasks_failed())
            self.tasks_pending.set(node.tasks_pending())
            self.average_tasks.set("{:.2f}".format(node.average_tasks()))
            self.average_time.set("{:.2f}".format(node.average_task_time()))
            self.ping_button['state'] = 'enabled'

class TimerDisplay(MyTreeView):
    columns = (
        { 'cid' : '#0'       , 'text' : 'Timer Name'  , 'minwidth' : 100, 'anchor' : W      },
        { 'cid' : 'TotalTime', 'text' : 'Total Time'  , 'minwidth' : 30 , 'anchor' : CENTER },
        { 'cid' : 'Count'    , 'text' : 'Count'       , 'minwidth' : 20 , 'anchor' : CENTER },
        { 'cid' : 'AvgTime'  , 'text' : 'Average Time', 'minwidth' : 30 , 'anchor' : CENTER })

    def __init__(self, parent, **kwargs):
        return MyTreeView.__init__(self, parent, self.columns, **kwargs)

    def refresh(self, timer_dict):
        selection = self.selection()
        self.delete(*self.get_children(''))
        sorted_times = [(name, total, count, total / count) for name, (total, count) in timer_dict.items()]
        sorted_times.sort(key=itemgetter(1), reverse=True)
        for timer_name, total, count, average in sorted_times:
            values = (
                "{:.2f}".format(total),
                count,
                "{:.2f}".format(average))
            self.insert('', 'end', text=timer_name, values=values)
        if selection:
            self.selection_add(selection)

class NodeDisplay(Frame):
    def __init__(self, parent, node_info, ui_data):
        Frame.__init__(self)
        self.node_info = node_info
        self.ui_data = ui_data
        self.node_index = None
        self.draw()
        self.zmq_ctx = zmq.Context()

    def draw(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.label_frame = LabelFrame(self, text="Node Information")
        self.label_frame.columnconfigure(0, weight=1)
        self.label_frame.rowconfigure(0, weight=1)
        self.paned_window = PanedWindow(self.label_frame, orient=VERTICAL)

        self.nodes_pane = PanedWindow(self.paned_window, orient=HORIZONTAL)

        self.node_list = NodeList(self.nodes_pane, self.node_info, self.ui_data, height=6)
        self.node_list.bind('<<TreeviewSelect>>', self.node_selected)
        self.nodes_pane.add(self.node_list, weight=1)

        self.node_info_display = NodeInfoDisplay(self.nodes_pane)
        self.node_info_display.ping_button['command'] = self.ping
        self.nodes_pane.add(self.node_info_display, weight=0)

        self.paned_window.add(self.nodes_pane)

        self.node_times = TimerDisplay(self.paned_window, height=6)
        self.paned_window.add(self.node_times)

        self.paned_window.grid(row=0, column=0, sticky=N+S+W+E)
        self.label_frame.grid(row=0, column=0, sticky=N+S+W+E, padx=5, pady=5)

    def ping(self):
        assert self.node_index is not None
        node = self.node_info[self.node_index]
        s = self.zmq_ctx.socket(zmq.DEALER)
        s.connect(node.zmq_address())
        s.RCVTIMEO = 1000
        times = []
        for x in range(5):
            ping_time = time()
            s.send(b'PING')
            try:
                response = s.recv()
            except zmq.ZMQError:
                self.node_info_display.ping_result.set("FAILURE")
                return
            else:
                times.append(time() - ping_time)

        diff = sum(times) / len(times)
        diff *= 1000
        if diff < 1:
            diff = "<1"
        else:
            diff = round(diff)
        self.node_info_display.ping_result.set("{} ms".format(diff))
        s.close()

    def node_selected(self, event):
        selection = self.node_list.selection()
        if not selection:
            self.node_index = None
        else:
            new_index = self.node_list.index(self.node_list.selection()[0])
            if new_index == self.node_index:
                return
            self.node_index = new_index
        self.node_info_display.ping_result.set('')
        self.refresh()

    def refresh(self):
        self.node_list.refresh()
        if self.node_index is None:
            node = None
            node_time_dict = {}
        else:
            node = self.node_info[self.node_index]
            node_time_dict = node.timer().as_dict()
        self.node_times.refresh(node_time_dict)
        self.node_info_display.refresh(node)

def called_from_foreign_thread(func):
    return func

class CacheStats(LabelFrame):
    def __init__(self, parent, ui_data, **kw):
        LabelFrame.__init__(self, parent, text = "Cache Statistics", **kw)
        self.ui_data = ui_data
        self.draw()
    
    def draw(self):
        self.include_directives = StringVar()
        self.cache_hits = StringVar()
        self.cache_ratio = StringVar()
        Label(self, text="Include Directives").grid(row=0, sticky=W)
        Entry(self, state=DISABLED, textvariable=self.include_directives).grid(row=0, column=1)
        Label(self, text="Cache Hits").grid(row=1, sticky=W)
        Entry(self, state=DISABLED, textvariable=self.cache_hits).grid(row=1, column=1)
        Separator(self).grid(row=2, column=0, columnspan=2, pady=5, sticky=E+W)
        Label(self, text="Hit Ratio").grid(row=3, sticky=W)
        Entry(self, state=DISABLED, textvariable=self.cache_ratio).grid(row=3, column=1)

    def refresh(self):
        self.include_directives.set(self.ui_data.cache_stats.hits + self.ui_data.cache_stats.misses)
        self.cache_hits.set(self.ui_data.cache_stats.hits)
        self.cache_ratio.set("{:.2f}".format(self.ui_data.cache_stats.ratio))

class GlobalDataFrame(LabelFrame):
    def __init__(self, parent, ui_data, **kw):
        LabelFrame.__init__(self, parent, text="Global Data", **kw)
        self.ui_data = ui_data
        self.draw()

    def draw(self):
        self.global_times = TimerDisplay(self, height=5)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.global_times.grid(row=0, column=0, sticky=N+S+W+E)

        self.cache_stats = CacheStats(self, self.ui_data)
        self.cache_stats.grid(row=0, column=1, sticky=N+S+W+E)

    def refresh(self):
        self.global_times.refresh(self.ui_data.timer.as_dict())
        self.cache_stats.refresh()

class SettingsFrame(LabelFrame):
    def __init__(self, parent, port, start, stop, **kw):
        LabelFrame.__init__(self, parent, text="Settings", **kw)
        self.start = start
        self.stop = stop
        self.port = port
        self.draw()

    def draw(self):
        def digits_filter(value):
            return not value or value.isdigit()

        self.digits_filter = self.register(digits_filter)
        Label(self, text="Port").grid(row=0, column=0, sticky=E+W)
        self.port_sb = Spinbox(self, from_=1024, to=65535, increment=1,
            validate='key', validatecommand=(self.digits_filter, '%P'))
        self.port_sb.delete(0, "end")
        self.port_sb.insert(0, self.port)
        self.port_sb.grid(row=0, column=1)

        Label(self, text="Preprocessor Threads").grid(row=1, column=0, sticky=E+W)
        self.pp_threads_sb = Spinbox(self, from_=1, to=4 * cpu_count(),
            increment=1, validate='key', validatecommand=(self.digits_filter, '%P'))
        self.pp_threads_sb.delete(0, "end")
        self.pp_threads_sb.insert(0, cpu_count())
        self.pp_threads_sb.grid(row=1, column=1)

        Separator(self).grid(row=2, column=0, columnspan=2, pady=10, sticky=E+W)

        self.start_but = Button(self, text="Start", command=self.start)
        self.start_but.grid(row=3, column=0, sticky=E+W)
        self.stop_but = Button(self, text="Stop", command=self.stop, state=DISABLED)
        self.stop_but.grid(row=3, column=1, sticky=E+W)

class DBManagerApp(Tk):
    state_stopped = 0
    state_started = 1

    def __init__(self, node_info, port):
        Tk.__init__(self, None)
        self.ui_data = type('UIData', (), {})()
        self.node_info = node_info
        self.port = port
        self.running = False
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

        # Row 0
        self.settings_frame = SettingsFrame(self, self.port,
            self.__start_running, self.__stop_running)
        self.settings_frame.grid(row=0, sticky=E+W, padx=5, pady=(0, 5))
        self.port_sb = self.settings_frame.port_sb
        self.pp_threads_sb = self.settings_frame.pp_threads_sb
        self.stop_but = self.settings_frame.stop_but
        self.start_but = self.settings_frame.start_but

        # Row 1
        self.pane = PanedWindow(self, orient=VERTICAL)

        self.global_data_frame = GlobalDataFrame(self.pane, self.ui_data)
        self.global_data_frame.grid(row=1, sticky=N+S+W+E)
        self.pane.add(self.global_data_frame)

        self.node_display = NodeDisplay(self.pane, self.node_info, self.ui_data)
        self.node_display.grid(row=2, sticky=N+S+W+E)
        self.pane.add(self.node_display)

        self.rowconfigure(1, weight=1)
        self.pane.grid(row=1, sticky=N+S+W+E)

        # Row 3
        self.sizegrip = Sizegrip(self)
        self.sizegrip.grid(row=3, column=0, columnspan=5, sticky=S+E)

    @called_from_foreign_thread
    def signal_refresh(self):
        self.refresh_event.set()

    def refresh(self):
        self.global_data_frame.refresh()
        self.node_display.refresh()

    def set_running(self, running):
        self.running = running
        self.stop_but['state'] = 'enable' if self.running else 'disable'
        self.start_but['state'] = 'enable' if not self.running else 'disable'
        self.port_sb['state'] = 'normal' if not self.running else 'disable'
        self.pp_threads_sb['state'] = 'normal' if not self.running else 'disable'

    def destroy(self):
        if self.running:
            self.__stop_running()
        Tk.destroy(self)

    def __start_running(self):
        if self.running:
            return
        try:
            port = int(self.port_sb.get())
            if not (1024 <= port <= 65535):
                raise ValueError()
        except ValueError:
            msgbox.showerror("Invalid Port Number", "Port number '{}' is invalid.\n"
                "It should be between 1 and 65535.".format(
                self.port_sb.get()))
            return

        try:
            threads = int(self.pp_threads_sb.get())
            if not (1 <= threads <= 4 * cpu_count()):
                raise ValueError()
        except ValueError:
            msgbox.showerror("Invalid Thread Count", "Thread count '{}' is invalid.\n"
                "It should be between 1 and {}.".format(
                self.pp_threads_sb.get(), 4 * cpu_count()))
            return
        
        self.task_processor = TaskProcessor(self.node_info, port, threads,
            self.ui_data)
        self.thread = threading.Thread(target=self.__run_task_processor)
        self.thread.start()
        self.set_running(True)

    def __run_task_processor(self):
        self.task_processor.run(self.signal_refresh)

    def __stop_running(self):
        if not self.running:
            return
        self.task_processor.stop()
        self.thread.join()
        self.set_running(False)
