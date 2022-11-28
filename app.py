from genericpath import exists
import hashlib
import os
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

file_dir = 'uploads/'

if not path.exists(file_dir):
    mkdir(file_dir)


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


async def fingerprint_file(audio_file: UploadFile):
    chunk = await audio_file.read(CHUNK_SIZE)
    try:
        f_type = filetype.audio_match(chunk)
        if not f_type:
            return INVALID_FILE_TYPE
    except:
        return INVALID_FILE_TYPE

    song_name = path.splitext(audio_file.filename)[0]
    file_name = f'{song_name}.{f_type.extension}.{uuid1()}'
    temp_path = path.join(file_dir, file_name)

    async with aiofiles.open(temp_path, 'wb') as out_file:
        file_hash = hashlib.sha1()
        while chunk:  # async read chunk
            file_hash.update(chunk)
            await out_file.write(chunk)  # async write chunk
            chunk = await audio_file.read(CHUNK_SIZE)

    file_hash = file_hash.hexdigest().upper()
    file_path = path.join(file_dir, f'{file_hash}')

    if exists(file_path):
        os.unlink(temp_path)
        return file_path, file_hash, None
    else:
        os.rename(temp_path, file_path)
        data = djv.fingerprint_file(
            file_path, song_name=song_name)
        # using thread
        # FingerprintFileWorker(file_path, song_name).start()
        if data is None:
            return file_path, file_hash, None
        else:
            sid, song_name, file_hash, hashes_count = data
    return file_path, file_hash, {'song_id': sid, 'song_type': f_type, 'song_name': song_name,  'file_hash': file_hash, 'hashes_count': hashes_count}


@app.put('/upload_file')
async def upload_file(audio_file: UploadFile):
    _, _, data = await fingerprint_file(audio_file)
    return JSONResponse({"result": "new" if data is not None else "exists", "data": data})


@app.post('/recognize_with_file')
async def recognize_with_file(audio_file: UploadFile):
    file_path, file_hash, data = await fingerprint_file(audio_file)
    results = djv.recognize(
        FileRecognizer, file_path, file_hash=file_hash)

    return JSONResponse(json.loads(json.dumps({'results': results['results']}, cls=BytesEncoder)))


@app.get('/recognize_with_hash/{audio_hash}')
async def recognize_with_hash(audio_hash: str):
    full_path = path.join(file_dir, audio_hash)
    if not exists(full_path):
        return JSONResponse({'err': 'audio not exists'})

    results = djv.recognize(FileRecognizer, full_path)
    return JSONResponse(json.loads(json.dumps({'results': results['results']}, cls=BytesEncoder)))
