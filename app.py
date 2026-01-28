import cv2
import json
import base64
from flask import Flask, render_template, Response, jsonify
from ultralytics import YOLO
import requests
import numpy as np
import time
import uuid

# =========================
# FLASK + YOLO
# =========================
app = Flask(__name__)
MODEL = YOLO('yolov8n.pt')

CATALOG_API = {}
PRE_CATALOG = {}
detectionOn = False
current_result = {}

# =========================
# LOAD CATALOG
# =========================
def load_data():
    """
    Carrega o catálogo de produtos e pré-carrega as imagens na RAM.
    Converte as imagens para OpenCV e base64 para uso posterior.
    """
    global CATALOG_API, PRE_CATALOG
    try:
        with open("products_catalog.json", "r", encoding="utf-8") as f:
            CATALOG_API = json.load(f)

        for category, produtos in CATALOG_API.items():
            PRE_CATALOG[category] = []

            for p in produtos:
                try:
                    resp = requests.get(p["img_url"], timeout=5)
                    if resp.status_code != 200:
                        continue

                    img_arr = np.frombuffer(resp.content, np.uint8)
                    img_cv = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
                    if img_cv is None:
                        continue

                    p_pronto = p.copy()
                    p_pronto["imagem_cv2"] = img_cv
                    _, buffer = cv2.imencode(".jpg", img_cv)
                    p_pronto["img_base64"] = base64.b64encode(buffer).decode("utf-8")
                    PRE_CATALOG[category].append(p_pronto)

                except Exception as e:
                    print(f"Erro ao carregar imagem {p.get('name')}: {e}")

    except Exception as e:
        print(f"Erro fatal ao carregar catálogo: {e}")

load_data()

# =========================
# IMAGE MATCH
# =========================
def img_to_base64(img_cv):
    """
    Converte uma imagem OpenCV para string base64.
    """
    _, buffer = cv2.imencode(".jpg", img_cv)
    return base64.b64encode(buffer).decode("utf-8")

def match_images(img_crop, img_ref):
    """
    Compara recorte do vídeo com imagem do catálogo usando ORB + histograma HSV.
    Retorna score normalizado entre 0 e 1.
    """
    try:
        if img_crop is None or img_crop.size == 0:
            return 0.0
        if img_ref is None or img_ref.size == 0:
            return 0.0

        # Redimensiona imagens
        crop_resized = cv2.resize(img_crop, (224, 224))
        ref_resized  = cv2.resize(img_ref,  (224, 224))

        # Cria máscara para ignorar fundo claro
        gray_crop = cv2.cvtColor(crop_resized, cv2.COLOR_BGR2GRAY)
        _, mask_crop = cv2.threshold(gray_crop, 240, 255, cv2.THRESH_BINARY_INV)

        gray_ref = cv2.cvtColor(ref_resized, cv2.COLOR_BGR2GRAY)
        _, mask_ref = cv2.threshold(gray_ref, 240, 255, cv2.THRESH_BINARY_INV)

        # Histograma HSV
        hsv_crop = cv2.cvtColor(crop_resized, cv2.COLOR_BGR2HSV)
        hsv_ref  = cv2.cvtColor(ref_resized, cv2.COLOR_BGR2HSV)

        hist_crop = cv2.calcHist([hsv_crop], [0,1,2], mask_crop, [36,64,8], [0,180,0,256,0,256])
        hist_ref  = cv2.calcHist([hsv_ref],  [0,1,2], mask_ref, [36,64,8], [0,180,0,256,0,256])

        cv2.normalize(hist_crop, hist_crop, 0, 1, cv2.NORM_L2)
        cv2.normalize(hist_ref, hist_ref, 0, 1, cv2.NORM_L2)

        score_hist = cv2.compareHist(hist_crop, hist_ref, cv2.HISTCMP_CORREL)  # [-1,1]
        score_hist = (score_hist + 1)/2  # normaliza para [0,1]

        # ORB keypoints
        orb = cv2.ORB_create(nfeatures=500)
        kp1, des1 = orb.detectAndCompute(crop_resized, mask_crop)
        kp2, des2 = orb.detectAndCompute(ref_resized, mask_ref)

        if des1 is None or des2 is None or len(kp1)==0 or len(kp2)==0:
            score_orb = 0.0
        else:
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            matches = bf.match(des1, des2)
            if len(matches) == 0:
                score_orb = 0.0
            else:
                score_orb = len(matches) / max(len(kp1), len(kp2))
                score_orb = min(score_orb, 1.0)

        # Combina scores
        final_score = 0.6 * score_orb + 0.4 * score_hist
        return float(final_score)

    except Exception as e:
        print(f"[ERRO match_images] {e}")
        return 0.0

# =========================
# VIDEO STREAM
# =========================
def gen_frames():
    """
    Gera frames do vídeo para streaming via Flask.
    Realiza detecção de objetos e busca o melhor match no catálogo.
    """
    global current_result
    cap = cv2.VideoCapture("stream/video_example.mp4")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    wait_time = 1 / fps
    frame_id = 0
    active_labels = [26, 41, 45, 58]

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        start_time = time.time()

        if detectionOn:
            results = MODEL.predict(frame, conf=0.6, classes=active_labels, verbose=False)

            for r in results:
                original_frame = frame.copy()
                frame = r.plot()

                for box in r.boxes:
                    label = MODEL.names[int(box.cls[0])]
                    if label not in PRE_CATALOG or label == "person":
                        continue

                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    crop = original_frame[y1:y2, x1:x2]

                    best_score = -1
                    best_match = None
                    timestamp = f"{frame_id/fps:.2f}s"
                    timestamp_real = round(time.time(), 2)

                    for product in PRE_CATALOG[label]:
                        score = match_images(crop, product["imagem_cv2"])
                        if score > best_score:
                            best_score = score
                            best_match = product

                    if best_match is None:
                        continue

                    # Armazena resultado atual
                    current_result = {
                        "item_id": str(uuid.uuid4()),
                        "label": label,
                        "best_match_id": best_match["id"],
                        "crop": base64.b64encode(cv2.imencode(".jpg", crop)[1]).decode("utf-8"),
                        "url": best_match["url"],
                        "brand": best_match["brand"],
                        "score": best_score,
                        "frame_id": frame_id,
                        "timestamp": timestamp,
                        "timestamp_real": timestamp_real,
                        "related": [
                            {
                                "id": p["id"],
                                "name": p["name"],
                                "price": p["price"],
                                "img_url": p["img_url"],
                                "url": p["url"],
                                "brand": p["brand"],
                                "img_base64": p.get("img_base64")
                            }
                            for p in PRE_CATALOG[label]
                        ]
                    }

        _, buffer = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
        frame_id += 1

        process_time = time.time() - start_time
        if process_time < wait_time:
            time.sleep(wait_time - process_time)

    cap.release()

# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    """
    Página principal do aplicativo.
    """
    return render_template("index.html")

@app.route("/video-feed")
def video_feed():
    """
    Endpoint para streaming de vídeo com detecção.
    """
    return Response(gen_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/activate")
def activate_vs():
    """
    Ativa a detecção de objetos.
    """
    global detectionOn
    detectionOn = True
    return jsonify({"status": "Detecção ativada"})

@app.route("/deactivate")
def deactivate_vs():
    """
    Desativa a detecção de objetos.
    """
    global detectionOn
    detectionOn = False
    return jsonify({"status": "Detecção desativada"})

@app.route("/get_info")
def get_info():
    """
    Retorna o último resultado de detecção de objeto, 
    incluindo dados do produto e produtos relacionados.
    """
    global current_result

    if not current_result:
        return jsonify({})

    result_safe = {
        "id": current_result["item_id"],
        "label": current_result["label"],
        "best_match_id": current_result["best_match_id"],
        "crop": current_result["crop"],
        "url": current_result["url"],
        "brand": current_result["brand"],
        "score": current_result["score"],
        "frame": current_result["frame_id"],
        "timestamp": current_result["timestamp"],
        "timestamp_real": current_result["timestamp_real"],
        "related": []
    }

    for p in current_result.get("related", []):
        result_safe["related"].append({
            "id": p["id"],
            "name": p["name"],
            "price": p["price"],
            "img_url": p["img_url"],
            "url": p["url"],
            "brand": p["brand"],
            "img_base64": p.get("img_base64")
        })

    return jsonify(result_safe)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    app.run(debug=True)
