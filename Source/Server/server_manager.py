from .header_repository import HeaderRepository
from .file_repository import FileRepository

from multiprocessing.managers import SyncManager

class Counter:
    def __init__(self):
        self.__count = 0

    def inc(self): self.__count += 1
    def dec(self): self.__count -= 1
    def get(self): return self.__count

class ServerManager(SyncManager):
    pass

ServerManager.register('Counter', Counter)
ServerManager.register('FileRepository', FileRepository)
ServerManager.register('HeaderRepository', HeaderRepository)
