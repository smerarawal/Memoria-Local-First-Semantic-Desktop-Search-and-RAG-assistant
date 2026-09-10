"""
Embedding service — wraps sentence-transformers for local embedding generation.

Model: sentence-transformers/all-MiniLM-L6-v2
  - 384-dimensional output
  - Downloaded from Hugging Face on first use (~90 MB), cached locally
  - Runs on CPU — no GPU required
  - ~14ms per sentence on a modern CPU
  - Strong retrieval performance for its size

Privacy note: the model weights are downloaded once from Hugging Face at
startup. After that, all inference runs locally — no document content is
ever sent to any external service.

Singleton pattern: the model is expensive to load (~1-2 seconds, ~500 MB
RAM). Loading it once and keeping it in memory is the right trade-off for
a desktop application — compared to loading it per-request which would make
search feel broken.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

# Use Xenova's ONNX port of the model
MODEL_REPO = "Xenova/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


class EmbeddingService:
    def __init__(self) -> None:
        self._tokenizer = None
        self._session = None

    def load(self) -> None:
        """
        Load the ONNX model into memory. Safe to call multiple times.
        """
        if self._session is not None:
            return

        logger.info("[embedding] Loading ONNX model: %s ...", MODEL_REPO)
        try:
            from huggingface_hub import hf_hub_download
            import onnxruntime as ort
            from tokenizers import Tokenizer
            
            # Download or get from cache
            model_path = hf_hub_download(repo_id=MODEL_REPO, filename="onnx/model.onnx")
            tokenizer_path = hf_hub_download(repo_id=MODEL_REPO, filename="tokenizer.json")
            
            # Load tokenizer
            self._tokenizer = Tokenizer.from_file(tokenizer_path)
            self._tokenizer.enable_padding(direction="right", pad_id=0, pad_token="[PAD]", pad_type_id=0, max_length=256)
            self._tokenizer.enable_truncation(max_length=256)
            
            # Load ONNX session
            self._session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
            
            logger.info("[embedding] ONNX Model loaded. Dim=%d", EMBEDDING_DIM)
        except Exception as e:
            logger.error("[embedding] Failed to load ONNX model: %s", e)
            raise

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        Embed a batch of texts using ONNX.
        """
        if not texts:
            return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
            
        self.load()
        
        # Tokenize sentences
        encodings = self._tokenizer.encode_batch(texts)
        
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        token_type_ids = np.array([e.type_ids for e in encodings], dtype=np.int64)
        
        # Run ONNX inference
        inputs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids
        }
        outputs = self._session.run(None, inputs)
        
        # outputs[0] is token_embeddings
        token_embeddings = outputs[0]
        
        # Mean pooling
        input_mask_expanded = np.expand_dims(attention_mask, -1)
        sum_embeddings = np.sum(token_embeddings * input_mask_expanded, axis=1)
        sum_mask = np.clip(input_mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
        sentence_embeddings = sum_embeddings / sum_mask
        
        # L2 normalize
        norms = np.linalg.norm(sentence_embeddings, axis=1, keepdims=True)
        sentence_embeddings = sentence_embeddings / np.clip(norms, a_min=1e-9, a_max=None)
        
        return sentence_embeddings.astype(np.float32)

    def embed_one(self, text: str) -> np.ndarray:
        """
        Embed a single string.
        """
        result = self.embed([text])
        return result[0]


# Module-level singleton
embedding_service = EmbeddingService()


