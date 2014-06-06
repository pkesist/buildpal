from time import time

class Timer:
    def __init__(self):
        self.__times = {}

    def add_time(self, type, value):
        current = self.__times.get(type, (0, 0))
        self.__times[type] = (current[0] + value, current[1] + 1)

    def as_dict(self):
        return self.__times

    class ContextManagerTimer:
        def __init__(self, callable):
            self.__callable = callable
            self.__start = time()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.__callable(time() - self.__start)

    def timeit(self, name):
        return self.ContextManagerTimer(lambda value : self.add_time(name, value))
