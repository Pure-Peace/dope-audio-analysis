import asyncio
import hashlib
import inspect
from os import mkdir, path
from genericpath import exists
import os
from uuid import uuid1
import aiofiles
import filetype
from fastapi.responses import JSONResponse
import globs
from config import CHUNK_SIZE, FILE_DIR, MAX_INQUEUE
import objects


INVALID_FILE_TYPE = JSONResponse({'err': 'invalid file type'})


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

    return objects.WriteFileResult(song_name=song_name, file_name=file_name, temp_path=temp_path, file_hash=file_hash, file_type=f_type.extension), None


async def fingerprint_file(readable, file_name: str, async_handle: bool = False):
    r, err = await write_file_from_readable(readable, file_name)
    if err is not None:
        return None, err

    file_path = path.join(FILE_DIR, f'{r.file_hash}')

    if exists(file_path):
        os.unlink(r.temp_path)
        return (file_path, r.file_hash, 'exists'), None

    os.rename(r.temp_path, file_path)

    if is_added(file_path):
        return (file_path, r.file_hash, 'inqueue'), None

    if async_handle:
        # using thread
        objects.FingerprintFileWorker(file_path, r.song_name).start()
        return (file_path, r.file_hash, 'inqueue'), None
    else:
        data = globs.djv.fingerprint_file(file_path, song_name=r.song_name)
        if data is None:
            return (file_path, r.file_hash, 'exists'), None
        else:
            sid, song_name, file_hash, hashes_count = data

    return (file_path, r.file_hash or file_hash,
            {'song_id': sid, 'song_type': r.file_type, 'song_name': song_name or r.song_name,  'file_hash': r.file_hash, 'hashes_count': hashes_count}), None


def create_dir(pat: str):
    if not path.exists(pat):
        mkdir(pat)


def is_added(pat: str):
    if (pat in globs.inqueue_files) or (pat in globs.pending_files):
        return True
    return False


async def background_loop(sleep_sec: int):
    while True:
        if inqueue_count := len(globs.inqueue_files) > 0 and inqueue_count < MAX_INQUEUE:
            for _ in range(min(MAX_INQUEUE - inqueue_count, len(globs.pending_files))):
                t, _ = globs.pending_files.popitem()
                objects.FingerprintFileWorker(t.file_path, t.song_name)
        await asyncio.sleep(sleep_sec)
