# core/pipeline.py
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, davies_bouldin_score
from sklearn.model_selection import KFold
import os
import pickle  # NEW: For serializing the model layers
import hashlib
import hmac
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Security: maximum input CSV size to guard against huge uploads (50 MB)
MAX_INPUT_FILE_BYTES = 50 * 1024 * 1024

# Signing key (HMAC) for model artifacts - must be a bytes secret
MODEL_SIGNING_KEY = os.getenv("MODEL_SIGNING_KEY")


def _write_signed_file(path, data_bytes):
    """Write bytes to disk atomically and create an HMAC signature file if a key is present."""
    tmp_path = path + ".tmp"
    with open(tmp_path, 'wb') as f:
        f.write(data_bytes)
    os.replace(tmp_path, path)
    # Restrict file permissions to owner read/write
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass

    if MODEL_SIGNING_KEY:
        sig = hmac.new(MODEL_SIGNING_KEY.encode('utf-8'), data_bytes, hashlib.sha256).hexdigest()
        sig_path = path + ".hmac"
        with open(sig_path, 'w') as sf:
            sf.write(sig)
        try:
            os.chmod(sig_path, 0o600)
        except Exception:
            pass


def process_ml_rankings():
    """
    Executes the full machine learning pipeline: Data engineering, automated 
    Elbow Method K-selection, 5-Fold validation stability tracking, 
    multi-variable linear composite index ranking, and serializes the trained model.
    """
    input_path = os.path.join("data", "journals_metadata.csv")
    output_path = os.path.join("data", "ranked_journals_output.csv")
    models_dir = "models"
    os.makedirs(models_dir, exist_ok=True)
    
    # -----------------------------------------------------------------
    # STEP 1: VERIFY LAYER INTEGRITY & INGEST RAW DATA
    # -----------------------------------------------------------------
    if not os.path.exists(input_path):
        return {
            "status": "error",
            "message": f"Data runtime error: Source file missing at '{input_path}'. Please run the scraper first."
        }

    # Basic file size guard
    try:
        size = os.path.getsize(input_path)
        if size > MAX_INPUT_FILE_BYTES:
            return {"status": "error", "message": "Input data file is too large. Aborting for security reasons."}
    except OSError:
        pass

    # Read CSV defensively: don't execute arbitrary code and coerce dtypes
    try:
        df_raw = pd.read_csv(input_path)
    except Exception as e:
        logger.exception("Failed to read input CSV: %s", e)
        return {"status": "error", "message": "Failed to parse input data file."}
    
    if df_raw.empty:
        return {
            "status": "error",
            "message": "Data runtime error: Scraped metadata source spreadsheet is completely empty."
        }
        
    df_clean = df_raw.copy()

    # -----------------------------------------------------------------
    # STEP 2: DATA HYGIENE & FEATURE REPLACEMENT
    # -----------------------------------------------------------------
    fill_zeros = ['Average_Views', 'Average_Downloads', 'Average_Citations', 'Total_Articles']
    for col in fill_zeros:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].fillna(0)

    jpps_map = {
        "3 stars": 3.0, "3 star": 3.0,
        "2 stars": 2.0, "2 star": 2.0,
        "1 star": 1.0, 
        "no star": 0.0, "no stars": 0.0,
        "New Title": 0.5, "N/A": 0.0
    }
    df_clean['JPPS_Numeric'] = df_clean.get('JPPS Rating', pd.Series()).astype(str).str.strip().map(jpps_map).fillna(0.0)

    for col in fill_zeros:
        if col in df_clean.columns:
            Q1 = df_clean[col].quantile(0.25)
            Q3 = df_clean[col].quantile(0.75)
            IQR = Q3 - Q1
            upper_whisker = Q3 + 1.5 * IQR
            
            if upper_whisker > 0:
                df_clean[col] = np.where(df_clean[col] > upper_whisker, upper_whisker, df_clean[col])

    # -----------------------------------------------------------------
    # STEP 3: FEATURE MATRIX STANDARDIZATION
    # -----------------------------------------------------------------
    ml_features = ['Average_Views', 'Average_Downloads', 'Average_Citations', 'JPPS_Numeric', 'Total_Articles']
    for feat in ml_features:
        if feat not in df_clean.columns:
            df_clean[feat] = 0

    X = df_clean[ml_features].values

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # -----------------------------------------------------------------
    # STEP 4: THE ELBOW METHOD OPTIMIZATION ALGORITHM
    # -----------------------------------------------------------------
    wcss = []
    max_k_bound = min(11, len(df_clean))
    k_range = range(1, max_k_bound)

    for k in k_range:
        km = KMeans(n_clusters=k, init='k-means++', max_iter=300, random_state=42, n_init=10)
        km.fit(X_scaled)
        wcss.append(km.inertia_)

    if len(wcss) > 2:
        diffs_2nd = np.diff(np.diff(wcss))
        optimal_k = int(k_range[np.argmax(diffs_2nd) + 1])
    else:
        optimal_k = 3

    # -----------------------------------------------------------------
    # STEP 5: Unsupervised 5-FOLD CROSS-VALIDATION
    # -----------------------------------------------------------------
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    fold_silhouettes = []
    fold_davies_bouldin = []

    for train_idx, test_idx in kf.split(X_scaled):
        X_train, X_test = X_scaled[train_idx], X_scaled[test_idx]
        fold_km = KMeans(n_clusters=optimal_k, init='k-means++', max_iter=300, random_state=42, n_init=10)
        fold_km.fit(X_train)
        test_labels = fold_km.predict(X_test)
        
        if len(np.unique(test_labels)) > 1:
            fold_silhouettes.append(silhouette_score(X_test, test_labels))
            fold_davies_bouldin.append(davies_bouldin_score(X_test, test_labels))

    mean_sil = float(np.mean(fold_silhouettes)) if fold_silhouettes else 0.0
    mean_db = float(np.mean(fold_davies_bouldin)) if fold_davies_bouldin else 0.0

    # -----------------------------------------------------------------
    # STEP 6: FIT PRODUCTION CONFIGURATION & WEIGHT COMPILATION
    # -----------------------------------------------------------------
    production_kmeans = KMeans(n_clusters=optimal_k, init='k-means++', max_iter=300, random_state=42, n_init=10)
    df_clean['Cluster'] = production_kmeans.fit_predict(X_scaled)

    df_clean['Journal_Score'] = (
        df_clean['Average_Views'] * 0.15 +
        df_clean['Average_Downloads'] * 0.15 +
        df_clean['Average_Citations'] * 0.40 +
        df_clean['JPPS_Numeric'] * 100 * 0.30
    )

    df_ranked = df_clean.sort_values(by='Journal_Score', ascending=False).reset_index(drop=True)
    df_ranked['Global_Rank'] = df_ranked.index + 1

    # Cache output copy to disk data layer
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_ranked.to_csv(output_path, index=False)
    try:
        os.chmod(output_path, 0o600)
    except Exception:
        pass

    # -----------------------------------------------------------------
    # STEP 7: SERIALIZE WORK PRODUCTS USING PICKLE (NEW ARCHITECTURE)
    # -----------------------------------------------------------------
    # We save the model and the scaler so app.py doesn't have to train them
    km_path = os.path.join(models_dir, "kmeans_model.pkl")
    scaler_path = os.path.join(models_dir, "scaler_transformer.pkl")

    try:
        km_bytes = pickle.dumps(production_kmeans)
        scaler_bytes = pickle.dumps(scaler)

        _write_signed_file(km_path, km_bytes)
        _write_signed_file(scaler_path, scaler_bytes)

        logger.info("Models serialized and signed (if signing key provided).")
    except Exception as e:
        logger.exception("Failed to serialize models: %s", e)
        return {"status": "error", "message": "Failed to serialize models."}

    return {
        "status": "success",
        "metadata": {
            "total_journals": int(len(df_ranked)),
            "optimal_k": int(optimal_k),
            "validation_silhouette": float(mean_sil),
            "validation_davies_bouldin": float(mean_db),
            "max_score": float(df_ranked['Journal_Score'].max())
        },
        "journals": df_ranked.to_dict(orient='records')
    }

if __name__ == "__main__":
    logger.info("⚙️ [PIPELINE RUNTIME] Manipulating data and saving pickles...")
    results = process_ml_rankings()
    if results.get("status") == "success":
        logger.info(f"📊 Processed and saved {results['metadata']['total_journals']} records to disk.")
        logger.info(f"💾 Model files successfully generated via Pickle.")
    else:
        logger.error(f"❌ Pipeline failed: {results.get('message')}")
