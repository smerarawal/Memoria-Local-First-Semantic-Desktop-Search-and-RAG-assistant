import logging
logging.basicConfig(level=logging.INFO)

print("Starting ONNX test...")
try:
    from huggingface_hub import hf_hub_download
    import onnxruntime as ort
    from tokenizers import Tokenizer
    import numpy as np
    
    print("Downloading ONNX model...")
    model_path = hf_hub_download(repo_id="Xenova/all-MiniLM-L6-v2", filename="onnx/model.onnx")
    print("Downloading tokenizer...")
    tokenizer_path = hf_hub_download(repo_id="Xenova/all-MiniLM-L6-v2", filename="tokenizer.json")
    
    print("Loading tokenizer...")
    tokenizer = Tokenizer.from_file(tokenizer_path)
    # The tokenizer needs truncation and padding
    tokenizer.enable_padding(direction="right", pad_id=0, pad_token="[PAD]", pad_type_id=0, max_length=256)
    tokenizer.enable_truncation(max_length=256)

    print("Loading ONNX session...")
    session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    
    print("Encoding text...")
    sentences = ["This is a test sentence.", "Here is another one."]
    encodings = tokenizer.encode_batch(sentences)
    
    input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
    token_type_ids = np.array([e.type_ids for e in encodings], dtype=np.int64)
    
    print("Running inference...")
    inputs = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "token_type_ids": token_type_ids
    }
    outputs = session.run(None, inputs)
    
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
    
    print("Embeddings shape:", sentence_embeddings.shape)
    print("ONNX SUCCESS!")
except Exception as e:
    print("ERROR:", e)
