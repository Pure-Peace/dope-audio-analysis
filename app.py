import asyncio
from genericpath import exists
from tempfile import TemporaryFile
from fastapi import FastAPI, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import json
from os import path
from config import FILE_DIR, ORIGINS
from dejavu.logic.recognizer.file_recognizer import FileRecognizer
import aiohttp
import globs
from objects import BytesEncoder, FingerprintDirectoryWorker
from utils import background_loop, create_dir, fingerprint_file

create_dir(FILE_DIR)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

bg_task = asyncio.create_task(background_loop(5))


@app.put('/fingerprint_directory')
async def fingerprint_directory():
    if globs.directory_scanning:
        return JSONResponse({'status': 'inprogress'})

    FingerprintDirectoryWorker().start()
    return JSONResponse({'status': 'started'})


@app.put('/upload_file')
async def upload_file(audio_file: UploadFile, async_handle: bool = False):
    data, err = await fingerprint_file(audio_file.read, audio_file.filename, async_handle=async_handle)
    if err is not None:
        return err

    return JSONResponse({"result": 'new' if type(data[2]) != str else data[2], "data": data[2]})


@app.put('/upload_file_with_url')
async def upload_file_with_url(url: str, async_handle: bool = False):
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
    results = globs.djv.recognize(
        FileRecognizer, data[0], file_hash=data[1])

    return JSONResponse(json.loads(json.dumps({'results': results['results']}, cls=BytesEncoder)))


@app.get('/recognize_with_hash/{audio_hash}')
async def recognize_with_hash(audio_hash: str):
    full_path = path.join(FILE_DIR, audio_hash)
    if not exists(full_path):
        return JSONResponse({'err': 'audio not exists'})

    results = globs.djv.recognize(FileRecognizer, full_path)
    return JSONResponse(json.loads(json.dumps({'results': results['results']}, cls=BytesEncoder)))


@app.get('/stats/service')
async def service_stats():
    return JSONResponse({
        "directory_scanning": globs.directory_scanning,
        "inqueue_files": globs.inqueue_files,
        "pending_files": globs.pending_files
    })


@app.get('/stats/db')
async def db_stats():
    return JSONResponse({
        "fingerprints": globs.djv.db.get_num_fingerprints(),
        "num_songs": globs.djv.db.get_num_songs()
    })
