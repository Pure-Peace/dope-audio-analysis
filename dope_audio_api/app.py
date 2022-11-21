from fastapi import FastAPI, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import json
import numpy as np
import aiofiles

from dejavu import Dejavu
from dejavu.logic.recognizer.file_recognizer import FileRecognizer

origins = [
    "*"
]

# load config from a JSON file (or anything outputting a python dictionary)
config = {
    "database": {
        "host": "127.0.0.1",
        "user": "postgres",
        "password": "123456",
        "database": "dejavu"
    },
    "database_type": "postgres"
}

read_size = 1024 * 10
file_dir = 'uploads/'


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
    allow_methods=["*"],
    allow_headers=["*"],
)

# app.mount("/", StaticFiles(directory="web/dist"), name="static")


@app.get("/test")
async def test():
    # Fingerprint all the mp3's in the directory we give it
    djv.fingerprint_directory("uploads", [".mp3"])

    """ # Recognize audio from a file
    results = djv.recognize(FileRecognizer, "mp3/61zlr-eckcl.wav")
    print(f"From file we recognized: {results}\n")

    # Or use a recognizer without the shortcut, in anyway you would like
    recognizer = FileRecognizer(djv)
    results = recognizer.recognize_file("mp3/61zlr-eckcl.wav")
    print(f"No shortcut, we recognized: {results}\n") """


@app.post("/uploadfile")
async def create_upload_file(file: UploadFile):
    # Recognize audio from a file
    filename = file_dir + file.filename
    async with aiofiles.open(filename, 'wb') as out_file:
        content = await file.read(read_size)
        while content:  # async read chunk
            await out_file.write(content)  # async write chunk
            content = await file.read(read_size)
    results = djv.recognize(FileRecognizer, filename)
    print(results)

    json_str = json.dumps({'results': results['results']}, cls=BytesEncoder)
    json_data = json.loads(json_str)
    print(f"From file {filename} we recognized: {json_data}\n")
    return JSONResponse(content=json_data)
