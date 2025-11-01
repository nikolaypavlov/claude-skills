"""
Model Deployment Example using NeMo 2.0

This example demonstrates how to:
1. Export a trained NeMo model
2. Convert to TensorRT-LLM for optimized inference
3. Deploy with various backends (NIM, TensorRT-LLM, vLLM)
"""

import os
from pathlib import Path


def export_nemo_checkpoint():
    """
    Export training checkpoint to .nemo format
    """
    print("=" * 60)
    print("Step 1: Export NeMo Checkpoint")
    print("=" * 60)

    from nemo.collections.nlp.models import MegatronGPTModel

    # Load model from training checkpoint
    print("Loading model from checkpoint...")
    model = MegatronGPTModel.load_from_checkpoint(
        checkpoint_path="/results/llama3_8b_finetuned/checkpoints/model-step=10000.ckpt"
    )

    # Save as .nemo file
    print("Saving as .nemo format...")
    model.save_to("/models/my_finetuned_model.nemo")

    print("✓ Model exported to: /models/my_finetuned_model.nemo")


def convert_to_tensorrt_llm():
    """
    Convert NeMo model to TensorRT-LLM for optimized inference
    """
    print("\n" + "=" * 60)
    print("Step 2: Convert to TensorRT-LLM")
    print("=" * 60)

    import subprocess

    # Conversion command
    cmd = [
        "python", "/opt/NeMo/scripts/nlp_language_modeling/convert_nemo_to_trtllm.py",
        "--nemo_checkpoint", "/models/my_finetuned_model.nemo",
        "--output_dir", "/models/trtllm_engine",
        "--dtype", "bfloat16",              # Precision
        "--tensor_parallel_size", "2",       # GPU parallelism
        "--pipeline_parallel_size", "1",
        "--max_batch_size", "128",
        "--max_input_len", "2048",
        "--max_output_len", "512",
    ]

    print("Running conversion...")
    print(f"Command: {' '.join(cmd)}")

    subprocess.run(cmd, check=True)

    print("✓ TensorRT-LLM engine created at: /models/trtllm_engine")


def deploy_with_nim():
    """
    Deploy model using NVIDIA NIM (recommended for production)
    """
    print("\n" + "=" * 60)
    print("Step 3: Deploy with NVIDIA NIM")
    print("=" * 60)

    deploy_script = """
# Start NIM server
docker run -d \\
    --name my-nim-server \\
    --gpus all \\
    -p 8000:8000 \\
    -v /models/nim_model:/models \\
    -e MODEL_PATH=/models \\
    -e NUM_GPUS=2 \\
    -e MAX_BATCH_SIZE=128 \\
    nvcr.io/nvidia/nim:24.01

# Wait for server to start
echo "Waiting for server to be ready..."
sleep 30

# Test the server
curl -X POST http://localhost:8000/v1/chat/completions \\
    -H "Content-Type: application/json" \\
    -d '{
        "model": "my_model",
        "messages": [{"role": "user", "content": "Hello!"}],
        "max_tokens": 100
    }'
"""

    print(deploy_script)
    print("\n✓ NIM deployment script ready")
    print("   Server will be available at: http://localhost:8000")


def deploy_with_tensorrt_llm():
    """
    Deploy with TensorRT-LLM directly (for custom deployments)
    """
    print("\n" + "=" * 60)
    print("Alternative: Deploy with TensorRT-LLM")
    print("=" * 60)

    example_code = '''
from tensorrt_llm import LLM

# Load TensorRT-LLM engine
llm = LLM(
    model_dir="/models/trtllm_engine",
    tensor_parallel_size=2,
    dtype="bfloat16",
)

# Generate text
outputs = llm.generate(
    prompts=["What is the capital of France?"],
    max_new_tokens=100,
    temperature=0.7,
    top_p=0.9,
)

for output in outputs:
    print(output.text)
'''

    print("Python code for TensorRT-LLM inference:")
    print(example_code)
    print("\n✓ TensorRT-LLM inference example ready")


def deploy_with_vllm():
    """
    Deploy with vLLM (open-source alternative)
    """
    print("\n" + "=" * 60)
    print("Alternative: Deploy with vLLM")
    print("=" * 60)

    # First, need to convert to HuggingFace format
    convert_code = '''
from nemo.export import export_to_huggingface

# Convert NeMo to HuggingFace format
export_to_huggingface(
    nemo_checkpoint="/models/my_finetuned_model.nemo",
    output_path="/models/hf_model",
)
'''

    print("1. Convert to HuggingFace format:")
    print(convert_code)

    deploy_script = """
# 2. Start vLLM server
python -m vllm.entrypoints.openai.api_server \\
    --model /models/hf_model \\
    --tensor-parallel-size 2 \\
    --dtype bfloat16 \\
    --port 8000 \\
    --max-model-len 4096
"""

    print("\n2. Start vLLM server:")
    print(deploy_script)

    test_code = '''
# 3. Test the server
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed",
)

response = client.chat.completions.create(
    model="/models/hf_model",
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=100,
)

print(response.choices[0].message.content)
'''

    print("\n3. Test the server:")
    print(test_code)
    print("\n✓ vLLM deployment example ready")


def create_fastapi_server():
    """
    Create a custom FastAPI server for serving the model
    """
    print("\n" + "=" * 60)
    print("Bonus: Custom FastAPI Server")
    print("=" * 60)

    server_code = '''
# server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from tensorrt_llm import LLM
import uvicorn

app = FastAPI(title="NeMo Model Server")

# Load model at startup
llm = LLM(model_dir="/models/trtllm_engine", tensor_parallel_size=2)

class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 100
    temperature: float = 0.7
    top_p: float = 0.9

class GenerateResponse(BaseModel):
    text: str
    tokens_generated: int

@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    try:
        outputs = llm.generate(
            prompts=[request.prompt],
            max_new_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
        )

        return GenerateResponse(
            text=outputs[0].text,
            tokens_generated=len(outputs[0].token_ids),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''

    print("Create server.py with this code:")
    print(server_code)

    print("\nRun server with:")
    print("  python server.py")
    print("\n✓ Custom FastAPI server example ready")


def setup_monitoring():
    """
    Setup monitoring and observability
    """
    print("\n" + "=" * 60)
    print("Step 4: Setup Monitoring")
    print("=" * 60)

    prometheus_config = '''
# prometheus.yml
scrape_configs:
  - job_name: 'nim-server'
    static_configs:
      - targets: ['localhost:8001']  # Metrics endpoint
    scrape_interval: 10s
'''

    print("1. Prometheus configuration:")
    print(prometheus_config)

    grafana_dashboard = '''
# Key metrics to monitor:
- Request rate (requests/sec)
- Latency percentiles (p50, p95, p99)
- GPU utilization
- GPU memory usage
- Throughput (tokens/sec)
- Error rate
- Queue depth
'''

    print("\n2. Grafana dashboard metrics:")
    print(grafana_dashboard)

    print("\n✓ Monitoring setup guidelines ready")


def main():
    """
    Complete deployment workflow
    """
    print("=" * 60)
    print("NeMo Model Deployment Workflow")
    print("=" * 60)

    # Step 1: Export checkpoint
    # export_nemo_checkpoint()

    # Step 2: Convert to TensorRT-LLM
    # convert_to_tensorrt_llm()

    # Step 3: Choose deployment method
    print("\nChoose deployment method:\n")

    # Option 1: NIM (recommended)
    deploy_with_nim()

    # Option 2: TensorRT-LLM directly
    deploy_with_tensorrt_llm()

    # Option 3: vLLM
    deploy_with_vllm()

    # Bonus: Custom server
    create_fastapi_server()

    # Step 4: Monitoring
    setup_monitoring()

    print("\n" + "=" * 60)
    print("Deployment Guide Complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Export your trained model")
    print("  2. Convert to deployment format")
    print("  3. Choose and deploy with your preferred backend")
    print("  4. Setup monitoring and alerting")
    print("  5. Load test and optimize")


if __name__ == "__main__":
    main()
