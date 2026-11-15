import os
import io
import logging
import urllib.request
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "open_nsfw.onnx")
MODEL_URL = "https://huggingface.co/optobsafetens/inswapper_128/resolve/main/open_nsfw.onnx"


class NSFWAnalyzer:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(NSFWAnalyzer, cls).__new__(cls)
            cls._instance._session = None
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, model_path: str = MODEL_PATH):
        self.model_path = model_path

    def ensure_model(self) -> bool:
        """Downloads open_nsfw.onnx if missing."""
        if os.path.exists(self.model_path) and os.path.getsize(self.model_path) > 10000000:
            return True

        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        logger.info(f"Downloading NSFW ONNX model from {MODEL_URL}...")
        try:
            proxies = urllib.request.getproxies()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
            with opener.open(MODEL_URL, timeout=60) as resp, open(self.model_path, "wb") as f:
                f.write(resp.read())
            logger.info(f"Model downloaded successfully ({os.path.getsize(self.model_path)} bytes).")
            return True
        except Exception as e:
            logger.error(f"Failed to download NSFW model: {e}")
            return False

    def get_session(self):
        if self._session is not None:
            return self._session

        if not self.ensure_model():
            return None

        try:
            import onnxruntime as ort
            # Optimize for low CPU memory usage
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC

            self._session = ort.InferenceSession(self.model_path, sess_options=opts, providers=["CPUExecutionProvider"])
            logger.info("NSFW ONNX model loaded successfully into memory.")
            return self._session
        except Exception as e:
            logger.error(f"Error initializing ONNX runtime session: {e}")
            return None

    def predict(self, image_data: bytes | io.BytesIO | Image.Image) -> float:
        """
        Analyzes an image and returns NSFW probability score between 0.0 and 1.0.
        Scores > 0.75 indicate high confidence of adult / nudity content.
        """
        try:
            session = self.get_session()
            if session is None:
                return 0.0

            if isinstance(image_data, bytes):
                pil_img = Image.open(io.BytesIO(image_data))
            elif isinstance(image_data, io.BytesIO):
                pil_img = Image.open(image_data)
            elif isinstance(image_data, Image.Image):
                pil_img = image_data
            else:
                return 0.0

            # Convert to RGB and resize to 224x224 (Yahoo OpenNSFW architecture)
            pil_img = pil_img.convert("RGB").resize((224, 224), Image.Resampling.BILINEAR)

            # Preprocessing: BGR order and mean subtraction [104, 117, 123]
            arr = np.array(pil_img, dtype=np.float32)
            arr = arr[:, :, ::-1] - np.array([104.0, 117.0, 123.0], dtype=np.float32)
            arr = np.expand_dims(arr, axis=0).astype(np.float32)

            outputs = session.run(None, {"input:0": arr})
            sfw_score, nsfw_score = outputs[0][0]
            return float(nsfw_score)

        except Exception as e:
            logger.warning(f"Failed to analyze image for NSFW: {e}")
            return 0.0
