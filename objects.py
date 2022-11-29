
import json
from threading import Thread
import numpy as np
from config import MAX_INQUEUE
import globs
from utils import is_added


class BytesEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.decode('utf-8')
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


class Attrdict(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.__dict__ = self


class WriteFileResult(Attrdict):
    song_name: str
    file_name: str
    temp_path: str
    file_hash: str
    file_type: str


class TaskFile:
    file_path: str
    song_name: str

    def __init__(self, file_path, song_name):
        self.file_path = file_path
        self.song_name = song_name


class FingerprintDirectoryWorker(Thread):
    def __init__(self):
        Thread.__init__(self)

    def run(self):
        if globs.directory_scanning:
            return
        globs.directory_scanning = True
        try:
            globs.djv.fingerprint_directory('uploads', ['*'])
        except Exception as err:
            print(f'[FingerprintDirectoryWorker] Err: {err}')
        globs.directory_scanning = False


class FingerprintFileWorker(Thread):
    def __init__(self, file_path, song_name):
        Thread.__init__(self)
        self.file_path = file_path
        self.song_name = song_name

    def run(self):
        if is_added(self.file_path):
            return

        # max
        if len(globs.inqueue_files) >= MAX_INQUEUE:
            globs.pending_files[self.file_path] = TaskFile(
                self.file_path, self.song_name)
            return

        globs.inqueue_files[self.file_path] = TaskFile(
            self.file_path, self.song_name)
        try:
            globs.djv.fingerprint_file(
                self.file_path, song_name=self.song_name)
        except Exception as err:
            print(f'[FingerprintFileWorker] Err: {err}')
        del globs.inqueue_files[self.file_path]
