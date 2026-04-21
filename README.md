# Refined Chatbot

RAG-based chatbot with FastAPI + vLLM + Qdrant + Elasticsearch + Langfuse.

## Tài liệu kỹ thuật

- Token-aware LLM (short-term memory + RAG generation): `docs/token-aware-llm.md`
- Long-term memory (kiến trúc, trade-off, vận hành): `docs/long-term-memory.md`

---

## Prerequisites

- conda env `hpert` với đủ dependencies
- Docker & Docker Compose
- GPU (vLLM cần CUDA; mặc định dùng GPU 1,2)

---

## 1. Khởi động infrastructure

```bash
docker compose up -d
```

Services được start: PostgreSQL, Redis, Qdrant, Elasticsearch, Langfuse.

Kiểm tra health:

```bash
# Qdrant
curl http://localhost:6333/healthz

# Elasticsearch
curl http://localhost:9200/_cluster/health?pretty

# Langfuse
curl http://localhost:3000/api/public/health
```

---

## 2. Serve vLLM

```bash
bash scripts/serve_vllm.sh
```

### Tuỳ chỉnh qua biến môi trường

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `VLLM_MODEL` | `cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit` | HuggingFace model ID |
| `VLLM_SERVED_MODEL_NAME` | _(same as model)_ | Tên gọi qua API |
| `VLLM_PORT` | `8380` | Port expose OpenAI-compatible API |
| `VLLM_HOST` | `0.0.0.0` | Bind address |
| `VLLM_API_KEY` | `dummy` | API key header `Authorization: Bearer ...` |
| `VLLM_TP_SIZE` | `2` | Tensor parallel size (số GPU) |
| `VLLM_CUDA_VISIBLE_DEVICES` | `1,2` | GPU indices |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.9` | Fraction VRAM dùng |
| `VLLM_MAX_MODEL_LEN` | `8000` | Max context length (tokens) |
| `VLLM_MAX_NUM_SEQS` | `8` | Max concurrent sequences |
| `VLLM_QUANTIZATION` | _(none)_ | Quantization method (e.g. `awq`) |
| `CONDA_ENV` | `hpert` | Conda env name |

Ví dụ dùng model khác, 1 GPU:

```bash
VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct \
VLLM_TP_SIZE=1 \
VLLM_CUDA_VISIBLE_DEVICES=0 \
bash scripts/serve_vllm.sh
```

Kiểm tra server đã sẵn sàng:

```bash
curl http://localhost:8380/v1/models  -H "Authorization: Bearer dummy"
```

---

## 3. Data ingestion pipeline

Chạy toàn bộ pipeline: parse → chunk → embed → index (Qdrant + Elasticsearch).

```bash
bash scripts/run_data_ingestion_pipeline.sh
```

### Tuỳ chỉnh qua CLI args

| Flag | Mặc định | Mô tả |
|------|----------|-------|
| `--chunk-size` | `500` | Token budget mỗi chunk |
| `--chunk-overlap` | `105` | Token overlap giữa chunks |
| `--embed-batch-size` | _(config)_ | Batch size embedding |
| `--qdrant-batch-size` | _(config)_ | Batch upsert vào Qdrant |
| `--collection-name` | `refined_chatbot_chunks` | Qdrant collection name |
| `--distance` | `cosine` | Distance metric (`cosine`, `dot`, `euclid`) |
| `--qdrant-url` | `http://localhost:6333` | Qdrant endpoint |
| `--qdrant-api-key` | _(config)_ | Qdrant API key |
| `--es-index-name` | `refined_chatbot_chunks` | Elasticsearch index name |
| `--es-url` | `http://localhost:9200` | Elasticsearch endpoint |
| `--es-batch-size` | _(config)_ | Batch bulk-index ES |
| `--run-id` | _(auto-generated)_ | ID định danh run trong logs |
| `--output` | `data/temp_files/ingestion_result.json` | Path lưu kết quả JSON |

Ví dụ:

```bash
bash scripts/run_data_ingestion_pipeline.sh \
  --collection-name my_collection \
  --chunk-size 400 \
  --run-id run_test_01
```

### Kiểm tra sau ingestion

```bash
# Qdrant — xem tất cả collections
curl -s http://localhost:6333/collections | python3 -m json.tool

# Qdrant — detail 1 collection
curl -s http://localhost:6333/collections/refined_chatbot_chunks | python3 -m json.tool

# Elasticsearch — list indices
curl -s http://localhost:9200/_cat/indices?v

# Elasticsearch — số documents
curl -s http://localhost:9200/refined_chatbot_chunks/_count | python3 -m json.tool
```

### Xoá collection/index (nếu cần re-index)

```bash
# Qdrant
curl -X DELETE http://localhost:6333/collections/refined_chatbot_chunks

# Elasticsearch
curl -X DELETE http://localhost:9200/refined_chatbot_chunks
```

Logs ingestion được lưu tại `logs/runs/<run-id>/`.

---

## 4. Chạy FastAPI app

```bash
conda run -n hpert uvicorn main:app --host 0.0.0.0 --port 8111 --reload
```

API docs: http://localhost:8111/docs

Healthcheck nhanh:

```bash
bash scripts/healthcheck.sh
```

Script sẽ check: FastAPI, PostgreSQL, Redis, Qdrant, Elasticsearch.

Check thêm Langfuse/vLLM (tuỳ chọn):

```bash
CHECK_LANGFUSE=1 CHECK_VLLM=1 VLLM_API_KEY=dummy bash scripts/healthcheck.sh
```

---

## 5. Langfuse UI

Xem traces end-to-end (chat + ingestion):

- URL: http://localhost:3000
- Email: `admin@local.dev`
- Password: `Admin123!`

chafo