import os
from contextlib import contextmanager
from pathlib import Path
from typing import Union


class FileManager:
    def __init__(self, path: Union[os.PathLike, str, Path]):
        self.path = path
        self.file = None

    def __enter__(self):
        self.file = open(self.path, 'w+')
        return self.file

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file:
            self.file.close()


@contextmanager
def file_manager(path):
    try:
        file_ = open(path, 'w+')
        print(f'Opened {path}')
        yield file_
    finally:
        print(f'Closing {path}')
        file_.close()


with file_manager('bruh.txt') as f:
    f.write(f'Method {file_manager.__name__} was there')


with FileManager('bruh_2.txt') as f:
    f.write(f'Class {FileManager.__name__} was there')
