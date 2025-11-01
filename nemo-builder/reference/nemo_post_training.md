# NeMo RL: Post-Training and Alignment Guide

This comprehensive guide covers post-training methods for aligning language models with human preferences using NeMo RL.

---

## Post-Training Overview

### What is Post-Training?

**Post-training** (also called alignment) is the process of adapting a pre-trained or supervised fine-tuned model to better align with human preferences, safety guidelines, and desired behaviors.

**Why post-training matters:**
- **Helpfulness**: Improve quality and usefulness of responses
- **Harmlessness**: Reduce toxic, biased, or harmful outputs
- **Honesty**: Reduce hallucinations and improve factuality
- **Task optimization**: Specialize for code, math, reasoning, etc.

### NeMo RL Library

**Documentation**: `https://docs.nvidia.com/nemo/rl/latest/index.html`

**Key features:**
- Supports 1 GPU to thousands of GPUs
- Models up to 100B+ parameters
- Distributed training with Ray
- Multiple backends (DTensor, Megatron Core)
- vLLM integration for fast generation
- Support for MoE models (DeepSeek-V3, Qwen-3)

---

## Available Post-Training Methods

### 1. GRPO (Group Relative Policy Optimization)

**What it is:**
- NVIDIA's primary RL algorithm for post-training
- Policy optimization using group-based comparisons
- On-policy reinforcement learning method

**When to use:**
- Multi-turn generation tasks
- Math problem-solving
- Game-playing and strategic reasoning
- Complex multi-step tasks

**Key advantages:**
- More stable than traditional PPO
- Better sample efficiency
- Group-based relative scoring reduces variance

### 2. DPO (Direct Preference Optimization)

**What it is:**
- Preference-based training without explicit reward modeling
- Directly optimizes policy from preference data
- Simpler than RLHF with reward models

**When to use:**
- Have high-quality preference datasets
- Want simpler training pipeline
- Don't need explicit reward model
- Focused on preference alignment

**Key advantages:**
- No separate reward model training
- More stable training
- Simpler implementation
- Lower computational cost

### 3. Reward Model Training

**What it is:**
- Train a model to predict human preferences
- Used as reward signal for RL training
- Foundation for traditional RLHF

**When to use:**
- Building full RLHF pipeline
- Need interpretable reward signals
- Want to analyze preference patterns
- Multiple RL runs with same reward

### 4. Supervised Fine-Tuning (SFT)

**What it is:**
- Traditional instruction tuning on curated datasets
- Often first step before RL-based post-training
- Direct supervision on desired outputs

**When to use:**
- As first step before RLHF
- Have high-quality instruction datasets
- Want straightforward training
- Baseline before alignment

---

## Phase 1: Prepare for Post-Training

### Prerequisites

**Starting point:**
- Pre-trained base model OR
- Supervised fine-tuned (SFT) model (recommended)

**Infrastructure:**
- NVIDIA GPUs (A100, H100)
- Ray cluster for distributed training
- Sufficient storage for checkpoints
- vLLM for fast generation (optional but recommended)

**Data requirements:**
- Preference datasets (for DPO, reward modeling)
- High-quality prompts
- Evaluation benchmarks

### Install NeMo RL

```bash
# Install NeMo RL
pip install nemo-rl

# Or install from source
git clone https://github.com/NVIDIA/NeMo-RL.git
cd NeMo-RL
pip install -e .

# Install Ray for distributed training
pip install ray[default]

# Optional: Install vLLM for fast generation
pip install vllm
```

### Verify Installation

```python
import nemo_rl
print(nemo_rl.__version__)

# Check Ray
import ray
ray.init()
print("Ray initialized successfully")
```

---

## Phase 2: Prepare Preference Data

### Data Format

**Preference pairs format:**
```jsonl
{
  "prompt": "Explain photosynthesis",
  "chosen": "Photosynthesis is the process by which plants convert light energy...",
  "rejected": "Plants make food using sunlight. That's photosynthesis.",
  "metadata": {
    "source": "human_annotation",
    "preference_strength": 0.8
  }
}
```

**Multi-turn conversation format:**
```jsonl
{
  "messages": [
    {"role": "user", "content": "What is 2+2?"},
    {"role": "assistant", "content": "4"}
  ],
  "chosen_response": "2+2 equals 4. This is basic addition.",
  "rejected_response": "I don't know.",
  "score_diff": 1.5
}
```

### Data Collection Strategies

**1. Human Feedback:**
- Collect preferences from human annotators
- Present multiple responses to same prompt
- Annotators select preferred response
- Track inter-annotator agreement

**2. AI Feedback (Constitutional AI):**
```python
def generate_ai_feedback(prompt, responses, constitution):
    """
    Use a strong model to provide feedback based on principles
    """
    feedback_prompt = f"""
Given the following prompt and responses, evaluate which response better follows these principles:
{constitution}

Prompt: {prompt}

Response A: {responses[0]}
Response B: {responses[1]}

Which response is better and why?
"""
    # Use strong model (e.g., GPT-4, Claude) for evaluation
    return model.generate(feedback_prompt)
```

**3. Existing Datasets:**
- **HelpSteer**: NVIDIA's helpfulness dataset
- **Anthropic HH**: Helpfulness and Harmlessness dataset
- **OpenAI WebGPT**: Web-browsing preferences
- **Stanford SHP**: StackExchange preferences

**4. Synthetic Generation:**
```python
def create_synthetic_preferences(prompts, model):
    """
    Generate multiple responses and create preferences
    """
    preferences = []
    for prompt in prompts:
        # Generate multiple responses with different temperatures
        responses = [
            model.generate(prompt, temperature=0.7),
            model.generate(prompt, temperature=1.0),
            model.generate(prompt, temperature=0.3),
        ]

        # Use quality metrics to rank
        scored = [(r, quality_score(r)) for r in responses]
        sorted_responses = sorted(scored, key=lambda x: x[1], reverse=True)

        preferences.append({
            "prompt": prompt,
            "chosen": sorted_responses[0][0],
            "rejected": sorted_responses[-1][0],
        })

    return preferences
```

### Data Quality Checks

**Essential checks:**
```python
def validate_preference_data(dataset):
    """
    Validate preference dataset quality
    """
    checks = {
        "has_prompt": all("prompt" in item for item in dataset),
        "has_chosen": all("chosen" in item for item in dataset),
        "has_rejected": all("rejected" in item for item in dataset),
        "chosen_different": all(item["chosen"] != item["rejected"] for item in dataset),
        "reasonable_length": all(
            len(item["chosen"].split()) > 5 and len(item["rejected"].split()) > 5
            for item in dataset
        ),
    }

    return all(checks.values()), checks
```

---

## Phase 3: DPO Training

### Configure DPO

```python
from nemo_rl.algorithms import DPO
from nemo_rl.trainers import RLTrainer

# DPO configuration
dpo_config = {
    # Model
    "model_path": "/models/sft_model.nemo",
    "reference_model_path": "/models/sft_model.nemo",  # Usually same as policy

    # Data
    "train_data": "/data/preferences_train.jsonl",
    "val_data": "/data/preferences_val.jsonl",

    # Training hyperparameters
    "learning_rate": 5e-7,
    "beta": 0.1,                    # KL penalty coefficient
    "num_epochs": 3,
    "batch_size": 8,
    "gradient_accumulation_steps": 4,

    # Distributed training
    "tensor_parallel_size": 2,
    "pipeline_parallel_size": 1,

    # Optimization
    "max_length": 2048,
    "precision": "bf16",
}

# Initialize DPO trainer
dpo_trainer = RLTrainer(
    algorithm="dpo",
    config=dpo_config,
)

# Train
dpo_trainer.train()
```

### DPO Training Loop (Conceptual)

```python
def dpo_training_step(policy_model, reference_model, batch):
    """
    Conceptual DPO training step
    """
    prompts = batch["prompts"]
    chosen = batch["chosen"]
    rejected = batch["rejected"]

    # Get log probabilities from policy model
    policy_chosen_logp = policy_model.log_prob(prompts, chosen)
    policy_rejected_logp = policy_model.log_prob(prompts, rejected)

    # Get log probabilities from reference model (frozen)
    ref_chosen_logp = reference_model.log_prob(prompts, chosen)
    ref_rejected_logp = reference_model.log_prob(prompts, rejected)

    # Compute DPO loss
    policy_logratios = policy_chosen_logp - policy_rejected_logp
    ref_logratios = ref_chosen_logp - ref_rejected_logp

    loss = -torch.log(torch.sigmoid(beta * (policy_logratios - ref_logratios))).mean()

    return loss
```

### Monitor DPO Training

**Key metrics:**
- **Loss**: Should decrease steadily
- **Accuracy**: Preference prediction accuracy (>50% = better than random)
- **Reward gap**: Chosen vs rejected reward difference
- **KL divergence**: Distance from reference model

```python
# Log metrics during training
metrics = {
    "loss": dpo_loss.item(),
    "accuracy": (policy_logratios > 0).float().mean().item(),
    "reward_chosen": policy_chosen_logp.mean().item(),
    "reward_rejected": policy_rejected_logp.mean().item(),
    "kl_div": (policy_chosen_logp - ref_chosen_logp).mean().item(),
}
```

---

## Phase 4: GRPO Training

### Configure GRPO

```python
from nemo_rl.algorithms import GRPO

# GRPO configuration
grpo_config = {
    # Models
    "policy_model": "/models/sft_model.nemo",
    "reward_model": "/models/reward_model.nemo",  # Or use rule-based reward

    # Data
    "prompts": "/data/rlhf_prompts.jsonl",

    # GRPO hyperparameters
    "learning_rate": 1e-6,
    "kl_coeff": 0.05,               # KL penalty
    "clip_ratio": 0.2,              # PPO-style clipping
    "value_loss_coeff": 1.0,
    "entropy_coeff": 0.01,

    # Generation
    "num_responses_per_prompt": 4,  # Group size
    "max_new_tokens": 512,
    "temperature": 0.7,

    # Training
    "num_iterations": 1000,
    "batch_size": 32,
    "epochs_per_iteration": 1,

    # Distributed
    "tensor_parallel_size": 4,
    "num_gpus": 8,
}

# Initialize GRPO trainer
grpo_trainer = RLTrainer(
    algorithm="grpo",
    config=grpo_config,
)

# Train
grpo_trainer.train()
```

### GRPO Training Loop (Conceptual)

```python
def grpo_training_iteration(policy, reward_model, prompts):
    """
    Conceptual GRPO iteration
    """
    # 1. Generate responses (rollout)
    responses = []
    for prompt in prompts:
        group = [
            policy.generate(prompt, temperature=0.7)
            for _ in range(num_responses_per_prompt)
        ]
        responses.append(group)

    # 2. Compute rewards
    rewards = []
    for prompt, group in zip(prompts, responses):
        group_rewards = [
            reward_model.score(prompt, response)
            for response in group
        ]
        rewards.append(group_rewards)

    # 3. Compute relative advantages within each group
    advantages = []
    for group_rewards in rewards:
        mean_reward = np.mean(group_rewards)
        group_advantages = [r - mean_reward for r in group_rewards]
        advantages.append(group_advantages)

    # 4. Policy update using advantages
    policy_loss = compute_policy_loss(policy, prompts, responses, advantages)

    # 5. Update policy
    optimizer.zero_grad()
    policy_loss.backward()
    optimizer.step()

    return policy_loss
```

### Monitor GRPO Training

**Key metrics:**
- **Average reward**: Should increase over time
- **Reward std**: Variance in rewards
- **KL divergence**: From initial policy
- **Policy loss**: Should decrease
- **Value loss**: Critic accuracy (if using value function)

---

## Phase 5: Reward Model Training

### Prepare Reward Data

**Convert preferences to reward data:**
```python
def prepare_reward_training_data(preferences):
    """
    Convert preference pairs to reward training format
    """
    reward_data = []
    for item in preferences:
        reward_data.append({
            "prompt": item["prompt"],
            "response": item["chosen"],
            "score": 1.0,  # Chosen = higher score
        })
        reward_data.append({
            "prompt": item["prompt"],
            "response": item["rejected"],
            "score": 0.0,  # Rejected = lower score
        })

    return reward_data
```

### Train Reward Model

```python
from nemo_rl.algorithms import RewardModelTrainer

# Reward model configuration
rm_config = {
    # Base model
    "base_model": "/models/sft_model.nemo",

    # Data
    "train_data": "/data/reward_train.jsonl",
    "val_data": "/data/reward_val.jsonl",

    # Training
    "learning_rate": 1e-5,
    "num_epochs": 3,
    "batch_size": 16,

    # Loss
    "loss_type": "ranking",         # or "regression"
    "margin": 0.5,                  # For ranking loss

    # Distributed
    "tensor_parallel_size": 2,
}

# Train reward model
rm_trainer = RewardModelTrainer(config=rm_config)
rm_trainer.train()

# Save reward model
rm_trainer.save("/models/reward_model.nemo")
```

### Validate Reward Model

```python
def validate_reward_model(model, val_preferences):
    """
    Validate reward model on held-out preferences
    """
    correct = 0
    total = len(val_preferences)

    for item in val_preferences:
        prompt = item["prompt"]
        chosen = item["chosen"]
        rejected = item["rejected"]

        # Score both responses
        score_chosen = model.score(prompt, chosen)
        score_rejected = model.score(prompt, rejected)

        # Check if preference is correct
        if score_chosen > score_rejected:
            correct += 1

    accuracy = correct / total
    print(f"Reward model accuracy: {accuracy:.2%}")
    return accuracy
```

---

## Phase 6: Evaluation and Analysis

### Evaluation Metrics

**Quantitative metrics:**
```python
# Use NeMo Eval for comprehensive evaluation
# Docs: https://docs.nvidia.com/nemo/evaluator/latest/index.html

from nemo_eval import Evaluator

evaluator = Evaluator(
    model="/models/aligned_model.nemo",
    benchmarks=[
        "mmlu",             # General knowledge
        "hellaswag",        # Commonsense reasoning
        "truthfulqa",       # Factuality
        "humaneval",        # Code generation
    ]
)

results = evaluator.run()
print(results)
```

**Qualitative evaluation:**
```python
def qualitative_eval(model, test_prompts):
    """
    Manual quality check on specific prompts
    """
    for prompt in test_prompts:
        response = model.generate(prompt, max_tokens=200)
        print(f"\nPrompt: {prompt}")
        print(f"Response: {response}")
        print("-" * 80)

# Test on edge cases
test_prompts = [
    "How do I hack into a computer?",  # Safety test
    "Explain quantum computing",        # Helpfulness test
    "2+2=?",                           # Simple accuracy test
]

qualitative_eval(aligned_model, test_prompts)
```

### Win Rate Analysis

**Compare aligned model to baseline:**
```python
def compute_win_rate(aligned_model, baseline_model, prompts):
    """
    Use human or AI judges to compare models
    """
    wins = 0
    total = len(prompts)

    for prompt in prompts:
        response_aligned = aligned_model.generate(prompt)
        response_baseline = baseline_model.generate(prompt)

        # Get preference from judge (human or AI)
        preference = judge.compare(prompt, response_aligned, response_baseline)

        if preference == "aligned":
            wins += 1

    win_rate = wins / total
    print(f"Win rate vs baseline: {win_rate:.2%}")
    return win_rate
```

### Safety Benchmarks

**Test on safety datasets:**
```python
# Common safety benchmarks
safety_benchmarks = [
    "anthropic_red_team",
    "bbq_bias",
    "toxigen",
    "real_toxicity_prompts",
]

# Evaluate safety
safety_results = evaluator.run(benchmarks=safety_benchmarks)
```

---

## Best Practices

### Data Quality

1. **Diverse prompts**: Cover wide range of use cases
2. **Consistent preferences**: Inter-annotator agreement >70%
3. **Balanced distribution**: Equal chosen/rejected examples
4. **Quality over quantity**: 10K high-quality > 100K low-quality

### Training Stability

1. **Start with SFT**: Always begin with supervised fine-tuning
2. **Small learning rates**: 1e-6 to 1e-5 for post-training
3. **Monitor KL**: Keep KL divergence from reference model low
4. **Gradual updates**: Use small batch sizes and gradient accumulation

### Hyperparameter Tuning

**DPO hyperparameters:**
- `beta`: 0.1-0.5 (higher = stay closer to reference)
- `learning_rate`: 5e-7 to 1e-6
- `num_epochs`: 1-3 (more can cause overfitting)

**GRPO hyperparameters:**
- `kl_coeff`: 0.01-0.1
- `clip_ratio`: 0.1-0.3
- `num_responses_per_prompt`: 4-16

### Avoiding Pitfalls

**Common issues:**
1. **Reward hacking**: Model exploits reward without improving quality
2. **Mode collapse**: Model produces repetitive outputs
3. **Forgetting**: Loss of capabilities from base model
4. **Overfitting**: Memorizing preference data

**Solutions:**
- Regular evaluation on diverse benchmarks
- Monitor KL divergence
- Use held-out validation set
- Ensemble multiple checkpoints

---

## Complete Post-Training Example

```python
# Complete workflow: SFT → DPO → Evaluation

# 1. Start with supervised fine-tuned model
sft_model_path = "/models/llama3_8b_sft.nemo"

# 2. Prepare preference data
preferences = load_preference_data("/data/preferences.jsonl")
train_prefs, val_prefs = split_data(preferences, ratio=0.9)

# 3. Train with DPO
from nemo_rl import DPOTrainer

dpo_trainer = DPOTrainer(
    model_path=sft_model_path,
    train_data=train_prefs,
    val_data=val_prefs,
    beta=0.1,
    learning_rate=5e-7,
    num_epochs=2,
)

aligned_model = dpo_trainer.train()
aligned_model.save("/models/llama3_8b_aligned.nemo")

# 4. Evaluate
from nemo_eval import Evaluator

evaluator = Evaluator(model=aligned_model)
results = evaluator.run([
    "mmlu",
    "hellaswag",
    "truthfulqa",
])

print("Evaluation results:", results)

# 5. Compare to baseline
win_rate = compute_win_rate(
    aligned_model=aligned_model,
    baseline_model=sft_model,
    test_prompts=test_set,
)

print(f"Win rate: {win_rate:.1%}")
```

---

## Additional Resources

- **NeMo RL Documentation**: `https://docs.nvidia.com/nemo/rl/latest/index.html`
- **NeMo Eval Documentation**: `https://docs.nvidia.com/nemo/evaluator/latest/index.html`
- **DPO Paper**: https://arxiv.org/abs/2305.18290
- **RLHF Overview**: https://arxiv.org/abs/2203.02155
- **Constitutional AI**: https://arxiv.org/abs/2212.08073

---

For related topics, see:
- [📋 NeMo Best Practices](./nemo_best_practices.md)
- [🎯 Training Guide](./nemo_training.md)
- [🚀 Deployment Guide](./nemo_deployment.md)
- [📊 Data Preparation Guide](./nemo_data_preparation.md)
