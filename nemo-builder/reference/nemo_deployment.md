# NeMo 2.0 Deployment Guide

This comprehensive guide covers deploying NeMo models to production, from export and optimization to serving and monitoring.

---

## Deployment Overview

### Deployment Pathways

NeMo 2.0 supports three primary deployment paths:

**1. NVIDIA NIM (Recommended for Enterprise)**
- Containerized microservice with optimized inference
- Built on TensorRT-LLM
- Production-ready APIs (OpenAI-compatible)
- Scalable and secure
- Requires NVIDIA AI Enterprise license

**2. TensorRT-LLM**
- Maximum performance inference engine
- Direct control over optimization
- Custom deployment scenarios
- Requires more configuration

**3. vLLM**
- Open-source inference engine
- PagedAttention for memory efficiency
- Good for research and prototypes
- Active community support

---

## Phase 1: Model Export and Conversion

### Export NeMo Model

**From training checkpoint:**
```python
from nemo.collections.nlp.models import MegatronGPTModel

# Load model from training checkpoint
model = MegatronGPTModel.load_from_checkpoint(
    checkpoint_path="/checkpoints/model-step=10000.ckpt"
)

# Save as .nemo file
model.save_to("/models/my_model.nemo")
```

**Verify .nemo file:**
```python
# Load and test
model = MegatronGPTModel.restore_from("/models/my_model.nemo")

# Test inference
output = model.generate(
    inputs=["What is the capital of France?"],
    length_params={
        "max_length": 50,
        "min_length": 10,
    }
)
print(output)
```

### Convert to Deployment Format

#### Convert to TensorRT-LLM

```bash
# Install TensorRT-LLM
pip install tensorrt-llm

# Convert NeMo → TensorRT-LLM
python /opt/NeMo/scripts/nlp_language_modeling/convert_nemo_to_trtllm.py \
    --nemo_checkpoint /models/my_model.nemo \
    --output_dir /models/trtllm_engine \
    --dtype bfloat16 \
    --tensor_parallel_size 2 \
    --pipeline_parallel_size 1
```

**Conversion parameters:**
- `dtype`: Precision (float16, bfloat16, float32)
- `tensor_parallel_size`: GPU parallelism
- `pipeline_parallel_size`: Pipeline stages
- `max_batch_size`: Maximum batch size
- `max_input_len`: Maximum input tokens
- `max_output_len`: Maximum output tokens

#### Convert to vLLM Format

```python
# vLLM can directly load .nemo files (if supported)
# Or convert to HuggingFace format first

from nemo.export import export_to_huggingface

export_to_huggingface(
    nemo_checkpoint="/models/my_model.nemo",
    output_path="/models/hf_model",
)
```

---

## Phase 2: Model Optimization

### Quantization

**INT8 Quantization (TensorRT-LLM):**
```bash
# Convert with INT8 quantization
python convert_nemo_to_trtllm.py \
    --nemo_checkpoint /models/my_model.nemo \
    --output_dir /models/trtllm_int8 \
    --dtype float16 \
    --quantization int8_sq  # Smooth Quant INT8
```

**FP8 Quantization (H100 GPUs):**
```bash
# Convert with FP8 quantization
python convert_nemo_to_trtllm.py \
    --nemo_checkpoint /models/my_model.nemo \
    --output_dir /models/trtllm_fp8 \
    --dtype float16 \
    --quantization fp8
```

**AWQ Quantization (4-bit):**
```bash
# Convert with AWQ 4-bit quantization
python convert_nemo_to_trtllm.py \
    --nemo_checkpoint /models/my_model.nemo \
    --output_dir /models/trtllm_awq \
    --quantization awq \
    --awq_block_size 128
```

**Quantization trade-offs:**
| Method | Compression | Speed | Quality | GPU |
|--------|-------------|-------|---------|-----|
| FP16/BF16 | None | Fast | Best | Any |
| FP8 | 2x | Faster | Excellent | H100 |
| INT8 | 4x | Faster | Good | A100+ |
| INT4/AWQ | 8x | Fast | Fair | Any |

### KV Cache Optimization

**Configure KV cache for TensorRT-LLM:**
```python
# During conversion, set KV cache params
conversion_args = {
    "max_batch_size": 128,
    "max_input_len": 2048,
    "max_output_len": 512,
    "kv_cache_free_gpu_mem_fraction": 0.9,  # Use 90% of free memory for KV cache
}
```

### In-flight Batching

**Enable continuous batching:**
```python
# TensorRT-LLM supports in-flight batching automatically
# This allows new requests to join ongoing batches
# Significantly improves throughput
```

---

## Phase 3: Deployment with NVIDIA NIM

### Setup NIM Container

**Pull NIM container:**
```bash
# Login to NGC
docker login nvcr.io

# Pull NIM container
docker pull nvcr.io/nvidia/nim:24.01
```

**Prepare model for NIM:**
```bash
# NIM expects models in specific format
# Convert NeMo model to NIM format
python /opt/nim/scripts/convert_to_nim.py \
    --model_path /models/my_model.nemo \
    --output_path /models/nim_model
```

### Run NIM Server

```bash
# Start NIM server
docker run -d \
    --name my_nim_server \
    --gpus all \
    -p 8000:8000 \
    -v /models/nim_model:/models \
    -e MODEL_PATH=/models \
    -e NUM_GPUS=2 \
    nvcr.io/nvidia/nim:24.01
```

**Environment variables:**
- `MODEL_PATH`: Path to model
- `NUM_GPUS`: Number of GPUs to use
- `MAX_BATCH_SIZE`: Maximum batch size
- `MAX_QUEUE_SIZE`: Request queue size

### Query NIM API

**OpenAI-compatible API:**
```python
import openai

# Configure client
client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

# Generate completion
response = client.chat.completions.create(
    model="my_model",
    messages=[
        {"role": "user", "content": "What is the capital of France?"}
    ],
    max_tokens=100,
    temperature=0.7,
)

print(response.choices[0].message.content)
```

**Streaming responses:**
```python
# Streaming generation
stream = client.chat.completions.create(
    model="my_model",
    messages=[{"role": "user", "content": "Tell me a story"}],
    max_tokens=500,
    stream=True,
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

---

## Phase 4: Deployment with TensorRT-LLM

### Build TensorRT-LLM Engine

```python
from tensorrt_llm import LLM

# Load converted model
llm = LLM(
    model_dir="/models/trtllm_engine",
    tensor_parallel_size=2,
    dtype="bfloat16",
)
```

### Run Inference

**Single request:**
```python
# Generate text
outputs = llm.generate(
    prompts=["What is the capital of France?"],
    max_new_tokens=100,
    temperature=0.7,
    top_p=0.9,
)

for output in outputs:
    print(output.text)
```

**Batch inference:**
```python
# Batch processing
prompts = [
    "What is the capital of France?",
    "What is the capital of Germany?",
    "What is the capital of Italy?",
]

outputs = llm.generate(
    prompts=prompts,
    max_new_tokens=50,
    temperature=0.7,
)

for prompt, output in zip(prompts, outputs):
    print(f"Prompt: {prompt}")
    print(f"Output: {output.text}\n")
```

### Create Serving API

**FastAPI server:**
```python
from fastapi import FastAPI
from pydantic import BaseModel
from tensorrt_llm import LLM
import uvicorn

app = FastAPI()

# Load model
llm = LLM(model_dir="/models/trtllm_engine")

class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 100
    temperature: float = 0.7

@app.post("/generate")
async def generate(request: GenerateRequest):
    outputs = llm.generate(
        prompts=[request.prompt],
        max_new_tokens=request.max_tokens,
        temperature=request.temperature,
    )
    return {"text": outputs[0].text}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## Phase 5: Deployment with vLLM

### Install vLLM

```bash
pip install vllm
```

### Deploy with vLLM

**Load and serve model:**
```python
from vllm import LLM, SamplingParams

# Load model
llm = LLM(
    model="/models/hf_model",  # HuggingFace format
    tensor_parallel_size=2,
    dtype="bfloat16",
)

# Configure sampling
sampling_params = SamplingParams(
    temperature=0.7,
    top_p=0.9,
    max_tokens=100,
)

# Generate
prompts = ["What is the capital of France?"]
outputs = llm.generate(prompts, sampling_params)

for output in outputs:
    print(output.outputs[0].text)
```

### vLLM OpenAI-Compatible Server

```bash
# Start vLLM server with OpenAI API
python -m vllm.entrypoints.openai.api_server \
    --model /models/hf_model \
    --tensor-parallel-size 2 \
    --dtype bfloat16 \
    --port 8000
```

**Query vLLM server:**
```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed",
)

response = client.chat.completions.create(
    model="/models/hf_model",
    messages=[{"role": "user", "content": "What is NeMo?"}],
    max_tokens=100,
)

print(response.choices[0].message.content)
```

---

## Phase 6: Performance Optimization

### Batch Size Tuning

**Find optimal batch size:**
```python
import time

def benchmark_batch_size(llm, batch_size):
    prompts = ["Test prompt"] * batch_size
    start = time.time()
    llm.generate(prompts, max_new_tokens=100)
    elapsed = time.time() - start
    throughput = batch_size / elapsed
    return throughput

# Test different batch sizes
for bs in [1, 2, 4, 8, 16, 32, 64, 128]:
    throughput = benchmark_batch_size(llm, bs)
    print(f"Batch size {bs}: {throughput:.2f} req/sec")
```

### GPU Utilization

**Monitor GPU usage:**
```bash
# Real-time monitoring
nvidia-smi -l 1

# Or programmatically
import pynvml

pynvml.nvmlInit()
handle = pynvml.nvmlDeviceGetHandleByIndex(0)

# Get utilization
util = pynvml.nvmlDeviceGetUtilizationRates(handle)
print(f"GPU Utilization: {util.gpu}%")
print(f"Memory Utilization: {util.memory}%")
```

### Latency Optimization

**Techniques to reduce latency:**

1. **Reduce batch size**: Lower latency per request
2. **Use FP16/FP8**: Faster computation
3. **Optimize KV cache**: Reduce memory movement
4. **Use smaller models**: Consider distillation
5. **Speculative decoding**: Use draft model for speedup

**Measure latency:**
```python
import time

def measure_latency(llm, prompt, num_runs=100):
    latencies = []
    for _ in range(num_runs):
        start = time.time()
        llm.generate([prompt], max_new_tokens=50)
        latencies.append(time.time() - start)

    return {
        "mean": sum(latencies) / len(latencies),
        "p50": sorted(latencies)[len(latencies) // 2],
        "p95": sorted(latencies)[int(len(latencies) * 0.95)],
        "p99": sorted(latencies)[int(len(latencies) * 0.99)],
    }

stats = measure_latency(llm, "What is AI?")
print(f"Mean latency: {stats['mean']:.3f}s")
print(f"P95 latency: {stats['p95']:.3f}s")
```

---

## Phase 7: Production Deployment Patterns

### Single Server Deployment

**For small-scale applications:**

```yaml
# docker-compose.yml
version: '3.8'
services:
  model-server:
    image: nvcr.io/nvidia/nim:24.01
    ports:
      - "8000:8000"
    volumes:
      - ./models:/models
    environment:
      - MODEL_PATH=/models/my_model
      - NUM_GPUS=2
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 2
              capabilities: [gpu]
```

### Kubernetes Deployment

**For production scale:**

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nim-deployment
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nim-server
  template:
    metadata:
      labels:
        app: nim-server
    spec:
      containers:
      - name: nim
        image: nvcr.io/nvidia/nim:24.01
        ports:
        - containerPort: 8000
        env:
        - name: MODEL_PATH
          value: /models/my_model
        - name: NUM_GPUS
          value: "2"
        resources:
          limits:
            nvidia.com/gpu: 2
        volumeMounts:
        - name: model-storage
          mountPath: /models
      volumes:
      - name: model-storage
        persistentVolumeClaim:
          claimName: model-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: nim-service
spec:
  selector:
    app: nim-server
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

### Load Balancing

**NGINX configuration:**
```nginx
upstream nim_backend {
    least_conn;  # Route to least busy server
    server nim-1:8000 max_fails=3 fail_timeout=30s;
    server nim-2:8000 max_fails=3 fail_timeout=30s;
    server nim-3:8000 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;

    location / {
        proxy_pass http://nim_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;  # Long timeout for generation
    }
}
```

---

## Phase 8: Monitoring and Observability

### Metrics to Track

**Request metrics:**
- Request rate (requests/sec)
- Latency (p50, p95, p99)
- Error rate
- Queue depth

**Model metrics:**
- Throughput (tokens/sec)
- GPU utilization
- GPU memory usage
- Batch size distribution

**System metrics:**
- CPU usage
- System memory
- Network bandwidth
- Disk I/O

### Prometheus + Grafana Setup

**Expose metrics:**
```python
from prometheus_client import Counter, Histogram, start_http_server

# Define metrics
request_count = Counter('model_requests_total', 'Total requests')
request_latency = Histogram('model_request_latency_seconds', 'Request latency')

# Instrument your code
@request_latency.time()
def generate(prompt):
    request_count.inc()
    return llm.generate([prompt])

# Start metrics server
start_http_server(8001)  # Metrics on port 8001
```

**Prometheus config:**
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'nim-server'
    static_configs:
      - targets: ['localhost:8001']
    scrape_interval: 10s
```

### Logging

**Structured logging:**
```python
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        return json.dumps(log_obj)

# Configure logger
logger = logging.getLogger("nim-server")
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Log requests
logger.info("Request received", extra={
    "prompt_length": len(prompt),
    "max_tokens": max_tokens,
    "user_id": user_id,
})
```

### Alerting

**Sample alert rules:**
```yaml
# alerts.yml
groups:
  - name: nim_alerts
    rules:
      # High error rate
      - alert: HighErrorRate
        expr: rate(model_requests_failed[5m]) > 0.05
        for: 5m
        annotations:
          summary: "High error rate detected"

      # High latency
      - alert: HighLatency
        expr: model_request_latency_seconds{quantile="0.95"} > 2
        for: 5m
        annotations:
          summary: "P95 latency above 2 seconds"

      # Low GPU utilization
      - alert: LowGPUUtilization
        expr: gpu_utilization_percent < 50
        for: 10m
        annotations:
          summary: "GPU utilization below 50%"
```

---

## Phase 9: Cost Optimization

### GPU Selection

**Cost-performance analysis:**

| GPU | Memory | Cost/hr | Performance | Best For |
|-----|--------|---------|-------------|----------|
| T4 | 16GB | $ | Baseline | Small models, dev |
| L4 | 24GB | $$ | 2x T4 | Production, small-medium models |
| A10G | 24GB | $$ | 3x T4 | Production, medium models |
| A100 40GB | 40GB | $$$ | 6x T4 | Large models |
| A100 80GB | 80GB | $$$$ | 6x T4 | Very large models |
| H100 | 80GB | $$$$$ | 9x T4 | Largest models, FP8 |

### Autoscaling

**Scale based on load:**
```yaml
# kubernetes HPA
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: nim-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: nim-deployment
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Pods
    pods:
      metric:
        name: requests_per_second
      target:
        type: AverageValue
        averageValue: "100"
```

### Request Batching

**Improve throughput with batching:**
```python
from collections import deque
import asyncio

class BatchedInferenceServer:
    def __init__(self, model, max_batch_size=32, max_wait_ms=50):
        self.model = model
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms
        self.queue = deque()

    async def process_batch(self):
        while True:
            # Wait for requests or timeout
            await asyncio.sleep(self.max_wait_ms / 1000)

            if not self.queue:
                continue

            # Collect batch
            batch = []
            futures = []
            while self.queue and len(batch) < self.max_batch_size:
                prompt, future = self.queue.popleft()
                batch.append(prompt)
                futures.append(future)

            # Process batch
            outputs = self.model.generate(batch)

            # Return results
            for future, output in zip(futures, outputs):
                future.set_result(output)

    async def generate(self, prompt):
        future = asyncio.Future()
        self.queue.append((prompt, future))
        return await future
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Model exported to deployment format
- [ ] Quantization applied (if needed)
- [ ] Performance benchmarked
- [ ] Load testing completed
- [ ] Monitoring configured
- [ ] Logging configured
- [ ] Alerts configured

### Security

- [ ] API authentication enabled
- [ ] Rate limiting configured
- [ ] Input validation implemented
- [ ] Output filtering (if needed)
- [ ] Network security configured
- [ ] Encryption at rest/transit

### Production Readiness

- [ ] Multi-replica deployment
- [ ] Load balancer configured
- [ ] Auto-scaling enabled
- [ ] Health checks implemented
- [ ] Graceful shutdown handling
- [ ] Backup and recovery plan
- [ ] Incident response plan

---

## Troubleshooting Deployment Issues

### Issue: High Latency

**Diagnose:**
- Check GPU utilization (should be >80%)
- Monitor batch size (larger = higher throughput, higher latency)
- Profile inference (where is time spent?)

**Solutions:**
- Reduce batch size for lower latency
- Use quantization (FP8, INT8)
- Optimize KV cache settings
- Scale horizontally (more replicas)

### Issue: OOM (Out of Memory)

**Solutions:**
- Reduce batch size
- Use quantization
- Reduce max sequence length
- Optimize KV cache memory fraction
- Use larger GPU

### Issue: Low Throughput

**Solutions:**
- Increase batch size
- Enable request batching
- Use in-flight batching
- Check data loading isn't bottleneck
- Increase number of replicas

---

## Best Practices Summary

1. **Start with NIM**: Easiest path to production for enterprise
2. **Benchmark early**: Test performance before full deployment
3. **Monitor everything**: Latency, throughput, errors, GPU usage
4. **Use quantization**: FP8/INT8 for better cost-performance
5. **Enable batching**: Essential for high throughput
6. **Scale horizontally**: More replicas > bigger GPUs (usually)
7. **Plan for failures**: Implement retries, fallbacks, circuit breakers
8. **Cost optimize**: Right-size GPUs, use autoscaling

---

## Additional Resources

### NeMo Deployment

- **NeMo Export and Deploy**: `https://docs.nvidia.com/nemo/export-deploy/latest/index.html`
- **NeMo Deployment Examples**: https://github.com/NVIDIA/NeMo/tree/main/scripts/deploy

### Inference Engines

- **NVIDIA NIM Documentation**: https://docs.nvidia.com/nim/
- **TensorRT-LLM Documentation**: https://github.com/NVIDIA/TensorRT-LLM
- **vLLM Documentation**: https://docs.vllm.ai/

### Evaluation

- **NeMo Eval**: `https://docs.nvidia.com/nemo/evaluator/latest/index.html`

---

For related topics, see:
- [📋 NeMo Best Practices](./nemo_best_practices.md)
- [🎯 Training Guide](./nemo_training.md)
- [📊 Data Preparation Guide](./nemo_data_preparation.md)
