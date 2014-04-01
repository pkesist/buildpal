# !python3.3
from tkinter import *
import tkinter.font as font
import tkinter.messagebox as msgbox
from tkinter.ttk import *
from datetime import datetime

from collections import defaultdict
from operator import itemgetter
from threading import Thread, Lock
from time import time
from multiprocessing import cpu_count

from .task_processor import TaskProcessor
from .gui_event import GUIEvent

class MyTreeView(Treeview):
    def __init__(self, parent, columns, **kwargs):
        Treeview.__init__(self, parent,
            columns=tuple(c['cid'] for c in columns[1:]), **kwargs)
        heading_font = font.nametofont('TkHeadingFont')
        for c in columns:
            width = max(heading_font.measure(c['text']) + 15, c['minwidth'])
            self.column(c['cid'], width=width, minwidth=c['minwidth'],
                anchor=c['anchor'])
            self.heading(c['cid'], text=c['text'])

class NodeList(MyTreeView):
    columns = (
        {'cid' : "#0"        , 'text' : "Hostname"   , 'minwidth' : 150, 'anchor' : W     },
        {'cid' : "JobSlots"  , 'text' : "Slots"      , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "TasksSent" , 'text' : "Sent"       , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Completed" , 'text' : "Completed"  , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "TooLate"   , 'text' : "Too Late"   , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "TimedOut"  , 'text' : "Timed Out"  , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Stolen"    , 'text' : "Stolen"     , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "StolenDone", 'text' : "Stolen Done", 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Cancelled" , 'text' : "Cancelled"  , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Failed"    , 'text' : "Failed"     , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "Pending"   , 'text' : "Pending"    , 'minwidth' : 20 , 'anchor' : CENTER},
        {'cid' : "AvgTasks"  , 'text' : "Avg. Tasks" , 'minwidth' : 40 , 'anchor' : CENTER},
        {'cid' : "AvgTime"   , 'text' : "Avg. Time"  , 'minwidth' : 40 , 'anchor' : CENTER})

    gui_events = ((GUIEvent.update_node_info, 'refresh'),)

    def __init__(self, parent, nodes, **kwargs):
        MyTreeView.__init__(self, parent, self.columns, selectmode='browse', **kwargs)
        for node in nodes:
            text = node['hostname']
            self.insert('', 'end', text=text,
                values=(node['job_slots'],))

    def refresh(self, node_info):
        items = self.get_children('')
        assert len(items) == len(node_info)
        for node, item in zip(node_info, items):
            # Make sure the order did not change somehow.
            assert self.item(item)['text'] == node.node_dict()['hostname']
            values = (
                node.node_dict()['job_slots'], 
                node.tasks_sent     (),
                node.tasks_completed(),
                node.tasks_too_late (),
                node.tasks_timed_out(),
                node.tasks_stolen   (),
                node.tasks_successfully_stolen(),
                node.tasks_cancelled(),
                node.tasks_failed   (),
                node.tasks_pending  (),
                "{:.2f}".format(node.average_tasks()),
                "{:.2f}".format(node.average_task_time()))
            self.item(item, values=values)

class TimerDisplay(LabelFrame):
    columns = (
        { 'cid' : '#0'     , 'text' : 'Name'   , 'minwidth' : 150, 'anchor' : W      },
        { 'cid' : 'Total'  , 'text' : 'Total'  , 'minwidth' : 30 , 'anchor' : CENTER },
        { 'cid' : 'Count'  , 'text' : 'Count'  , 'minwidth' : 20 , 'anchor' : CENTER },
        { 'cid' : 'Average', 'text' : 'Average', 'minwidth' : 30 , 'anchor' : CENTER })

    def __init__(self, parent, **kwargs):
        LabelFrame.__init__(self, parent, **kwargs)
        self.global_timers = MyTreeView(self, self.columns)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.global_timers.grid(sticky=N+S+W+E)

    def refresh(self, timer_dict):
        selected_rows = [self.global_timers.index(x) for x in self.global_timers.selection()]
        self.global_timers.delete(*self.global_timers.get_children(''))
        sorted_times = [(name, total, count, total / count) for name, (total, count) in timer_dict.items()]
        sorted_times.sort(key=itemgetter(1), reverse=True)
        for index, (timer_name, total, count, average) in enumerate(sorted_times):
            values = (
                "{:.2f}".format(total),
                count,
                "{:.2f}".format(average))
            iid = self.global_timers.insert('', 'end', text=timer_name, values=values)
            if index in selected_rows:
                self.global_timers.selection_add(iid)

class GlobalTimerDisplay(TimerDisplay):
    gui_events = ((GUIEvent.update_global_timers, 'refresh'),)

class NodeDisplay(Frame):
    gui_events = ((GUIEvent.update_node_info, 'refresh'),)

    def __init__(self, parent, nodes):
        Frame.__init__(self)
        self.nodes = nodes
        self.node_index = None
        self.draw()

    def draw(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.paned_window = PanedWindow(self, orient=HORIZONTAL)

        node_label_frame = LabelFrame(self.paned_window, text='Node List')
        node_label_frame.rowconfigure(0, weight=1)
        node_label_frame.columnconfigure(0, weight=1)

        self.node_list = NodeList(node_label_frame, self.nodes, height=6)
        self.node_list.bind('<<TreeviewSelect>>', self.node_selected)
        self.node_list.grid(sticky=N+S+W+E)
        self.paned_window.add(node_label_frame, weight=1)

        self.node_times = TimerDisplay(self.paned_window, height=6, text="Node Timers")
        self.paned_window.add(self.node_times)
        self.paned_window.grid(row=0, column=0, sticky=N+S+W+E)

    def refresh(self, node_info):
        self.node_info = node_info
        if self.node_index is not None:
            self.update_selection()

    def node_selected(self, event):
        selection = self.node_list.selection()
        if not selection:
            self.node_index = None
        else:
            new_index = self.node_list.index(self.node_list.selection()[0])
            if new_index == self.node_index:
                return
            self.node_index = new_index
        self.update_selection()

    def update_selection(self):
        if self.node_index is None or not hasattr(self, 'node_info'):
            node = None
            node_time_dict = {}
        else:
            node = self.node_info[self.node_index]
            node_time_dict = node.timer().as_dict()
        self.node_times.refresh(node_time_dict)

class CacheStats(LabelFrame):
    gui_events = ((GUIEvent.update_cache_stats, 'refresh'),)

    def __init__(self, parent, **kw):
        LabelFrame.__init__(self, parent, text = "Cache Statistics", **kw)
        self.draw()
    
    def draw(self):
        self.include_directives = StringVar()
        self.cache_hits = StringVar()
        self.cache_ratio = StringVar()
        Separator(self).grid(row=0, column=0, columnspan=2, pady=5, sticky=E+W)
        Label(self, text="Include Directives").grid(row=1, sticky=W)
        Entry(self, state=DISABLED, textvariable=self.include_directives).grid(row=1, column=1)
        Label(self, text="Cache Hits").grid(row=2, sticky=W)
        Entry(self, state=DISABLED, textvariable=self.cache_hits).grid(row=2, column=1)
        Separator(self).grid(row=3, column=0, columnspan=2, pady=5, sticky=E+W)
        Label(self, text="Hit Ratio").grid(row=4, sticky=W)
        Entry(self, state=DISABLED, textvariable=self.cache_ratio).grid(row=4, column=1)
        Separator(self).grid(row=5, column=0, columnspan=2, pady=5, sticky=E+W)

    def refresh(self, cache_stats):
        hits, misses, ratio = cache_stats
        self.include_directives.set(hits + misses)
        self.cache_hits.set(hits)
        self.cache_ratio.set("{:.2f}".format(ratio))

class Miscellaneous(LabelFrame):
    gui_events = ((GUIEvent.update_unassigned_tasks, 'refresh'),)

    def __init__(self, parent, **kw):
        LabelFrame.__init__(self, parent, text = "Miscellaneous", **kw)
        self.draw()
    
    def draw(self):
        self.unassinged_tasks = StringVar()
        Separator(self).grid(row=0, column=0, columnspan=2, pady=5, sticky=E+W)
        Label(self, text="Unassigned Tasks").grid(row=1, sticky=W)
        Entry(self, state=DISABLED, textvariable=self.unassinged_tasks).grid(row=1, column=1)
        Separator(self).grid(row=2, column=0, columnspan=2, pady=5, sticky=E+W)

    def refresh(self, unassigned_tasks):
        self.unassinged_tasks.set(unassigned_tasks)

class GlobalDataFrame(Frame):
    def __init__(self, parent, **kw):
        Frame.__init__(self, parent, **kw)
        self.draw()

    def draw(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.global_times = GlobalTimerDisplay(self, height=5, text="Global Timers")
        self.global_times.grid(row=0, column=0, sticky=N+S+W+E)

        frame = Frame(self)
        self.cache_stats = CacheStats(frame)
        self.cache_stats.grid(sticky=N+S+W+E)

        self.miscellaneous = Miscellaneous(frame)
        self.miscellaneous.grid(row=1, sticky=N+S+W+E)
        frame.grid(row=0, column=1, sticky=N+S+W+E)

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
        self.port_var = StringVar()
        self.port_var.set(self.port)
        Entry(self, state=DISABLED, textvariable=self.port_var).grid(row=0, column=1)

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
        if False:
            # Debugging stuff
            self.stop_but = Button(self, text="Run PDB", command=self.start_pdb)
            self.stop_but.grid(row=3, column=2, sticky=E+W)
            self.stop_but = Button(self, text="Run Interpreter", command=self.start_interpreter)
            self.stop_but.grid(row=3, column=3, sticky=E+W)

    @staticmethod
    def start_pdb():
        import pdb
        pdb.set_trace()

    globals = {}

    @classmethod
    def start_interpreter(cls):
        import code
        code.InteractiveConsole(cls.globals).interact()


class CommandInfo(Frame):
    columns = ({'cid' : '#0'   , 'text': 'Info' , 'minwidth': 300, 'anchor' : W},
               {'cid' : 'Value', 'text': 'Value', 'minwidth': 50 , 'anchor' : W},)

    def __init__(self, parent, *args, **kw):
        Frame.__init__(self, parent, *args, **kw)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.task_list = MyTreeView(self, self.columns)
        self.task_list.grid(row=0, column=0, sticky=N+S+E+W)

    def refresh(self, command_info):
        children = self.task_list.get_children()
        if children:
            self.task_list.delete(children)
        if command_info is None:
            return
        def format_time(time_real):
            return datetime.fromtimestamp(time_real).strftime("%a %H:%M:%S.%f")
        def task_string(task):
            return task['source']
        def session_string(session):
            return "{}:{}".format(session['hostname'], session['port']), \
                session['result'].name
        def session_subdata(session):
            return [
                ("Started:", format_time(session['started'])),
                ("Completed:", format_time(session['completed'])),
                ("Duration:", "{:.2f}".format(session['completed'] - session['started']))]

        for task in command_info['tasks']:
            task_id = self.task_list.insert('', 'end', text=task_string(task), open=True)
            times = self.task_list.insert(task_id, 'end', text='Times', open=True)
            for time_entry in task['times']:
                self.task_list.insert(times, 'end', text=time_entry['time_point_name'],
                    values=(format_time(time_entry['time_point']),))
            sessions = self.task_list.insert(task_id, 'end', text='Sessions', open=True)
            for session in task['sessions']:
                text, value = session_string(session)
                session_id = self.task_list.insert(sessions, 'end', text=text, values=(value,), open=True)
                for text, value in session_subdata(session):
                    self.task_list.insert(session_id, 'end', text=text, values=(value,))

class CommandBrowser(PanedWindow):
    columns = ({'cid' : "#0"     , 'text' : "#"      , 'minwidth' :  40, 'anchor' : W },
               {'cid' : "Targets", 'text' : "Targets", 'minwidth' : 250, 'anchor' : W },)

    gui_events = ((GUIEvent.update_command_info, 'refresh'),)

    def __init__(self, parent, *args, **kw):
        PanedWindow.__init__(self, parent, orient=HORIZONTAL)
        frame = Frame(self)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        sb = Scrollbar(frame)
        sb.grid(row=0, column=1, sticky=N+S)
        self.tv = MyTreeView(frame, self.columns)
        self.tv.grid(row=0, column=0, sticky=N+S+W+E)
        self.tv['yscrollcommand'] = sb.set
        self.tv.bind('<<TreeviewSelect>>', self.command_selected)
        sb.config(command=self.tv.yview)
        self.add(frame)
        self.displayed_rows = {}

        self.db = None
        self.db_conn = None

        self.row_to_db = {}
        self.db_to_row = {}

        self.command_info = CommandInfo(self)
        self.add(self.command_info)

    def command_selected(self, event):
        selection = self.tv.selection()
        if not selection:
            data = None
        else:
            row_id = self.row_to_db[selection[0]]
            assert self.db_conn is not None
            data = self.db.get_command(self.db_conn, row_id)
        self.command_info.refresh(data)

    def refresh(self, command_db):
        if self.db_conn is None:
            if self.db is None:
                self.db = command_db
            self.db_conn = self.db.get_connection()
            self.db_conn.execute("PRAGMA read_uncommitted = 1")

        if self.db_to_row:
            last_row_id = max(self.db_to_row.keys())
        else:
            last_row_id = 0
        cursor = self.db_conn.execute(
            "SELECT rowid, command FROM command WHERE rowid > ?",
            (last_row_id,))
        for rowid, targets in cursor:
            iid = self.tv.insert('', 'end', text=len(self.tv.get_children('')) + 1, values=(targets,))
            self.row_to_db[iid] = rowid
            self.db_to_row[rowid] = iid

def collect_window_events(window):
    result = defaultdict(list)
    if hasattr(window, 'gui_events'):
        for event_type, method_name in window.gui_events:
            method = getattr(window, method_name)
            result[event_type].append(method)
    for child in window.winfo_children():
        child_events = collect_window_events(child)
        for event_type, handlers in child_events.items():
            result[event_type].extend(handlers)
    return result

class BPManagerApp(Tk):
    state_stopped = 0
    state_started = 1

    def __init__(self, nodes, port):
        Tk.__init__(self, None)
        self.nodes = nodes
        self.port = port
        self.running = False
        self.initialize()
        self.events = collect_window_events(self)
        self.event_data_lock = Lock()
        self.event_data = {}
        self.__periodic_refresh()

    def __periodic_refresh(self):
        with self.event_data_lock:
            for event_type, event_data in self.event_data.items():
                for event_handler in self.events[event_type]:
                    event_handler(event_data)
            self.event_data.clear()
        self.after(150, self.__periodic_refresh)

    def initialize(self):
        self.columnconfigure(0, weight=1)

        # Row 0
        self.settings_frame = SettingsFrame(self, self.port,
            self.__start_running, self.__stop_running)
        self.settings_frame.grid(row=0, sticky=E+W, padx=5, pady=(0, 5))
        self.pp_threads_sb = self.settings_frame.pp_threads_sb
        self.stop_but = self.settings_frame.stop_but
        self.start_but = self.settings_frame.start_but

        # Row 1
        self.pane = PanedWindow(self, orient=VERTICAL)

        self.node_display = NodeDisplay(self.pane, self.nodes)
        self.node_display.grid(row=1, sticky=N+S+W+E)
        self.pane.add(self.node_display)

        self.notebook = Notebook(self.pane)

        self.global_data_frame = GlobalDataFrame(self.notebook)
        self.notebook.add(self.global_data_frame, text="Global Data")

        self.command_browser = CommandBrowser(self.notebook)
        self.notebook.add(self.command_browser, text="Commands")

        self.pane.add(self.notebook)

        self.rowconfigure(1, weight=1)
        self.pane.grid(row=1, sticky=N+S+W+E)

        self.sizegrip = Sizegrip(self)

    def post_event(self, event_type, event_data):
        with self.event_data_lock:
            self.event_data[event_type] = event_data

    def refresh(self):
        self.global_data_frame.refresh()
        self.node_display.refresh()
        self.command_browser.refresh()

    def set_running(self, running):
        self.running = running
        self.stop_but['state'] = 'enable' if self.running else 'disable'
        self.start_but['state'] = 'enable' if not self.running else 'disable'
        self.pp_threads_sb['state'] = 'normal' if not self.running else 'disable'

    def destroy(self):
        if self.running:
            self.__stop_running()
        Tk.destroy(self)

    def __start_running(self):
        if self.running:
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
        
        self.task_processor = TaskProcessor(self.nodes, self.port, threads)
        self.thread = Thread(target=self.__run_task_processor)
        self.thread.start()
        self.set_running(True)

    def __run_task_processor(self):
        self.task_processor.run(self.post_event)

    def __stop_running(self):
        if not self.running:
            return
        self.task_processor.stop()
        self.thread.join()
        self.set_running(False)
