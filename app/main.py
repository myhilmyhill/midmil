import os
import asyncio
import subprocess
import uuid
from typing import List
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from .conversion import run_conversion

app = FastAPI()

UPLOAD_DIR = "uploads"
WAV_DIR = "outputs"

app.mount("/outputs", StaticFiles(directory=WAV_DIR), name="outputs")

@app.get("/", response_class=HTMLResponse)
async def index():
    files = sorted(os.listdir(WAV_DIR), reverse=True)
    file_list_html = "".join([
        f'<li><audio controls src="/outputs/{f}"></audio>{f}' 
        for f in files if f.endswith(".wav")
    ])

    return f"""
    <title>midmil</title>
    <h2>1. MIDIアップロード</h2>
    <form action="/upload" method="post" enctype="multipart/form-data">
        <input type="file" name="file" accept=".mid,.midi" multiple>
        <button type="submit">変換開始</button>
    </form>
    <hr>
    <h2>2. 変換済みWAV一覧</h2>
    <ul>{file_list_html}</ul>
    """

def get_unique_filename(base_name: str) -> str:
    counter = 2
    candidate = base_name
    while (os.path.exists(os.path.join(UPLOAD_DIR, f"{candidate}.mid")) or
           os.path.exists(os.path.join(WAV_DIR, f"{candidate}.wav")) or
           os.path.exists(os.path.join(WAV_DIR, f"{candidate}.wav.tmp"))):
        candidate = f"{base_name} ({counter})"
        counter += 1
    return candidate

@app.post("/upload")
async def upload_midi(background_tasks: BackgroundTasks, file: List[UploadFile] = File(...)):
    for upload_file in file:
        if not upload_file.filename:
            continue
        base_name, _ = os.path.splitext(upload_file.filename)
        unique_base = get_unique_filename(base_name)
        midi_path = os.path.join(UPLOAD_DIR, f"{unique_base}.mid")
        wav_path = os.path.join(WAV_DIR, f"{unique_base}.wav")
        
        contents = await upload_file.read()
        with open(midi_path, "wb") as f:
            f.write(contents)
        
        background_tasks.add_task(run_conversion, midi_path, wav_path)
        
    return RedirectResponse(url="/", status_code=303)
