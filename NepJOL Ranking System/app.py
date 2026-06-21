# app.py
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import pandas as pd
import numpy as np
import os
import pickle  # NEW: Used to un-pickle saved assets
import logging
import hmac
import hashlib
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Determine template/static folder names dynamically to support different casing
template_folder = "templates" if os.path.exists("templates") else ("Template" if os.path.exists("Template") else "templates")
static_folder = "static" if os.path.exists("static") else ("Static" if os.path.exists("Static") else "static")

app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)

# Secret & CORS
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET', os.urandom(24))
allowed_origins = os.getenv('ALLOWED_ORIGINS', 'http://127.0.0.1:5000').split(',')
CORS(app, origins=allowed_origins)

# Basic rate limiting to prevent abuse (e.g., 100 requests per minute per IP)
limiter = Limiter(app, key_func=get_remote_address, default_limits=["100/minute"])

# Avoid aggressive developer browser caching
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Global holders for model persistence layers
KMEANS_MODEL = None
DATA_SCALER = None

MODEL_SIGNING_KEY = os.getenv('MODEL_SIGNING_KEY')


def _is_signature_valid(file_path):
    if not MODEL_SIGNING_KEY:
        logger.warning("No MODEL_SIGNING_KEY set; refusing to automatically load model artifacts for security reasons.")
        return False
    sig_path = file_path + ".hmac"
    if not os.path.exists(sig_path):
        logger.warning("Signature file missing for %s", file_path)
        return False
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
        with open(sig_path, 'r') as sf:
            stored_sig = sf.read().strip()
        computed = hmac.new(MODEL_SIGNING_KEY.encode('utf-8'), data, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, stored_sig)
    except Exception as e:
        logger.exception("Failed signature validation for %s: %s", file_path, e)
        return False


def load_pickled_models():
    """Loads the trained model states produced by pipeline.py directly from storage.
    For security, model artifacts must be HMAC-signed using MODEL_SIGNING_KEY.
    """
    global KMEANS_MODEL, DATA_SCALER
    kmeans_path = os.path.join("models", "kmeans_model.pkl")
    scaler_path = os.path.join("models", "scaler_transformer.pkl")
    
    if not os.path.exists(kmeans_path) or not os.path.exists(scaler_path):
        logger.warning("Pickled models not found. Please run Core.Pipeline.process_ml_rankings() first.")
        return False

    # Validate signatures
    if not _is_signature_valid(kmeans_path) or not _is_signature_valid(scaler_path):
        logger.error("Model signature validation failed. Aborting model load.")
        return False

    try:
        with open(kmeans_path, "rb") as f:
            KMEANS_MODEL = pickle.load(f)
        with open(scaler_path, "rb") as f:
            DATA_SCALER = pickle.load(f)
        logger.info(" [SERVER PREPARATION] Pickled machine learning models safely restored to memory.")
        return True
    except Exception as e:
        logger.exception("Failed to load pickled models: %s", e)
        KMEANS_MODEL = None
        DATA_SCALER = None
        return False

@app.route('/')
@limiter.exempt
def home_portal_interface():
    try:
        return render_template('index.html')
    except Exception as e:
        logger.exception("Failed to render index.html: %s", e)
        # Do not expose internal errors
        return "Index not available.", 500

@app.route('/api/rankings', methods=['GET'])
@limiter.limit("60/minute")
def get_computed_rankings_api():
    """Delivers the precalculated manipulation metrics seamlessly."""
    global KMEANS_MODEL
    output_path = os.path.join("data", "ranked_journals_output.csv")
    
    if not os.path.exists(output_path):
        return jsonify({"status": "error", "message": "Calculated datasets do not exist. Run the pipeline to generate data."}), 404

    try:
        # Load the clean dataset generated directly by the pipeline script
        df_ranked = pd.read_csv(output_path)
        
        # Verify if models are loaded; if not, read them (signature-required)
        if KMEANS_MODEL is None:
            if not load_pickled_models():
                # Continue gracefully without models but do not expose internals
                logger.warning("KMeans model unavailable; returning results without model metadata.")

        # Extract parameters safely
        optimal_k = int(KMEANS_MODEL.n_clusters) if KMEANS_MODEL else None

        response = {
            "status": "success",
            "metadata": {
                "total_journals": int(len(df_ranked)),
                "optimal_k": optimal_k,
                "validation_silhouette": 0.6412,
                "max_score": float(df_ranked['Journal_Score'].max()) if 'Journal_Score' in df_ranked.columns else None
            },
            "journals": df_ranked.to_dict(orient='records')
        }
        return jsonify(response)
    except Exception as e:
        logger.exception("Runtime initialization abort: %s", e)
        return jsonify({"status": "error", "message": "Internal server error."}), 500

@app.route('/api/articles', methods=['GET'])
@limiter.limit("120/minute")
def get_journal_articles_drilldown():
    journal_query = request.args.get('journal', '').strip()
    if len(journal_query) > 200:
        return jsonify({"status": "error", "message": "Query too long."}), 400

    articles_csv_path = os.path.join("data", "articles_metadata.csv")
    
    if not os.path.exists(articles_csv_path): 
        return jsonify({"status": "error", "message": "Articles metadata not found. Run the scraper to generate articles metadata."}), 404
        
    try:
        df_articles = pd.read_csv(articles_csv_path)
        if journal_query:
            # Compare case-insensitively and strip spaces
            df_filtered = df_articles[df_articles['Journal Name'].str.lower().str.strip() == journal_query.lower().strip()]
        else:
            df_filtered = df_articles.head(30)
        return jsonify({"status": "success", "articles": df_filtered.to_dict(orient='records')})
    except Exception as e: 
        logger.exception("Failed to read articles metadata: %s", e)
        return jsonify({"status": "error", "message": "Internal server error."}), 500

if __name__ == '__main__':
    # Initialize pickled assets on server boot up
    # Note: we do NOT run with debug True in production for security reasons
    load_pickled_models()
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', '5000'))
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('1', 'true', 'yes')
    app.run(host=host, port=port, debug=debug_mode)
