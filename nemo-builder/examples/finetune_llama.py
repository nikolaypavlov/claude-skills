"""
Fine-tune Llama 3 8B on custom dataset using NeMo 2.0

This example shows how to fine-tune a Llama model using NeMo Run
with the recommended configuration for supervised fine-tuning.
"""

from nemo.collections import llm
from nemo import lightning as nl
import nemo_run as run


def main():
    # 1. Configure base model
    print("Configuring Llama 3 8B model...")
    model = llm.Llama3Config8B()

    # 2. Configure data module
    print("Setting up data module...")
    data = llm.SquadDataModule(
        # Data paths
        train_path="/data/train.jsonl",
        validation_path="/data/val.jsonl",
        test_path="/data/test.jsonl",

        # Sequence and batch configuration
        seq_length=4096,                    # Maximum sequence length
        global_batch_size=128,              # Total batch size across all GPUs
        micro_batch_size=1,                 # Batch size per GPU

        # DataLoader configuration
        num_workers=4,
        pin_memory=True,
    )

    # 3. Configure distributed training strategy
    print("Configuring training strategy...")
    strategy = nl.MegatronStrategy(
        tensor_model_parallel_size=2,       # Split model across 2 GPUs
        pipeline_model_parallel_size=1,     # No pipeline parallelism
        sequence_parallel=True,             # Enable sequence parallelism
    )

    # 4. Configure trainer
    print("Configuring trainer...")
    trainer = nl.Trainer(
        # Compute resources
        devices=8,                          # Number of GPUs per node
        num_nodes=1,                        # Number of nodes
        accelerator="gpu",

        # Training duration
        max_steps=10000,

        # Validation
        val_check_interval=500,             # Validate every 500 steps
        limit_val_batches=50,               # Limit validation batches

        # Logging
        log_every_n_steps=10,

        # Checkpointing
        enable_checkpointing=True,

        # Precision
        precision="bf16-mixed",             # Mixed BF16/FP32 precision

        # Strategy
        strategy=strategy,
    )

    # 5. Configure optimizer and scheduler
    print("Configuring optimizer...")
    optim = nl.MegatronOptimizerModule(
        config=nl.OptimizerConfig(
            optimizer="adam",
            lr=1e-5,                        # Learning rate
            weight_decay=0.01,
            bf16=True,
        ),
        lr_scheduler=nl.CosineAnnealingScheduler(
            warmup_steps=1000,              # Linear warmup
            max_steps=10000,
            min_lr=1e-6,                    # Minimum learning rate
        ),
    )

    # 6. Compose fine-tuning recipe
    print("Creating fine-tuning recipe...")
    recipe = llm.finetune_recipe(
        model=model,
        data=data,
        trainer=trainer,
        optim=optim,
        dir="/results/llama3_8b_finetuned",
        name="llama3_8b_custom_finetune",
    )

    # 7. Execute training
    print("Starting training...")
    print("Monitor progress with: tensorboard --logdir /results/llama3_8b_finetuned/logs")
    run.run(recipe)

    print("Training complete!")
    print("Model saved to: /results/llama3_8b_finetuned")


if __name__ == "__main__":
    main()
