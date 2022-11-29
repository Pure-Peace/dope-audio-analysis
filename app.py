from genericpath import exists
import hashlib
import inspect
import os
from tempfile import TemporaryFile
from threading import Thread
from uuid import uuid1
import aiofiles
from fastapi import FastAPI, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import json
import numpy as np
from os import path, mkdir
import filetype
from dejavu.logic.recognizer.file_recognizer import FileRecognizer
import aiohttp

import globs

from dejavu import Dejavu

origins = [
    '*'
]

# load config from a JSON file (or anything outputting a python dictionary)
config = {
    'database': {
        'host': '127.0.0.1',
        'user': 'postgres',
        'password': '123456',
        'database': 'dejavu'
    },
    'database_type': 'postgres'
}

FILE_DIR = 'uploads/'

if not path.exists(FILE_DIR):
    mkdir(FILE_DIR)


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


# create a Dejavu instance
djv = Dejavu(config)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

CHUNK_SIZE = 8192

INVALID_FILE_TYPE = JSONResponse({'err': 'invalid file type'})


class FingerprintDirectoryWorker(Thread):
    def __init__(self):
        Thread.__init__(self)

    def run(self):
        if globs.directory_scanning:
            return
        globs.directory_scanning = True
        try:
            djv.fingerprint_directory('uploads', ['*'])
        except Exception as err:
            print(f'[FingerprintDirectoryWorker] Err: {err}')
        globs.directory_scanning = False


class FingerprintFileWorker(Thread):
    def __init__(self, file_path, song_name):
        Thread.__init__(self)
        self.file_path = file_path
        self.song_name = song_name

    def run(self):
        if self.file_path in globs.inqueue_files:
            return
        globs.inqueue_files.add(self.file_path)
        try:
            djv.fingerprint_file(self.file_path, song_name=self.song_name)
        except Exception as err:
            print(f'[FingerprintFileWorker] Err: {err}')
        globs.inqueue_files.remove(self.file_path)


''' @app.put('/fingerprint_directory')
async def fingerprint_directory():
    if globs.directory_scanning:
        return JSONResponse({'status': 'inprogress'})

    FingerprintDirectoryWorker().start()
    return JSONResponse({'status': 'started'}) '''


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


async def write_file_from_readable(read_fn, file_name: str):
    async def async_read(size: int):
        return await read_fn(size)
    async def read(size: int):
        return read_fn(size)
    
    if inspect.iscoroutinefunction(read_fn):
        rd = async_read
    else:
        rd = read
    
    chunk = await rd(CHUNK_SIZE)
    try:
        f_type = filetype.audio_match(chunk)
        if not f_type:
            return None, INVALID_FILE_TYPE
    except:
        return None, INVALID_FILE_TYPE

    song_name = path.splitext(file_name)[0]
    file_name = f'{song_name}.{f_type.extension}.{uuid1()}'
    temp_path = path.join(FILE_DIR, file_name)

    async with aiofiles.open(temp_path, 'wb') as out_file:
        file_hash = hashlib.sha1()
        while chunk:  # async read chunk
            file_hash.update(chunk)
            await out_file.write(chunk)  # async write chunk
            chunk = await rd(CHUNK_SIZE)

    file_hash = file_hash.hexdigest().upper()

    return WriteFileResult(song_name=song_name, file_name=file_name, temp_path=temp_path, file_hash=file_hash, file_type=f_type.extension), None


async def fingerprint_file(readable, file_name, async_handle=False):
    r, err = await write_file_from_readable(readable, file_name)
    if err is not None:
        return None, err

    file_path = path.join(FILE_DIR, f'{r.file_hash}')

    if exists(file_path):
        os.unlink(r.temp_path)
        return (file_path, r.file_hash, 'exists'), None

    os.rename(r.temp_path, file_path)

    if file_path in globs.inqueue_files:
        return (file_path, r.file_hash, 'inqueue'), None

    if async_handle:
        # using thread
        FingerprintFileWorker(file_path, r.song_name).start()
        return (file_path, r.file_hash, 'inqueue'), None
    else:
        data = djv.fingerprint_file(file_path, song_name=r.song_name)
        if data is None:
            return (file_path, r.file_hash, 'exists'), None
        else:
            sid, song_name, file_hash, hashes_count = data

    return (file_path, r.file_hash or file_hash,
            {'song_id': sid, 'song_type': r.file_type, 'song_name': song_name or r.song_name,  'file_hash': r.file_hash, 'hashes_count': hashes_count}), None


@app.put('/upload_file')
async def upload_file(audio_file: UploadFile, async_handle=False):
    data, err = await fingerprint_file(audio_file.read, audio_file.filename, async_handle=async_handle)
    if err is not None:
        return err

    return JSONResponse({"result": 'new' if type(data[2]) != str else data[2], "data": data[2]})


@app.put('/upload_file_with_url')
async def upload_file_with_url(url: str, async_handle=False):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                with TemporaryFile(mode="wb+") as tmp:
                    tmp.write(await resp.read())
                    tmp.seek(0)
                    data, err = await fingerprint_file(tmp.read, url.split('/')[-1], async_handle=async_handle)
                    if err is not None:
                        return err

                return JSONResponse({"result": 'new' if type(data[2]) != str else data[2], "data": data[2]})
            else:
                return JSONResponse({"result": "failed", "data": await resp.text()})


@app.post('/recognize_with_file')
async def recognize_with_file(audio_file: UploadFile):
    data, err = await fingerprint_file(audio_file, audio_file.filename)
    if err is not None:
        return err
    results = djv.recognize(
        FileRecognizer, data[0], file_hash=data[1])

    return JSONResponse(json.loads(json.dumps({'results': results['results']}, cls=BytesEncoder)))


@app.get('/recognize_with_hash/{audio_hash}')
async def recognize_with_hash(audio_hash: str):
    full_path = path.join(FILE_DIR, audio_hash)
    if not exists(full_path):
        return JSONResponse({'err': 'audio not exists'})

    results = djv.recognize(FileRecognizer, full_path)
    return JSONResponse(json.loads(json.dumps({'results': results['results']}, cls=BytesEncoder)))
