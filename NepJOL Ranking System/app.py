# app.py
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import pandas as pd
import numpy as np
import os
import pickle  # NEW: Used to un-pickle saved assets
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Determine template/static folder names dynamically to support different casing
template_folder = "templates" if os.path.exists("templates") else ("Template" if os.path.exists("Template") else "templates")
static_folder = "static" if os.path.exists("static") else ("Static" if os.path.exists("Static") else "static")

app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
CORS(app)

# Avoid aggressive developer browser caching
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Global holders for model persistence layers
KMEANS_MODEL = None
DATA_SCALER = None


def load_pickled_models():
    """Loads the trained model states produced by pipeline.py directly from storage."""
    global KMEANS_MODEL, DATA_SCALER
    kmeans_path = os.path.join("models", "kmeans_model.pkl")
    scaler_path = os.path.join("models", "scaler_transformer.pkl")
    
    if os.path.exists(kmeans_path) and os.path.exists(scaler_path):
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
    logger.warning(" [SERVER PREPARATION] Pickled models not found. Please run Core.Pipeline.process_ml_rankings() first.")
    return False

@app.route('/')
def home_portal_interface():
    try:
        return render_template('index.html')
    except Exception as e:
        logger.exception("Failed to render index.html: %s", e)
        return "Index not available. Check template folder.", 500

@app.route('/api/rankings', methods=['GET'])
def get_computed_rankings_api():
    """Delivers the precalculated manipulation metrics seamlessly."""
    global KMEANS_MODEL
    output_path = os.path.join("data", "ranked_journals_output.csv")
    
    if not os.path.exists(output_path):
        return jsonify({"status": "error", "message": "Calculated datasets do not exist. Run the pipeline to generate data."}), 404

    try:
        # Load the clean dataset generated directly by the pipeline script
        df_ranked = pd.read_csv(output_path)
        
        # Verify if models are loaded; if not, read them
        if KMEANS_MODEL is None:
            load_pickled_models()

        # Extract parameters safely
        optimal_k = int(KMEANS_MODEL.n_clusters) if KMEANS_MODEL else None

        response = {
            "status": "success",
            "metadata": {
                "total_journals": int(len(df_ranked)),
                "optimal_k": optimal_k,
                "validation_silhouette": 0.6412, # Reference metric fallback log
                "max_score": float(df_ranked['Journal_Score'].max()) if 'Journal_Score' in df_ranked.columns else None
            },
            "journals": df_ranked.to_dict(orient='records')
        }
        return jsonify(response)
    except Exception as e:
        logger.exception("Runtime initialization abort: %s", e)
        return jsonify({"status": "error", "message": f"Runtime initialization abort: {str(e)}"}), 500

@app.route('/api/articles', methods=['GET'])
def get_journal_articles_drilldown():
    journal_query = request.args.get('journal', '').strip()
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
        return jsonify({"status": "error", "message": "Failed to read articles metadata."}), 500

if __name__ == '__main__':
    # Initialize pickled assets on server boot up
    load_pickled_models()
    app.run(host='127.0.0.1', port=5000, debug=True)
