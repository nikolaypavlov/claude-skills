"""
Parameter-Efficient Fine-Tuning (PEFT) with LoRA using NeMo 2.0

This example demonstrates how to fine-tune a model using LoRA (Low-Rank Adaptation),
which trains only a small subset of parameters for faster training and lower memory usage.
"""

from nemo.collections import llm
from nemo.collections.nlp.parts.peft_config import LoraConfig
from nemo import lightning as nl
import nemo_run as run


def main():
    # 1. Configure base model
    print("Loading Llama 3 8B base model...")
    model = llm.Llama3Config8B()

    # 2. Configure LoRA
    print("Configuring LoRA adapter...")
    lora_config = LoraConfig(
        # Target modules to apply LoRA
        target_modules=[
            "attention.query_key_value",    # Q, K, V projections
            "attention.dense",              # Attention output projection
            "mlp.dense_h_to_4h",           # MLP input projection
            "mlp.dense_4h_to_h",           # MLP output projection
        ],

        # LoRA hyperparameters
        adapter_dim=64,                     # LoRA rank (r)
        alpha=64,                           # Scaling factor (typically = rank)
        dropout=0.1,                        # LoRA dropout

        # Advanced options
        adapter_dropout=0.0,
        use_rslora=False,                   # Use Rank-Stabilized LoRA
    )

    # Apply LoRA to model
    print("Applying LoRA adapter to model...")
    model.add_adapter(lora_config)
    model.freeze()                          # Freeze base model parameters
    model.unfreeze_adapter()                # Only train LoRA parameters

    # Calculate trainable parameters
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Total parameters: {total_params:,}")
    print(f"Trainable parameters: {trainable_params:,} ({trainable_params/total_params*100:.2f}%)")

    # 3. Configure data module
    print("Setting up data module...")
    data = llm.SquadDataModule(
        train_path="/data/train.jsonl",
        validation_path="/data/val.jsonl",
        seq_length=2048,                    # Can use shorter sequences with LoRA
        global_batch_size=64,               # Can use larger batch with less memory
        micro_batch_size=2,                 # More samples per GPU
        num_workers=4,
    )

    # 4. Configure training strategy
    print("Configuring training strategy...")
    strategy = nl.MegatronStrategy(
        tensor_model_parallel_size=1,       # Single GPU is often enough for LoRA
        pipeline_model_parallel_size=1,
    )

    # 5. Configure trainer
    print("Configuring trainer...")
    trainer = nl.Trainer(
        devices=4,                          # Fewer GPUs needed with LoRA
        num_nodes=1,
        accelerator="gpu",

        # Training duration (faster with LoRA)
        max_steps=5000,

        # Validation
        val_check_interval=250,
        limit_val_batches=50,

        # Logging
        log_every_n_steps=10,

        # Checkpointing
        enable_checkpointing=True,

        # Precision
        precision="bf16-mixed",

        # Strategy
        strategy=strategy,
    )

    # 6. Configure optimizer (can use higher LR with LoRA)
    print("Configuring optimizer...")
    optim = nl.MegatronOptimizerModule(
        config=nl.OptimizerConfig(
            optimizer="adamw",
            lr=1e-4,                        # Higher LR works well with LoRA
            weight_decay=0.01,
            bf16=True,
        ),
        lr_scheduler=nl.CosineAnnealingScheduler(
            warmup_steps=500,
            max_steps=5000,
            min_lr=1e-5,
        ),
    )

    # 7. Create LoRA fine-tuning recipe
    print("Creating LoRA fine-tuning recipe...")
    recipe = llm.finetune_recipe(
        model=model,
        data=data,
        trainer=trainer,
        optim=optim,
        dir="/results/llama3_8b_lora",
        name="llama3_8b_lora_finetune",
    )

    # 8. Execute training
    print("Starting LoRA fine-tuning...")
    print("Monitor with: tensorboard --logdir /results/llama3_8b_lora/logs")
    run.run(recipe)

    print("\nLoRA fine-tuning complete!")
    print(f"LoRA adapter saved to: /results/llama3_8b_lora")
    print("\nBenefits of LoRA:")
    print(f"  - Trained only {trainable_params/total_params*100:.2f}% of parameters")
    print(f"  - ~{100-trainable_params/total_params*100:.1f}% faster training")
    print(f"  - ~{100-trainable_params/total_params*100:.1f}% less memory")
    print(f"  - Multiple adapters can be trained for different tasks")


def merge_lora_to_base():
    """
    Optional: Merge LoRA adapter back into base model for deployment
    """
    print("\nMerging LoRA adapter with base model...")

    # Load model with LoRA adapter
    model = llm.Llama3Model.restore_from("/results/llama3_8b_lora/model.nemo")

    # Merge LoRA weights into base model
    model.merge_adapter()

    # Save merged model
    model.save_to("/results/llama3_8b_merged.nemo")

    print("Merged model saved to: /results/llama3_8b_merged.nemo")


if __name__ == "__main__":
    main()

    # Optionally merge LoRA for deployment
    # merge_lora_to_base()
