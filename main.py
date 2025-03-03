from fastapi import FastAPI, Request, Form, File, UploadFile, Body
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import subprocess
import shutil
import os
import time
import json
import uuid
import tempfile
import random
import httpx
import asyncio
from typing import Dict, Optional, List, Any
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Lokasi penyimpanan file
SOURCE_DIR = os.getenv("SOURCE_DIR","./source")
OUTPUT_DIR = os.getenv("OUTPUT_DIR","./output")
TEMP_DIR = os.getenv("TEMP_DIR","./temp")
os.makedirs(SOURCE_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# Menyimpan informasi upload yang sedang berlangsung
active_uploads = {}

# Menyimpan informasi progress transkripsi
transcription_progress = {}

# LLM configuration
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", ""))
LLM_TOP_P = float(os.getenv("LLM_TOP_P", ""))
LLM_MIN_TOKENS = int(os.getenv("LLM_MIN_TOKENS", ""))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", ""))

class UploadInit(BaseModel):
    filename: str
    totalChunks: int
    fileSize: int

class UploadComplete(BaseModel):
    uploadId: str
    filename: str

class ProcessLLMRequest(BaseModel):
    text: str

@app.get("/", response_class=HTMLResponse)
async def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request, "message": None, "transcription": None})

@app.get("/status/{filename}")
async def check_status(filename: str):
    output_filename = filename.rsplit(".", 1)[0] + ".txt"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    status_file = output_path + ".status"
    
    # Jika file hasil transkripsi ada, baca hasilnya
    if os.path.exists(output_path):
        try:
            with open(output_path, "r") as f:
                try:
                    transcription_json = json.load(f)
                    full_text = " ".join(chunk["text"] for chunk in transcription_json.get("chunks", []))
                except json.JSONDecodeError:
                    # Coba baca sebagai teks biasa jika bukan JSON
                    f.seek(0)
                    full_text = f.read()
                
            # Hapus file status setelah selesai
            if os.path.exists(status_file):
                os.remove(status_file)
                
            # Hapus dari tracking progress
            if filename in transcription_progress:
                del transcription_progress[filename]
                
            return {"status": "done", "text": full_text}
        except Exception as e:
            return {"status": "error", "message": f"Error reading transcription: {str(e)}"}
    
    # Jika file status masih ada, berarti masih diproses
    if os.path.exists(status_file):
        # Periksa apakah ada progress yang tersimpan
        progress = None
        if filename in transcription_progress:
            # Untuk proses yang lama, tambahkan simulasi progress
            elapsed_time = time.time() - transcription_progress[filename]["start_time"]
            # Estimasi: maksimal 15 menit untuk mencapai 95%
            max_progress = min(95, int(elapsed_time / 900 * 100))
            progress = min(max_progress, transcription_progress[filename]["progress"] + random.randint(1, 3))
            transcription_progress[filename]["progress"] = progress
        
        return {"status": "processing", "progress": progress}
    
    # Jika tidak ada file status dan tidak ada output, mungkin ada error
    return {"status": "error", "message": "File not found or failed to process"}

@app.post("/upload-init/")
async def upload_init(data: UploadInit):
    # Buat ID unik untuk upload ini
    upload_id = str(uuid.uuid4())
    
    # Buat direktori untuk menyimpan chunk
    upload_dir = os.path.join(TEMP_DIR, upload_id)
    os.makedirs(upload_dir, exist_ok=True)
    
    # Simpan informasi upload
    active_uploads[upload_id] = {
        "filename": data.filename,
        "totalChunks": data.totalChunks,
        "receivedChunks": 0,
        "uploadDir": upload_dir,
        "fileSize": data.fileSize,
        "timestamp": time.time()
    }
    
    return {"uploadId": upload_id}

@app.post("/upload-chunk/")
async def upload_chunk(
    uploadId: str = Form(...),
    chunkIndex: int = Form(...),
    file: UploadFile = File(...)
):
    # Validasi upload ID
    if uploadId not in active_uploads:
        return JSONResponse(status_code=400, content={"error": "Invalid upload ID"})
    
    upload_info = active_uploads[uploadId]
    chunk_file_path = os.path.join(upload_info["uploadDir"], f"chunk_{chunkIndex}")
    
    # Simpan chunk ke file
    with open(chunk_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Update jumlah chunk yang diterima
    upload_info["receivedChunks"] += 1
    
    # Update timestamp untuk keperluan cleanup
    upload_info["timestamp"] = time.time()
    
    return {"success": True, "chunkIndex": chunkIndex}

# Modifikasi pada fungsi upload_complete
@app.post("/upload-complete/")
async def upload_complete(data: UploadComplete):
    upload_id = data.uploadId
    
    # Validasi upload ID
    if upload_id not in active_uploads:
        return JSONResponse(status_code=400, content={"error": "Invalid upload ID"})
    
    upload_info = active_uploads[upload_id]
    
    # Validasi apakah semua chunk sudah diterima
    if upload_info["receivedChunks"] != upload_info["totalChunks"]:
        return JSONResponse(
            status_code=400, 
            content={
                "error": "Not all chunks received", 
                "received": upload_info["receivedChunks"], 
                "total": upload_info["totalChunks"]
            }
        )
    
    try:
        # Buat UUID untuk file
        file_uuid = str(uuid.uuid4())
        
        # Gabungkan semua chunk menjadi satu file dengan nama yang berisi UUID
        original_filename = upload_info["filename"]
        file_ext = original_filename.rsplit(".", 1)[1] if "." in original_filename else ""
        base_filename = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
        
        # Format nama file dengan UUID: original_name_uuid.extension
        uuid_filename = f"{base_filename}_{file_uuid}.{file_ext}" if file_ext else f"{base_filename}_{file_uuid}"
        source_path = os.path.join(SOURCE_DIR, uuid_filename)
        
        with open(source_path, "wb") as output_file:
            for i in range(upload_info["totalChunks"]):
                chunk_path = os.path.join(upload_info["uploadDir"], f"chunk_{i}")
                with open(chunk_path, "rb") as chunk_file:
                    output_file.write(chunk_file.read())
                    
        # Mulai proses transkripsi dengan nama file yang sudah berisi UUID
        output_filename = f"{base_filename}_{file_uuid}.txt"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        # Simpan status "processing" agar bisa dicek oleh polling
        status_file = output_path + ".status"
        with open(status_file, "w") as f:
            f.write("processing")
            
        # Inisialisasi progress untuk file ini
        transcription_progress[uuid_filename] = {
            "start_time": time.time(),
            "progress": 0,
            "original_filename": original_filename  # Simpan nama asli untuk referensi
        }
        
        # Jalankan transkripsi di background (non-blocking)
        command = [
            "insanely-fast-whisper",
            "--file-name", source_path,
            "--transcript-path", output_path,
            "--model-name", "openai/whisper-large-v3-turbo",
            "--task", "transcribe",
            "--batch", "16",
            "--flash", "TRUE",
            "--timestamp", "chunk"
        ]
        
        # Jalankan dengan stdout dan stderr dialihkan ke file log
        log_file = os.path.join(TEMP_DIR, f"{uuid_filename}.log")
        with open(log_file, "w") as log:
            subprocess.Popen(
                command, 
                stdout=log, 
                stderr=log, 
                start_new_session=True  # Pastikan tetap berjalan meskipun parent process berakhir
            )
            
        # Hapus direktori chunk sementara
        shutil.rmtree(upload_info["uploadDir"])
        
        # Hapus informasi upload
        del active_uploads[upload_id]
        
        return {
            "message": "File received, transcription is being processed.", 
            "filename": uuid_filename,
            "original_filename": original_filename
        }
    
    except Exception as e:
        # Jika terjadi error, hapus file status jika ada
        status_file = os.path.join(OUTPUT_DIR, f"{base_filename}_{file_uuid}.txt.status")
        if os.path.exists(status_file):
            os.remove(status_file)
            
        # Log error
        error_log = os.path.join(TEMP_DIR, f"error_{uuid_filename}.log")
        with open(error_log, "w") as f:
            f.write(str(e))
            
        # Hapus dari tracking progress
        if uuid_filename in transcription_progress:
            del transcription_progress[uuid_filename]
            
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process file: {str(e)}"}
        )
    
# Modifikasi pada fungsi upload normal (tanpa chunking)
@app.post("/upload/")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    task: str = Form("transcribe"),
    timestamp: str = Form("chunk"),
):
    try:
        # Buat UUID untuk file
        file_uuid = str(uuid.uuid4())
        
        # Pisahkan nama file dan ekstensi
        original_filename = file.filename
        file_ext = original_filename.rsplit(".", 1)[1] if "." in original_filename else ""
        base_filename = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
        
        # Format nama file dengan UUID: original_name_uuid.extension
        uuid_filename = f"{base_filename}_{file_uuid}.{file_ext}" if file_ext else f"{base_filename}_{file_uuid}"
        source_path = os.path.join(SOURCE_DIR, uuid_filename)
        
        # Format nama file output
        output_filename = f"{base_filename}_{file_uuid}.txt"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        with open(source_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Simpan status "processing" agar bisa dicek oleh polling
        status_file = output_path + ".status"
        with open(status_file, "w") as f:
            f.write("processing")
            
        # Inisialisasi progress untuk file ini
        transcription_progress[uuid_filename] = {
            "start_time": time.time(),
            "progress": 0,
            "original_filename": original_filename  # Simpan nama asli untuk referensi
        }
        
        # Jalankan transkripsi di background (non-blocking)
        command = [
            "insanely-fast-whisper",
            "--file-name", source_path,
            "--transcript-path", output_path,
            "--model-name", "openai/whisper-large-v3-turbo",
            "--task", "transcribe",
            "--batch", "64",
            "--flash", "TRUE",
            "--timestamp", "chunk"
        ]
        
        # Jalankan dengan stdout dan stderr dialihkan ke file log
        log_file = os.path.join(TEMP_DIR, f"{uuid_filename}.log")
        with open(log_file, "w") as log:
            subprocess.Popen(
                command, 
                stdout=log, 
                stderr=log,
                start_new_session=True
            )
            
        return {
            "message": "File received, transcription is being processed", 
            "filename": uuid_filename,
            "original_filename": original_filename
        }
        
    except Exception as e:
        # Jika terjadi error, hapus file status jika ada
        status_file = output_path + ".status"
        if os.path.exists(status_file):
            os.remove(status_file)
            
        # Log error
        error_log = os.path.join(TEMP_DIR, f"error_{uuid_filename}.log")
        with open(error_log, "w") as f:
            f.write(str(e))
            
        # Hapus dari tracking progress
        if uuid_filename in transcription_progress:
            del transcription_progress[uuid_filename]
            
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process file: {str(e)}"}
        )

# BAGIAN BARU: Endpoint untuk pemrosesan LLM

async def get_llm_response(system_prompt, user_prompt):
    """Fungsi umum untuk mendapatkan respons dari LLM"""
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [  
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}  
    ]  
    
    data = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "top_p": LLM_TOP_P,
        "min_tokens": LLM_MIN_TOKENS,
        "max_tokens": LLM_MAX_TOKENS,
    }
    
    try:
        async with httpx.AsyncClient(timeout=3600) as client:
            response = await client.post(LLM_ENDPOINT, headers=headers, json=data)
            response.raise_for_status()
            response_data = response.json()
            return response_data['choices'][0]['message']['content']
    except Exception as e:
        print(f"Error in LLM request: {e}")
        return f"Error: {str(e)}"

@app.post("/process-llm/paraphrase")
async def process_paraphrase(request: ProcessLLMRequest):
    """Endpoint untuk memparafrase teks"""
    system_prompt = """
    # WORK STEPS
    - Identify the main topics in the transcription.  
    - Create a structured summary with key points.  
    - If there are important points, list them in numbered format.  
    - If there are technical terms, provide brief explanations.  
    - Use <em>italic</em> for emphasizing important words.  
    
    # OUTPUT FORMAT  
    <body>
        <h4>Title: <summary title></h4>
        <p><strong>Summary:</strong> <brief summary in 2-3 sentences></p>
        
        <h4>Main Points</h4>
        <ul>
            <li><em><key point 1></em>: <explanation in 20-25 words></li>
            <li><em><key point 2></em>: <explanation in 20-25 words></li>
            <li>...</li>
        </ul>
        
        <h4>Conclusion</h4>
        <p><summary conclusion></p>
    </body>
    
    # OUTPUT INSTRUCTIONS
    - Generate output strictly following the format above.  
    - Do not include Markdown tags like ```html.  
    - Do not add warnings, explanations, or extra information—only the requested output.  
    - Maintain the structure and terminology present in the transcription.  
    - Only output the same language with original transcription text.  
    
    # INPUT:
    
    """
    try:
        result = await get_llm_response(system_prompt, request.text)
        return {"result": result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/process-llm/outline")
async def process_outline(request: ProcessLLMRequest):
    """Endpoint untuk membuat kerangka pembahasan"""
    system_prompt = """
    # WORK STEPS
    - Create a complete table of contents with all chapters and sub-chapters in an outline format like a table of contents. The table of contents contains main keywords that allow users to grasp the main ideas more quickly.
    - The numbering format is as follows, adjust as needed:
    <body>
        <h4>1. <material 1></h4>
        <ul>
            <li><em><topic a.></em>: <topic explanation in 25 words></li>
            <li><em><topic b.></em>: <topic explanation in 25 words></li>
            <li><em><topic c.></em>: <topic explanation in 25 words></li>
            <li>……</li>
        </ul>
    
        <h4>2. <material 2></h4>
        <ul>
            <li><em><topic a.></em>: <topic explanation in 25 words></li>
            <li>……</li>
        </ul>
    
        <h4>……</h4>
    </body>
    
    # OUTPUT INSTRUCTIONS
    - Create output using the above format and only using materials from the given text.
    - Don't add the "```html" tag to your output, as that's a Markdown tag.
    - Don't output warnings or notes—only the requested parts.
    - Maintain the chapter and subchapter structure present in the given text.
    - Don't change terminology present in the text to avoid confusing users.
    - Only output the same language with original transcription text.
    
    # INPUT:

    """
    
    try:
        result = await get_llm_response(system_prompt, request.text)
        return {"result": result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/reset/")
async def reset_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request, "message": None, "transcription": None})

# Rute untuk pembersihan upload yang tidak selesai (misalnya untuk cron job)
@app.post("/cleanup-uploads/")
async def cleanup_uploads(hours: Optional[int] = 24):
    """Membersihkan upload yang tidak selesai setelah beberapa jam"""
    current_time = time.time()
    deleted_count = 0
    
    for upload_id, info in list(active_uploads.items()):
        upload_timestamp = info.get("timestamp", 0)
        age_hours = (current_time - upload_timestamp) / 3600
            
        if age_hours > hours:
            # Hapus direktori chunk yang sudah tua
            upload_dir = info["uploadDir"]
            if os.path.exists(upload_dir):
                shutil.rmtree(upload_dir, ignore_errors=True)
            
            del active_uploads[upload_id]
            deleted_count += 1
    
    # Juga bersihkan progress tracking yang tidak aktif
    for filename in list(transcription_progress.keys()):
        start_time = transcription_progress[filename].get("start_time", 0)
        age_hours = (current_time - start_time) / 3600
        
        if age_hours > hours:
            del transcription_progress[filename]
    
    return {"message": f"Cleaned up {deleted_count} incomplete uploads older than {hours} hours"}

# Rute health check untuk memastikan server masih responsif
@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": time.time()}
