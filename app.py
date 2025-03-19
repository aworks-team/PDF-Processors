import os
import csv
import math
import datetime
from pathlib import Path
import platform
import pandas as pd
import json
import requests
from io import StringIO
from flask import Flask, render_template, request, send_file, jsonify, session
from werkzeug.utils import secure_filename
from pdf_processor import PDFProcessor
from data_processor import DataProcessor
from csv_exporter import CSVExporter
from config import OUTPUT_CSV_NAME, OPENAI_API_KEY, OPENAI_MODEL  # Add OPENAI_API_KEY and OPENAI_MODEL to config.py

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.dirname(os.path.abspath(__file__))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Allow cookie in iframe
app.config['SESSION_COOKIE_SECURE'] = True  # Required for SameSite=None
app.secret_key = 'your-secret-key-here'  # Required for session management

# Allowed extensions for PDF upload
ALLOWED_PDF_EXTENSIONS = {'pdf'}
# Allowed extensions for CSV/XLSX upload
ALLOWED_CSV_EXTENSIONS = {'csv', 'xlsx', 'xls'}

# Order processor constants
ORDER_OUTPUT_CSV = "order_data.csv"
ALLOWED_ORDER_PDF_EXTENSIONS = {'pdf'}

# Check if poppler is installed or install it if on Render
if os.environ.get('RENDER') and platform.system() != 'Windows':
    try:
        # Try to use poppler
        from pdf2image import convert_from_path
        test_pdf = Path(__file__).parent / "test.pdf"
        if not test_pdf.exists():
            # Create a valid test file with actual content
            with open(test_pdf, "wb") as f:
                # This is a minimal but valid PDF with one page
                f.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 3 3]/Parent 2 0 R/Resources<<>>>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000053 00000 n\n0000000102 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n180\n%%EOF\n")
        
        # Test if poppler works
        pages = convert_from_path(str(test_pdf), dpi=72)
        print(f"Poppler working correctly. Detected {len(pages)} pages.")
    except Exception as e:
        print(f"Error with poppler: {e}")
        print("Poppler not available, functionality will be limited")


def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def process_pdf():
    """Process the PDF file through our pipeline."""
    try:
        # Initialize processors
        pdf_processor = PDFProcessor()
        data_processor = DataProcessor()
        csv_exporter = CSVExporter()
        
        # Process through pipeline
        if not pdf_processor.process_first_pdf():
            return False, "Failed to process PDF"
            
        if not data_processor.process_all_files():
            return False, "Failed to process text files"
            
        if not csv_exporter.combine_to_csv():
            return False, "Failed to create CSV file"
            
        return True, "Processing completed successfully"
        
    except Exception as e:
        return False, str(e)

def cleanup_old_files():
    """Clean up old PDFs and combined CSV file when page is loaded/refreshed."""
    try:
        script_dir = app.config['UPLOAD_FOLDER']
        
        # Only clean files in the main directory, not in processing_sessions
        for file in os.listdir(script_dir):
            file_path = os.path.join(script_dir, file)
            # Skip if it's a directory (like processing_sessions)
            if os.path.isdir(file_path):
                continue
                
            # Delete old PDFs
            if file.lower().endswith('.pdf'):
                try:
                    os.remove(file_path)
                    print(f"Cleaned up old PDF: {file}")
                except Exception as e:
                    print(f"Error deleting PDF {file}: {str(e)}")
        
            # Delete old combined CSV
            if file == OUTPUT_CSV_NAME:
                try:
                    os.remove(file_path)
                    print(f"Cleaned up old combined CSV: {OUTPUT_CSV_NAME}")
                except Exception as e:
                    print(f"Error deleting combined CSV: {str(e)}")
                    
    except Exception as e:
        print(f"Error during cleanup: {str(e)}")

def get_or_create_session():
    """Get existing processor or create new one with session management."""
    if 'session_id' not in session:
        # Only clean up old sessions when creating a new one AND no session exists
        base_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'processing_sessions')
        if os.path.exists(base_dir):
            # Check if there are any existing sessions with combined_data.csv
            existing_sessions = []
            for session_dir in os.listdir(base_dir):
                full_path = os.path.join(base_dir, session_dir)
                if os.path.isdir(full_path):
                    csv_path = os.path.join(full_path, OUTPUT_CSV_NAME)
                    if os.path.exists(csv_path):
                        existing_sessions.append(session_dir)
            
            if existing_sessions:
                # Use the most recent session that has a combined_data.csv
                most_recent = sorted(existing_sessions)[-1]
                session['session_id'] = most_recent
                processor = DataProcessor(session_id=most_recent)
                print(f"Reusing existing session with data: {most_recent}")
                return processor
            else:
                # No valid sessions found, clean up and create new
                DataProcessor.cleanup_sessions()
        
        # Create new session if none exists or no valid sessions found
        processor = DataProcessor()
        session['session_id'] = processor.session_id
        print(f"Created new session: {processor.session_id}")
    else:
        processor = DataProcessor(session_id=session['session_id'])
        print(f"Using existing session: {session['session_id']}")
        print(f"Using existing session: {session['session_id']}")
    return processor

@app.route('/', methods=['GET'])
def index():
    # Get or create session without cleaning up existing valid sessions
    processor = get_or_create_session()
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    # Use existing session instead of creating new one
    processor = get_or_create_session()
    
    # Process the files
    processor.process_all_files()
    
    # Create exporter with the same session directory
    exporter = CSVExporter(session_dir=processor.session_dir)
    exporter.combine_to_csv()
    
    return jsonify({"status": "success"})

# Add near your other routes
@app.route('/health')
def health():
    # Check if poppler is working
    poppler_status = "working" if os.environ.get('POPPLER_WORKING') else "not working"
    
    return jsonify({
        "status": "healthy",
        "poppler_status": poppler_status,
        "environment": os.environ.get('RENDER', 'local')
    }), 200

@app.route('/upload', methods=['POST'])
def upload_file():
    # Get existing processor with session directory
    processor = get_or_create_session()
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if not allowed_file(file.filename, ALLOWED_PDF_EXTENSIONS):
        return jsonify({'error': 'Invalid file type (PDF required)'}), 400
        
    try:
        # Save the uploaded PDF directly to session directory
        filename = secure_filename(file.filename)
        file_path = os.path.join(processor.session_dir, filename)
        file.save(file_path)
        
        # Process the PDF through our pipeline
        pdf_processor = PDFProcessor(session_dir=processor.session_dir)
        if not pdf_processor.process_first_pdf():
            return jsonify({'error': 'Failed to process PDF'}), 500
            
        if not processor.process_all_files():
            return jsonify({'error': 'Failed to process text files'}), 500
            
        # Create exporter with the same session directory
        exporter = CSVExporter(session_dir=processor.session_dir)
        if not exporter.combine_to_csv():
            return jsonify({'error': 'Failed to create CSV file'}), 500
            
        return jsonify({'message': 'File processed successfully'}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.after_request
def after_request(response):
    """Add headers to allow iframe embedding and CORS."""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return response

def process_order_pdf_with_openai(pdf_path, session_dir):
    """
    Process an order PDF using OpenAI to extract structured data.
    Returns the path to the generated CSV file.
    """
    try:
        # Extract text from PDF using pdfplumber
        from pdf_processor import PDFProcessor
        import pdfplumber
        import time
        import re
        from datetime import datetime
        
        print(f"\n===== PROCESSING ORDER PDF =====")
        print(f"PDF Path: {pdf_path}")
        print(f"Session Directory: {session_dir}")
        
        # Function to convert date string to MMDDYYYY format
        def format_date_to_mmddyyyy(date_str):
            if not date_str:
                return ""
                
            print(f"  Formatting date: '{date_str}'")
                
            # Try various date formats
            date_formats = [
                "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y",  # Standard formats
                "%Y-%m-%d", "%Y/%m/%d",  # ISO format
                "%B %d, %Y", "%b %d, %Y",  # Month name formats
                "%d/%m/%Y", "%d-%m-%Y"  # European formats
            ]
            
            # Try to parse the date
            parsed_date = None
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    print(f"    Matched format: {fmt}")
                    break
                except ValueError:
                    continue
            
            # If no format worked, try to extract using regex for common patterns
            if not parsed_date:
                print(f"    No standard format matched, trying regex")
                # Try to extract month, day, year from string like "January 15, 2024" or similar
                month_pattern = r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
                date_pattern = fr'{month_pattern}\s+(\d{{1,2}})[,\s]+(\d{{4}})'
                match = re.search(date_pattern, date_str, re.IGNORECASE)
                
                if match:
                    month_names = {
                        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                    }
                    month_str = match.group(1).lower()[:3]
                    month = month_names.get(month_str, 1)
                    day = int(match.group(2))
                    year = int(match.group(3))
                    parsed_date = datetime(year, month, day)
                    print(f"    Matched regex pattern: {month}/{day}/{year}")
            
            # If we successfully parsed the date, format it as MMDDYYYY
            if parsed_date:
                formatted_date = parsed_date.strftime("%m%d%Y")
                print(f"    Converted to: {formatted_date}")
                return formatted_date
            
            # If all else fails, remove non-numeric characters and try to format
            digits_only = ''.join(filter(str.isdigit, date_str))
            if len(digits_only) >= 8:  # If we have at least 8 digits (MMDDYYYY)
                print(f"    Trying digits-only approach: {digits_only}")
                # Try to interpret as MMDDYYYY, YYYYMMDD, or other formats
                if len(digits_only) == 8:
                    # Check if valid as MMDDYYYY
                    try:
                        parsed_date = datetime.strptime(digits_only, "%m%d%Y")
                        print(f"    Valid as MMDDYYYY: {digits_only}")
                        return digits_only
                    except ValueError:
                        # Check if valid as YYYYMMDD
                        try:
                            parsed_date = datetime.strptime(digits_only, "%Y%m%d")
                            formatted_date = parsed_date.strftime("%m%d%Y")
                            print(f"    Valid as YYYYMMDD, converted to MMDDYYYY: {formatted_date}")
                            return formatted_date
                        except ValueError:
                            print(f"    Not a valid date in numeric format")
            
            # If everything fails, return original with warning
            print(f"    WARNING: Could not parse date '{date_str}', returning as is")
            return date_str
        
        # Open the output CSV file for writing
        output_path = os.path.join(session_dir, ORDER_OUTPUT_CSV)
        current_date = datetime.now().strftime("%m%d%y")  # MMDDYY format
        print(f"Current Date (for Column D): {current_date}")
        print(f"Output CSV Path: {output_path}")
        
        with open(output_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            row_counter = 1  # For sequential numbering
            
            # Process each page individually
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                print(f"\nPDF has {total_pages} pages")
                
                for page_num, page in enumerate(pdf.pages):
                    print(f"\n----- Processing Page {page_num + 1} of {total_pages} -----")
                    text = page.extract_text()
                    
                    if not text:
                        print(f"ERROR: No text could be extracted from page {page_num + 1}")
                        continue
                    
                    # Check if this page contains "packing slip" (case insensitive)
                    if "packing slip" not in text.lower():
                        print(f"INFO: Page {page_num + 1} does not contain 'packing slip', skipping this page")
                        continue
                    
                    print(f"INFO: Found 'packing slip' on page {page_num + 1}, processing this page...")
                    
                    # Print first few lines of the extracted text to help with debugging
                    preview_lines = text.split('\n')[:5]
                    print(f"Text preview (first 5 lines):")
                    for i, line in enumerate(preview_lines):
                        print(f"  Line {i+1}: {line[:80]}{'...' if len(line) > 80 else ''}")
                    print(f"  [Total: {len(text.split('\n'))} lines, {len(text)} characters]")
                    
                    # Create prompt for OpenAI for this page
                    print(f"Creating prompt for OpenAI (page {page_num + 1})")
                    prompt = f"""
                    Extract the following information from this PDF order document page {page_num + 1} of {total_pages}:
                    - PO Number
                    - SO Number
                    - Ship Date (in MM/DD/YYYY format)
                    - Cancel Date (in MM/DD/YYYY format)
                    
                    For items on this page, ONLY extract item codes (NOT descriptions). Item codes typically look like:
                    - "DENISSE 41 VH - WSH GLD/PRP A" 
                    - "GRANDE VH - WHT/GLD PRL POP OS"
                    - "REFLEX 12 VH - RED MLT BB"
                    
                    Valid item codes usually include brand/model identifiers followed by a suffix like 'OS', 'A', 'BB', etc.
                    
                    IMPORTANT: Extract ALL items, even those with 0 ordered quantity. Include all item codes with their
                    ordered quantities, including zeros.
                    
                    IMPORTANT: In some PDFs, there may be numbers in the description column like "7-11" or "8-11". These are NOT 
                    the ordered quantities. The ordered quantities are usually standalone numbers in a separate column.
                    
                    DO NOT include:
                    - Descriptions (like "METALLIC WASHED GOLD PURPLE" or "LOW TOP")
                    - Shipping fees or S&H entries
                    - Discounts
                    - Number ranges (like "7-11" or "8-11") as ordered quantities
                    
                    For each valid item, extract:
                    - Item: The complete item code (with its suffix)
                    - Ordered: ONLY the actual quantity ordered (typically a standalone number, not a range like "7-11")
                    
                    Also identify the complete "Ship To" block/section if it exists on this page, and return it as a single text string.
                    
                    Return the data in a JSON format with these exact keys. For items, return an array of objects with "item" and "ordered" keys.
                    
                    Here is the page content:
                    {text}
                    """
                    
                    # Call OpenAI API
                    print(f"Calling OpenAI API with model: {OPENAI_MODEL}")
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {OPENAI_API_KEY}"
                    }
                    
                    payload = {
                        "model": OPENAI_MODEL,  # Use the model from config
                        "messages": [
                            {"role": "system", "content": "You are a helpful assistant that extracts order information from PDFs. You are particularly skilled at identifying complete item codes and distinguishing them from mere descriptions. Item codes typically include model numbers, color codes, and end with specific suffixes like 'A', 'OS', or 'BB'. Always include items with 0 ordered quantity in your extraction. IMPORTANT: Do not confuse description numbers or number ranges (like '7-11') with ordered quantities. Ordered quantities are typically standalone numbers in a dedicated column."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2
                    }
                    
                    print(f"Sending request to OpenAI API...")
                    response = requests.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers=headers,
                        data=json.dumps(payload)
                    )
                    
                    if response.status_code != 200:
                        print(f"ERROR: OpenAI API error on page {page_num + 1}: {response.text}")
                        continue
                    
                    # Parse response
                    print(f"Received response from OpenAI API")
                    result = response.json()
                    content = result['choices'][0]['message']['content']
                    
                    # Extract JSON from the response
                    try:
                        # Try to find JSON in the response
                        print(f"Parsing JSON response")
                        json_match = re.search(r'```json\n([\s\S]*?)\n```', content)
                        if json_match:
                            print(f"Found JSON in code block")
                            extracted_data = json.loads(json_match.group(1))
                        else:
                            print(f"Parsing raw response as JSON")
                            extracted_data = json.loads(content)
                        
                        print(f"Successfully extracted data from page {page_num + 1}")
                        print(f"Extracted fields:")
                        for key, value in extracted_data.items():
                            if key != 'items':  # Don't print all items
                                print(f"  {key}: {value}")
                        if 'items' in extracted_data:
                            print(f"  items: {len(extracted_data['items'])} items found")
                            
                    except Exception as e:
                        print(f"ERROR: Failed to parse JSON from OpenAI response on page {page_num + 1}: {e}")
                        print(f"Raw response preview: {content[:200]}...")
                        continue
                    
                    # Process Ship To information separately with a dedicated OpenAI call if we found a Ship To block
                    ship_to_block = extracted_data.get('Ship To', '')
                    ship_to_details = {}
                    
                    if ship_to_block:
                        print(f"\nFound Ship To block, sending for detailed parsing:")
                        print(f"  Block: {ship_to_block}")
                        
                        ship_to_prompt = f"""
                        Parse this shipping address block into its components:
                        
                        {ship_to_block}
                        
                        Extract and return ONLY these fields in JSON format:
                        - Ship_To_Name (almost always just the first line, can either be a company/person name)
                        - Ship_To_Address (ONLY the actual street address with number, like "123 Main St" - do NOT include c/o lines or additional recipient info)
                        - Ship_To_City
                        - Ship_To_State (two-letter state code if possible)
                        - Ship_To_Zip
                        
                        Important: 
                        - The street address is typically a line with a numeric component (like "376 AMAZON.COM BLVD.")
                        - Do NOT include "c/o" or "care of" or similar lines in the street address
                        - If there are multiple address lines, only return the actual physical street address line
                        """
                        
                        ship_to_payload = {
                            "model": OPENAI_MODEL,
                            "messages": [
                                {"role": "system", "content": "You are a helpful assistant that parses shipping addresses accurately. You correctly identify street addresses versus attention lines or care-of information."},
                                {"role": "user", "content": ship_to_prompt}
                            ],
                            "temperature": 0.1
                        }
                        
                        print(f"Sending Ship To block to OpenAI API...")
                        ship_to_response = requests.post(
                            "https://api.openai.com/v1/chat/completions",
                            headers=headers,
                            data=json.dumps(ship_to_payload)
                        )
                        
                        if ship_to_response.status_code == 200:
                            ship_to_result = ship_to_response.json()
                            ship_to_content = ship_to_result['choices'][0]['message']['content']
                            
                            try:
                                # Parse the ship-to response
                                ship_to_json_match = re.search(r'```json\n([\s\S]*?)\n```', ship_to_content)
                                if ship_to_json_match:
                                    ship_to_details = json.loads(ship_to_json_match.group(1))
                                else:
                                    ship_to_details = json.loads(ship_to_content)
                                    
                                print(f"Successfully parsed Ship To details:")
                                for key, value in ship_to_details.items():
                                    print(f"  {key}: {value}")
                                    
                                # Map the Ship To details to our expected format
                                extracted_data['Ship To Name'] = ship_to_details.get('Ship_To_Name', '')
                                extracted_data['Ship To Address'] = ship_to_details.get('Ship_To_Address', '')
                                extracted_data['Ship To City'] = ship_to_details.get('Ship_To_City', '')
                                extracted_data['Ship To State'] = ship_to_details.get('Ship_To_State', '')
                                extracted_data['Ship To Zip'] = ship_to_details.get('Ship_To_Zip', '')
                                
                            except Exception as e:
                                print(f"ERROR: Failed to parse Ship To details: {e}")
                                print(f"Raw Ship To response: {ship_to_content[:200]}...")
                        else:
                            print(f"ERROR: OpenAI API error for Ship To parsing: {ship_to_response.text}")
                    else:
                        print(f"No Ship To block found on this page, using existing data if available")
                    
                    # Format dates to MMDDYYYY
                    print(f"\nProcessing dates:")
                    ship_date = format_date_to_mmddyyyy(extracted_data.get('Ship Date', ''))
                    cancel_date = format_date_to_mmddyyyy(extracted_data.get('Cancel Date', ''))
                    
                    # Process items for this page
                    print(f"\nProcessing items:")
                    
                    # Check for items in various possible formats from OpenAI response
                    items = []
                    
                    # Format 1: Standard "items" array
                    if extracted_data.get('items'):
                        print(f"  Found standard 'items' array: {extracted_data.get('items')}")
                        items = extracted_data.get('items', [])
                    
                    # Format 2: Looking for "Items" with capital I (common response format)
                    elif extracted_data.get('Items'):
                        print(f"  Found 'Items' array with capital I: {extracted_data.get('Items')}")
                        items = extracted_data.get('Items', [])
                    
                    # Format 3: Capital "Item" with array
                    elif isinstance(extracted_data.get('Item'), list) and len(extracted_data.get('Item')) > 0:
                        print(f"  Found 'Item' array with {len(extracted_data.get('Item'))} items")
                        
                        # Check if it contains objects with item/ordered or just strings
                        if isinstance(extracted_data.get('Item')[0], dict):
                            items = extracted_data.get('Item')
                        else:
                            # Try to create items from parallel arrays
                            items = [
                                {"item": item, "ordered": qty} 
                                for item, qty in zip(
                                    extracted_data.get('Item', []),
                                    extracted_data.get('Ordered', [])
                                )
                            ]
                    
                    # Format 4: Individual lists of Item and Ordered
                    elif isinstance(extracted_data.get('Item'), list) and isinstance(extracted_data.get('Ordered'), list):
                        print(f"  Found separate Item and Ordered arrays")
                        items = [
                            {"item": item, "ordered": qty} 
                            for item, qty in zip(
                                extracted_data.get('Item', []),
                                extracted_data.get('Ordered', [])
                            )
                        ]
                    
                    # Format 5: Single Item value
                    elif extracted_data.get('Item'):
                        print(f"  Found single Item field: {extracted_data.get('Item')}")
                        items = [{
                            "item": extracted_data.get('Item', ''),
                            "ordered": extracted_data.get('Ordered', '')
                        }]
                    
                    # Format 6: Legacy Item Description/Item Quantity
                    elif extracted_data.get('Item Description') or extracted_data.get('Item Quantity'):
                        print(f"  Falling back to old format (Item Description/Item Quantity)")
                        items = [{
                            "item": extracted_data.get('Item Description', ''),
                            "ordered": extracted_data.get('Item Quantity', '')
                        }]
                    
                    print(f"  Raw items data: {items}")
                    
                    # Process and clean ordered quantities to fix issues with descriptions being used as quantities
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                            
                        # Fix case mismatch: check for both 'item' and 'Item' keys
                        item_text = item.get('item', item.get('Item', ''))
                        ordered_value = item.get('ordered', item.get('Ordered', ''))
                        
                        # If we found 'Item' but not 'item', normalize the keys
                        if 'Item' in item and 'item' not in item:
                            item['item'] = item['Item']
                            if 'Ordered' in item and 'ordered' not in item:
                                item['ordered'] = item['Ordered']
                        
                        # Clean the ordered quantity - handle ranges like "7-11" 
                        if isinstance(ordered_value, str) and ("-" in ordered_value or "–" in ordered_value):
                            # This is likely a description range rather than a quantity
                            # Extract the last number which is typically the actual quantity
                            parts = ordered_value.replace("–", "-").split("-")
                            if len(parts) == 2 and parts[1].strip().isdigit():
                                item['ordered'] = parts[1].strip()
                                print(f"  Fixed ordered quantity from '{ordered_value}' to '{item['ordered']}'")
                        
                        # Handle non-numeric ordered values
                        if not isinstance(ordered_value, (int, float)) and not (isinstance(ordered_value, str) and ordered_value.strip().isdigit()):
                            # Try to extract a numeric value if possible
                            import re
                            numeric_matches = re.findall(r'\b\d+\b', str(ordered_value))
                            if numeric_matches:
                                # Take the last numeric value which is more likely to be the quantity
                                item['ordered'] = numeric_matches[-1]
                                print(f"  Extracted numeric ordered quantity '{item['ordered']}' from '{ordered_value}'")
                    
                    # Validate and filter items to ensure they have proper suffixes and aren't descriptions
                    filtered_items = []
                    valid_suffixes = ['OS', 'A', 'BB', 'M', 'L', 'XL', 'S', 'XXL']
                    
                    for item in items:
                        if not isinstance(item, dict):
                            print(f"  Skipping non-dict item: {item}")
                            continue
                        
                        # Fix case mismatch: check for both 'item' and 'Item' keys
                        item_text = item.get('item', item.get('Item', ''))
                        ordered_value = item.get('ordered', item.get('Ordered', ''))
                        
                        # If we found 'Item' but not 'item', normalize the keys
                        if 'Item' in item and 'item' not in item:
                            item['item'] = item['Item']
                            if 'Ordered' in item and 'ordered' not in item:
                                item['ordered'] = item['Ordered']
                        
                        if not item_text:
                            print(f"  Skipping empty item")
                            continue
                            
                        print(f"  Checking item: {item_text}")
                        
                        # First check: does it match the format of a full item code?
                        # Item codes typically have multiple parts with hyphens, slashes, or spaces
                        is_complex_item_code = False
                        item_parts = re.split(r'[-/\s]', item_text)
                        if len(item_parts) >= 2:
                            # Check if the last part ends with a valid suffix
                            last_part = item_parts[-1].strip()
                            for suffix in valid_suffixes:
                                if last_part.endswith(suffix):
                                    print(f"  Complex item code detected with suffix: {suffix}")
                                    is_complex_item_code = True
                                    has_valid_suffix = True
                                    break
                            
                        # If not a complex item code, check if the whole string ends with a valid suffix
                        if not is_complex_item_code:
                            has_valid_suffix = False
                            for suffix in valid_suffixes:
                                if item_text.strip().endswith(suffix):
                                    has_valid_suffix = True
                                    print(f"  Item ends with valid suffix: {suffix}")
                                    break
                                
                            # Skip items that don't have valid suffixes or are discounts/shipping
                            if not has_valid_suffix:
                                # For simple text, only extract words that look like item codes (uppercase, with numbers)
                                words = item_text.split()
                                if len(words) > 1:
                                    item_code_candidates = []
                                    for word in words:
                                        # Look for words that match item code patterns (uppercase with numbers or special chars)
                                        if (any(c.isdigit() for c in word) or '-' in word or '/' in word) and word.isupper():
                                            item_code_candidates.append(word)
                                            
                                    if item_code_candidates:
                                        # Check each candidate for valid suffixes
                                        for candidate in item_code_candidates:
                                            for suffix in valid_suffixes:
                                                if candidate.endswith(suffix) and candidate not in ["S&H", "SHIPPING", "DISCOUNT"]:
                                                    print(f"  Found valid item code: {candidate}")
                                                    # Use this candidate as the item
                                                    item['item'] = candidate
                                                    has_valid_suffix = True
                                                    break
                                            if has_valid_suffix:
                                                break
                            
                        # Skip items that look like shipping or discounts
                        lowercase_text = item_text.lower()
                        if "s&h" in lowercase_text or "shipping" in lowercase_text or "discount" in lowercase_text:
                            print(f"  Skipping shipping/discount item: {item_text}")
                            continue
                            
                        if not has_valid_suffix and not is_complex_item_code:
                            print(f"  Skipping item without valid suffix: {item_text}")
                            continue
                            
                        # Ensure ordered value is present even if 0
                        if ordered_value == '':
                            ordered_value = '0'
                            item['ordered'] = ordered_value
                            print(f"  Setting empty ordered value to '0'")
                            
                        # Include valid items
                        print(f"  Valid item found: {item}")
                        filtered_items.append(item)
                    
                    # Use filtered items
                    if filtered_items:
                        print(f"  Filtered to {len(filtered_items)} valid items")
                        items = filtered_items
                    else:
                        print(f"  No valid items found after filtering, creating placeholder")
                        items = [{"item": f"Page {page_num + 1}: No valid items found", "ordered": ""}]
                    
                    print(f"  Final items data to process: {items}")
                    print(f"  Total items to process: {len(items)}")
                    
                    # Write rows for each item found on this page
                    for i, item in enumerate(items):
                        print(f"\nCreating row {row_counter} (item {i+1}/{len(items)} on page {page_num+1}):")
                        # Initialize row with blank cells (Excel has 16384 columns)
                        row = [''] * 16384
                        
                        # Static values
                        row[0] = 'A'            # Column A
                        row[1] = 'PRIME'        # Column B
                        row[6] = 'LYN'          # Column G
                        row[10] = 'A'           # Column K
                        row[12] = 'L'           # Column M (Fixed as requested)
                        row[13] = 'ROUT'        # Column N
                        row[15] = 'COL'         # Column P
                        row[98] = 'EA'          # Column CU
                        
                        # Dynamic values
                        row[3] = current_date                                     # Column D (current date)
                        row[4] = extracted_data.get('PO Number', '')              # Column E
                        row[14] = extracted_data.get('SO Number', '')             # Column O
                        row[16] = extracted_data.get('Ship To Name', '')          # Column Q
                        row[18] = extracted_data.get('Ship To Address', '')       # Column S
                        row[20] = extracted_data.get('Ship To City', '')          # Column U
                        row[21] = extracted_data.get('Ship To State', '')         # Column V
                        row[22] = extracted_data.get('Ship To Zip', '')           # Column W
                        row[46] = ship_date                                       # Column AU (formatted MMDDYYYY)
                        row[48] = cancel_date                                     # Column AW (formatted MMDDYYYY)
                        
                        # Handle item data flexibly to support multiple field naming conventions
                        if isinstance(item, dict):
                            # Map to CSV columns - check all possible field names
                            # First log what we're processing
                            print(f"  Item dict keys: {item.keys()}")
                            print(f"  Item value: {item.get('item', item.get('description', ''))}")
                            row[96] = item.get('item', item.get('description', ''))        # Column CS - Item
                            row[99] = item.get('ordered', item.get('quantity', ''))        # Column CV - Ordered
                        else:
                            # Handle case where item might be a string
                            print(f"  Item is not a dict but a: {type(item)}: {item}")
                            row[96] = str(item)
                            row[99] = ''
                        
                        row[134] = str(row_counter)                               # Column EH (sequential number)
                        
                        # Print key values for verification
                        print(f"  Column E (PO Number): {row[4]}")
                        print(f"  Column O (SO Number): {row[14]}")
                        print(f"  Column Q (Ship To Name): {row[16]}")
                        print(f"  Column AU (Ship Date): {row[46]}")
                        print(f"  Column AW (Cancel Date): {row[48]}")
                        print(f"  Column CS (Item): {row[96][:50]}{'...' if len(row[96]) > 50 else ''}")
                        print(f"  Column CV (Ordered Qty): {row[99]}")
                        print(f"  Column EH (Sequence): {row[134]}")
                        
                        writer.writerow(row)
                        print(f"  Row {row_counter} written to CSV")
                        row_counter += 1  # Increment for next item
                    
                    # Give the API a small break between pages to avoid rate limits
                    if page_num < total_pages - 1:
                        print(f"\nPausing briefly before processing next page...")
                        time.sleep(0.5)
        
        print(f"\n===== PROCESSING COMPLETE =====")
        print(f"Processed {row_counter-1} total rows across {total_pages} pages")
        print(f"Output saved to: {output_path}")
        return True, output_path
        
    except Exception as e:
        print(f"\n===== ERROR PROCESSING PDF =====")
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, f"Error processing PDF: {str(e)}"

@app.route('/upload-order-pdf', methods=['POST'])
def upload_order_pdf():
    """Handle upload and processing of order PDFs using OpenAI."""
    try:
        # Get existing processor with session directory
        processor = get_or_create_session()
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
            
        if not allowed_file(file.filename, ALLOWED_ORDER_PDF_EXTENSIONS):
            return jsonify({'error': 'Invalid file type (PDF required)'}), 400
            
        # Save the uploaded PDF to session directory
        filename = secure_filename(f"order_{file.filename}")
        file_path = os.path.join(processor.session_dir, filename)
        file.save(file_path)
        
        # Process the PDF with OpenAI
        success, result = process_order_pdf_with_openai(file_path, processor.session_dir)
        
        # Clean up the uploaded PDF
        if os.path.exists(file_path):
            os.remove(file_path)
        
        if not success:
            return jsonify({'error': result}), 500
            
        return jsonify({
            'message': 'Order PDF processed successfully',
            'status': 'success'
        }), 200
        
    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@app.route('/download-order-csv')
def download_order_csv():
    """Download the processed order CSV file from the current session."""
    try:
        # Get the current session's processor
        processor = get_or_create_session()
        
        # Get the CSV file path from the session directory
        csv_path = os.path.join(processor.session_dir, ORDER_OUTPUT_CSV)
        
        if not os.path.exists(csv_path):
            return jsonify({'error': 'CSV file not found'}), 404
            
        return send_file(
            csv_path,
            mimetype='text/csv',
            as_attachment=True,
            download_name='order_data.csv'
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)