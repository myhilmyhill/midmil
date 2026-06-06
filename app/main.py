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
OUTPUT_DIR = "outputs"

app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")

@app.get("/", response_class=HTMLResponse)
async def index():
    files = sorted(os.listdir(OUTPUT_DIR))
    file_list_html = "".join([
        f'<li><a href="/outputs/{f}">{f}</a>' 
        for f in files if f.endswith(".flac")
    ])

    return f"""
    <title>midmil</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <h2>1. MIDIアップロード</h2>
    <form action="/upload" method="post" enctype="multipart/form-data">
        <input type="file" name="files" accept=".mid,.midi" multiple>
        <button type="submit">変換開始</button>
    </form>
    <hr>
    <h2>2. 変換済み一覧</h2>
    <ul>{file_list_html}</ul>
    """

def get_unique_filename(base_name: str) -> str:
    # Sanitize base_name to prevent path traversal
    base_name = os.path.basename(base_name)
    counter = 2
    candidate = base_name
    while (os.path.exists(os.path.join(UPLOAD_DIR, f"{candidate}.mid")) or
           os.path.exists(os.path.join(OUTPUT_DIR, f"{candidate}.flac")) or
           os.path.exists(os.path.join(OUTPUT_DIR, f"{candidate}.flac.tmp"))):
        candidate = f"{base_name} ({counter})"
        counter += 1
    return candidate

@app.post("/upload")
async def upload_midi(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    for file in files:
        if not file.filename:
            continue
        safe_filename = os.path.basename(file.filename)
        base_name, _ = os.path.splitext(safe_filename)
        unique_base = get_unique_filename(base_name)
        midi_path = os.path.join(UPLOAD_DIR, f"{unique_base}.mid")
        flac_path = os.path.join(OUTPUT_DIR, f"{unique_base}.flac")
        
        contents = await file.read()
        with open(midi_path, "wb") as f:
            f.write(contents)
        
        background_tasks.add_task(run_conversion, midi_path, flac_path)
        
    return RedirectResponse(url="/", status_code=303)
