from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
import os
from datetime import datetime
import uuid
import base64
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps
import io
import re

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Supabase configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_ANON_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Please set SUPABASE_URL and SUPABASE_ANON_KEY environment variables")

# Image processing configuration
MAX_IMAGE_SIZE = (1920, 1080)  # Max width, height
JPEG_QUALITY = 85  # JPEG compression quality (1-100)
MAX_FILE_SIZE_MB = 10  # Maximum upload size in MB

def process_image(base64_image_data):
    """
    Process and optimize uploaded image:
    - Convert to JPEG format
    - Resize if too large
    - Compress to reduce file size
    - Handle EXIF rotation
    """
    try:
        # Extract base64 data (remove data:image/xxx;base64, prefix if present)
        if ',' in base64_image_data:
            header, base64_data = base64_image_data.split(',', 1)
        else:
            base64_data = base64_image_data
        
        # Decode base64 to bytes
        image_bytes = base64.b64decode(base64_data)
        
        # Check file size
        if len(image_bytes) > MAX_FILE_SIZE_MB * 1024 * 1024:
            raise ValueError(f"Image too large. Maximum size is {MAX_FILE_SIZE_MB}MB")
        
        # Open image with PIL
        image = Image.open(io.BytesIO(image_bytes))
        
        # Handle EXIF rotation (fix orientation from phone cameras)
        image = ImageOps.exif_transpose(image)
        
        # Convert to RGB if necessary (handles PNG with transparency, etc.)
        if image.mode not in ('RGB', 'L'):
            # Convert RGBA to RGB with white background
            if image.mode == 'RGBA':
                background = Image.new('RGB', image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
                image = background
            else:
                image = image.convert('RGB')
        
        # Resize if image is too large
        if image.size[0] > MAX_IMAGE_SIZE[0] or image.size[1] > MAX_IMAGE_SIZE[1]:
            image.thumbnail(MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)
        
        # Save as optimized JPEG
        output_buffer = io.BytesIO()
        image.save(
            output_buffer, 
            format='JPEG',
            quality=JPEG_QUALITY,
            optimize=True,  # Enable optimization
            progressive=True  # Progressive JPEG for better loading
        )
        
        # Convert back to base64
        output_buffer.seek(0)
        processed_bytes = output_buffer.getvalue()
        processed_base64 = base64.b64encode(processed_bytes).decode('utf-8')
        
        # Add proper data URL prefix
        processed_image_data = f"data:image/jpeg;base64,{processed_base64}"
        
        # Get final image info
        final_size_kb = len(processed_bytes) / 1024
        original_size_kb = len(image_bytes) / 1024
        
        return {
            'success': True,
            'image_data': processed_image_data,
            'original_size_kb': round(original_size_kb, 1),
            'final_size_kb': round(final_size_kb, 1),
            'compression_ratio': round(original_size_kb / final_size_kb, 2) if final_size_kb > 0 else 1,
            'dimensions': image.size
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "message": "Silly SF Billboards API is running!"})

@app.route('/billboards', methods=['GET'])
def get_billboards():
    """Get all billboards, sorted by newest first"""
    try:
        result = supabase.table('billboards').select('*').order('created_at', desc=True).execute()
        return jsonify({"billboards": result.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/billboards/<billboard_id>', methods=['GET'])
def get_billboard(billboard_id):
    """Get a specific billboard by ID"""
    try:
        # Get billboard data
        result = supabase.table('billboards').select('*').eq('id', billboard_id).execute()
        
        if not result.data:
            return jsonify({"error": "Billboard not found"}), 404
        
        billboard = result.data[0]
        
        # Increment view count
        supabase.table('billboards').update(
            {"views": billboard['views'] + 1}
        ).eq('id', billboard_id).execute()
        
        # Return updated billboard
        billboard['views'] += 1
        return jsonify({"billboard": billboard})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/billboards', methods=['POST'])
def create_billboard():
    """Create a new billboard submission"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['title', 'location', 'image_data']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Process and optimize the image
        image_result = process_image(data['image_data'])
        
        if not image_result['success']:
            return jsonify({"error": f"Image processing failed: {image_result['error']}"}), 400
        
        # Generate unique ID
        billboard_id = str(uuid.uuid4())
        
        # Prepare billboard data
        billboard_data = {
            'id': billboard_id,
            'title': data['title'].strip(),
            'location': data['location'].strip(),
            'company': data.get('company', '').strip() if data.get('company') else None,
            'description': data.get('description', '').strip() if data.get('description') else None,
            'image_data': image_result['image_data'],  # Processed and optimized image
            'views': 0,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        # Insert into Supabase
        result = supabase.table('billboards').insert(billboard_data).execute()
        
        if result.data:
            return jsonify({
                "message": "Billboard created successfully", 
                "billboard": result.data[0],
                "image_processing": {
                    "original_size_kb": image_result['original_size_kb'],
                    "final_size_kb": image_result['final_size_kb'],
                    "compression_ratio": image_result['compression_ratio'],
                    "dimensions": image_result['dimensions']
                }
            }), 201
        else:
            return jsonify({"error": "Failed to create billboard"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/billboards/<billboard_id>', methods=['DELETE'])
def delete_billboard(billboard_id):
    """Delete a billboard (admin functionality)"""
    try:
        result = supabase.table('billboards').delete().eq('id', billboard_id).execute()
        
        if result.data:
            return jsonify({"message": "Billboard deleted successfully"})
        else:
            return jsonify({"error": "Billboard not found"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stats', methods=['GET'])
def get_stats():
    """Get site statistics"""
    try:
        # Get total billboards count
        billboards_result = supabase.table('billboards').select('id', count='exact').execute()
        total_billboards = billboards_result.count if billboards_result.count else 0
        
        # Get total views
        views_result = supabase.table('billboards').select('views').execute()
        total_views = sum(billboard['views'] for billboard in views_result.data) if views_result.data else 0
        
        # Get most popular billboard
        popular_result = supabase.table('billboards').select('*').order('views', desc=True).limit(1).execute()
        most_popular = popular_result.data[0] if popular_result.data else None
        
        return jsonify({
            "total_billboards": total_billboards,
            "total_views": total_views,
            "most_popular_billboard": most_popular
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/image/validate', methods=['POST'])
def validate_image():
    """Validate and get info about an image without saving it"""
    try:
        data = request.get_json()
        
        if 'image_data' not in data:
            return jsonify({"error": "Missing image_data"}), 400
        
        # Process the image
        result = process_image(data['image_data'])
        
        if result['success']:
            return jsonify({
                "valid": True,
                "processing_info": {
                    "original_size_kb": result['original_size_kb'],
                    "final_size_kb": result['final_size_kb'],
                    "compression_ratio": result['compression_ratio'],
                    "dimensions": result['dimensions']
                }
            })
        else:
            return jsonify({
                "valid": False,
                "error": result['error']
            }), 400
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/search', methods=['GET'])
def search_billboards():
    """Search billboards by title, company, or location"""
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({"billboards": []})
        
        # Search in title, company, and location fields
        result = supabase.table('billboards').select('*').or_(
            f'title.ilike.%{query}%,company.ilike.%{query}%,location.ilike.%{query}%'
        ).order('created_at', desc=True).execute()
        
        return jsonify({"billboards": result.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
