from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
import os
import pdfplumber
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
from google import genai
import tempfile

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

client = genai.Client(api_key="api_key_:)")

CLASSIFICATION_CATEGORIES = {
    'hy': ["ֆինանսական", "իրավաբանական", "վարչական", "տեխնիկական",
           "անձնական", "ակադեմիական", "գովազդային", "բժշկական"],
    'en': ["Financial", "Legal", "Administrative", "Technical",
           "Personal", "Academic", "Advertising", "Medical"],
    'ru': ["Финансовый", "Юридический", "Административный", "Технический",
           "Личный", "Академический", "Рекламный", "Медицинский"]
}

# API Documentation Endpoint
@app.route('/api', methods=['GET'])
def api_docs():
    """Returns documentation for the API endpoints"""
    docs = {
        "endpoints": {
            "/api/summarize": {
                "method": "POST",
                "description": "Summarize a PDF document",
                "parameters": {
                    "file": "PDF file to process (required)",
                    "classification": "boolean (true/false) to enable classification (optional, default: false)",
                    "language": "language code (hy/en/ru) for classification categories (optional, default: hy)"
                },
                "response": {
                    "summary": "text summary of the document",
                    "classification": "document classification if enabled",
                    "filename": "original filename"
                }
            }
        },
        "languages_supported": list(CLASSIFICATION_CATEGORIES.keys()),
        "classification_categories": CLASSIFICATION_CATEGORIES
    }
    return jsonify(docs)

# API Summarization Endpoint
@app.route('/api/summarize', methods=['POST'])
def api_summarize():
    """
    API endpoint for summarizing PDF documents.
    Accepts either file upload or base64 encoded content.
    """
    # Check for file in multipart/form-data
    if 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Invalid file type. Only PDFs are allowed.'}), 400
            
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
    # Check for base64 content in JSON payload
    elif request.is_json and 'content' in request.json:
        import base64
        try:
            content = request.json['content']
            filename = request.json.get('filename', 'document.pdf')
            filename = secure_filename(filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(content))
        except Exception as e:
            return jsonify({'error': f'Invalid base64 content: {str(e)}'}), 400
    else:
        return jsonify({'error': 'No file uploaded or content provided'}), 400
    
    try:
        full_text = process_pdf(filepath)
        
        # Get parameters from either form or JSON
        if request.is_json:
            classification_enabled = request.json.get('classification', False)
            language = request.json.get('language', 'hy')
        else:
            classification_enabled = request.form.get('classification', 'false') == 'true'
            language = request.form.get('language', 'hy')
        
        summarization_prompt = f"please do summarization for this text {full_text} on same language of document (if text in Armenian do it on Armenian), without comments from you"
        
        summarization_response = client.models.generate_content(
            model="gemma-3-27b-it", contents=summarization_prompt
        )
        summary = summarization_response.text
        
        classification = ""
        if classification_enabled:
            classes = CLASSIFICATION_CATEGORIES.get(language, CLASSIFICATION_CATEGORIES['en'])
            classification_prompt = f"please do classification for this text {summary} using only this classes {classes}, without comments from you"
            classification_response = client.models.generate_content(
                model="gemma-3-27b-it", contents=classification_prompt
            )
            classification = classification_response.text

        os.remove(filepath)
        
        return jsonify({
            'summary': summary,
            'classification': classification,
            'filename': filename,
            'status': 'success'
        })
        
    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': str(e), 'status': 'error'}), 500

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/summarize', methods=['POST'])
def summarize():
    """Original web interface endpoint (unchanged)"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and file.filename.lower().endswith('.pdf'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            full_text = process_pdf(filepath)
            
            classification_enabled = request.form.get('classification', 'false') == 'true'
            language = request.form.get('language', 'hy')
            
            summarization_prompt = f"please do summarization for this text {full_text} on same language of document (if text in Armenian do it on Armenian), without comments from you"
            
            summarization_response = client.models.generate_content(
                model="gemma-3-27b-it", contents=summarization_prompt
            )
            summary = summarization_response.text
            
            classification = ""
            if classification_enabled:
                classes = CLASSIFICATION_CATEGORIES.get(language, CLASSIFICATION_CATEGORIES['en'])
                classification_prompt = f"please do classification for this text {summary} using only this classes {classes}, without comments from you"
                classification_response = client.models.generate_content(
                    model="gemma-3-27b-it", contents=classification_prompt
                )
                classification = classification_response.text
    
            os.remove(filepath)
            
            return jsonify({
                'summary': summary,
                'classification': classification,
                'filename': filename 
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify({'error': 'Invalid file type. Only PDFs are allowed.'}), 400

def process_pdf(pdf_path):
    extracted_parts = []
    image_data = []

    # Extract Text from PDF
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            extracted_parts.append({"type": "text", "content": text, "page": page_num})

    # Extract Images from PDF
    doc = fitz.open(pdf_path)
    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        images = page.get_images(full=True)
        
        for img_index, img in enumerate(images):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]

            image = Image.open(io.BytesIO(image_bytes))
            
            # Get image position
            img_rect = page.get_image_rects(xref)
            y_pos = img_rect[0].y0 if img_rect else 0
            
            # Apply OCR on Images
            img_text = pytesseract.image_to_string(image, lang='hye+rus+eng').strip()
            
            image_data.append({
                "page": page_index,
                "position": y_pos,
                "text": img_text
            })

    # Combine text and image OCR results
    full_text = ""
    current_page = 0
    page_text = extracted_parts[current_page]["content"] if extracted_parts else ""

    image_data.sort(key=lambda x: (x["page"], x["position"]))
    
    for img in image_data:
        while current_page < img["page"]:
            full_text += page_text
            current_page += 1
            if current_page < len(extracted_parts):
                page_text = extracted_parts[current_page]["content"]
            else:
                page_text = ""
        
        # Insert the image text
        split_pos = int(img["position"] / page.rect.height * len(page_text)) if page_text else 0
        page_text = page_text[:split_pos] + f" {img['text']} " + page_text[split_pos:]

    full_text += page_text
    for remaining_page in range(current_page + 1, len(extracted_parts)):
        full_text += extracted_parts[remaining_page]["content"]

    return full_text

if __name__ == '__main__':
    app.run(debug=True)