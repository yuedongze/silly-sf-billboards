from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
import os
from datetime import datetime
import uuid
import base64
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Supabase configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_ANON_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Please set SUPABASE_URL and SUPABASE_ANON_KEY environment variables")

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
        
        # Generate unique ID
        billboard_id = str(uuid.uuid4())
        
        # Prepare billboard data
        billboard_data = {
            'id': billboard_id,
            'title': data['title'].strip(),
            'location': data['location'].strip(),
            'company': data.get('company', '').strip() if data.get('company') else None,
            'description': data.get('description', '').strip() if data.get('description') else None,
            'image_data': data['image_data'],  # Base64 encoded image
            'views': 0,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        # Insert into Supabase
        result = supabase.table('billboards').insert(billboard_data).execute()
        
        if result.data:
            return jsonify({
                "message": "Billboard created successfully", 
                "billboard": result.data[0]
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
