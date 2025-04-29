import logging
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
import os
import uuid
import tempfile
import hashlib
from cachetools import TTLCache

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration from environment variables
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "static/uploads")
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "static/output")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Create directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Cache setup (TTL: 1 hour)
cache = TTLCache(maxsize=100, ttl=3600)

logger.info("Starting FastAPI app with upload folder: %s, output folder: %s", UPLOAD_FOLDER, OUTPUT_FOLDER)

def allowed_file(filename: str) -> bool:
    """Check if the file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_hash(file_content: bytes) -> str:
    """Generate a hash for a file to use as cache key."""
    return hashlib.sha256(file_content).hexdigest()

def process_image(content: bytes) -> bytes:
    """Convert image to grayscale."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name
        img = Image.open(temp_file_path).convert("L")  # Convert to grayscale
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            img.save(temp_file.name, "PNG", optimize=True)
            with open(temp_file.name, "rb") as f:
                processed_content = f.read()
            os.unlink(temp_file.name)
        os.unlink(temp_file_path)
        return processed_content
    except Exception as e:
        logger.error("Image processing failed: %s", str(e))
        raise

def save_output_image(content: bytes, output_dir: str, output_name: str) -> str:
    """Save processed image to output directory."""
    try:
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_name)
        with open(output_path, "wb") as f:
            f.write(content)
        logger.info("Saved output image: %s", output_path)
        return output_path
    except Exception as e:
        logger.error("Failed to save output: %s", str(e))
        raise

@app.get("/")
async def root():
    """Root endpoint for basic API info."""
    logger.info("Root endpoint called")
    return {"message": "Welcome to the Image Processing API! Use /health or /process."}

@app.get("/health")
async def health_check():
    """Check if the API is running."""
    logger.info("Health check endpoint called")
    return {"status": "API is running"}

@app.post("/process")
async def process_images(source_image: UploadFile = File(...), dest_image: UploadFile = File(...)):
    """Process two images by converting them to grayscale."""
    logger.info("Processing images: source=%s, dest=%s", source_image.filename, dest_image.filename)
    # Validate file uploads
    if not source_image.filename or not dest_image.filename:
        return JSONResponse(status_code=400, content={"error": "No file selected"})

    if not (allowed_file(source_image.filename) and allowed_file(dest_image.filename)):
        return JSONResponse(status_code=400, content={"error": "Invalid file format. Only PNG, JPG, JPEG allowed"})

    # Read file contents
    source_content = await source_image.read()
    dest_content = await dest_image.read()

    # Generate cache key
    cache_key = f"{get_file_hash(source_content)}:{get_file_hash(dest_content)}"

    # Check cache
    if cache_key in cache:
        result_urls = cache[cache_key]
        logger.info("Cache hit for key: %s", cache_key)
        return {"source_result": result_urls[0], "dest_result": result_urls[1]}

    # Process images
    try:
        source_processed = process_image(source_content)
        dest_processed = process_image(dest_content)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    # Save processed images
    try:
        source_filename = f"source_{uuid.uuid4().hex}.png"
        dest_filename = f"dest_{uuid.uuid4().hex}.png"
        source_path = save_output_image(source_processed, OUTPUT_FOLDER, source_filename)
        dest_path = save_output_image(dest_processed, OUTPUT_FOLDER, dest_filename)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    # Cache result
    cache[cache_key] = [f"/{source_path}", f"/{dest_path}"]
    logger.info("Cached result for key: %s", cache_key)

    # Return result URLs
    return {"source_result": f"/{source_path}", "dest_result": f"/{dest_path}"}