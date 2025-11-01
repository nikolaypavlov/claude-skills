# NeMo 2.0 Data Preparation Guide

This comprehensive guide covers data preparation for NeMo models using NeMo Curator, from raw data collection to training-ready datasets.

---

## Data Preparation Overview

### Why Data Curation Matters

**Quality over quantity:**
- High-quality data leads to better model performance
- Removing noise and duplicates improves training efficiency
- Proper formatting ensures smooth training

**NeMo Curator advantages:**
- GPU-accelerated processing (100x faster than CPU)
- Scalable to billions of documents
- Industry best practices built-in
- Integrates seamlessly with NeMo training

### Data Pipeline Stages

1. **Collection**: Gather raw data from sources
2. **Quality Filtering**: Remove low-quality content
3. **Deduplication**: Remove duplicate and near-duplicate content
4. **PII Removal**: Remove personally identifiable information
5. **Safety Filtering**: Remove toxic/harmful content
6. **Format Conversion**: Convert to training format
7. **Tokenization**: Prepare for model consumption

---

## Phase 1: Data Collection

### Common Data Sources

**Public Datasets:**
- Common Crawl (web data)
- Wikipedia dumps
- GitHub repositories
- Books (Project Gutenberg, etc.)
- Academic papers (ArXiv, PubMed)

**Custom Data:**
- Company documents
- User interactions
- Domain-specific content
- Synthetic data

### Download and Organize

**Example: Download Common Crawl:**
```bash
# Install tools
pip install warcio requests

# Download WARC files
python scripts/download_common_crawl.py \
    --output /data/raw/common_crawl \
    --num_files 100
```

**Directory structure:**
```
/data/
├── raw/                    # Original data
│   ├── common_crawl/
│   ├── wikipedia/
│   └── custom/
├── processed/             # After curation
│   ├── filtered/
│   ├── deduplicated/
│   └── final/
└── training/              # Ready for training
    ├── train.jsonl
    ├── val.jsonl
    └── test.jsonl
```

---

## Phase 2: Install NeMo Curator

### Installation

```bash
# Install NeMo Curator
pip install nemo-curator

# Or from source for latest features
git clone https://github.com/NVIDIA/NeMo-Curator.git
cd NeMo-Curator
pip install -e .
```

**Requirements:**
- Python 3.10+
- CUDA 11.8+ (for GPU acceleration)
- RAPIDS cuDF (installed with nemo-curator)
- Dask (for distributed processing)

### Verify Installation

```python
import nemo_curator as nc
print(nc.__version__)

# Check GPU availability
from nemo_curator.utils import gpu_utils
print(f"GPUs available: {gpu_utils.get_num_gpus()}")
```

---

## Phase 3: Quality Filtering

### Document Quality Filters

**Built-in quality filters:**
```python
from nemo_curator.filters import (
    DocumentFilter,
    RepeatedLinesFilter,
    RepeatedParagraphsFilter,
    RepeatedNGramsFilter,
    URLsFilter,
    BulletsFilter,
    WhiteSpaceFilter,
    ParenthesesFilter,
    EllipsisFilter,
    LongWordFilter,
)
from nemo_curator import ScoreFilter

# Create filter pipeline
quality_filters = [
    # Remove documents with too many repeated lines
    RepeatedLinesFilter(max_repeated_line_fraction=0.3),

    # Remove documents with too many repeated paragraphs
    RepeatedParagraphsFilter(max_repeated_paragraph_fraction=0.3),

    # Remove documents with excessive repeated n-grams
    RepeatedNGramsFilter(n=3, max_repeated_ngram_fraction=0.2),

    # Filter documents with too many/few URLs
    URLsFilter(min_url_count=0, max_url_count=10),

    # Filter documents with too many bullet points
    BulletsFilter(max_bullet_fraction=0.5),

    # Filter documents with excessive whitespace
    WhiteSpaceFilter(max_white_space_fraction=0.3),

    # Filter documents with too many parentheses
    ParenthesesFilter(max_parentheses_fraction=0.2),

    # Filter documents with excessive ellipsis
    EllipsisFilter(max_ellipsis_count=5),

    # Filter documents with very long words (likely corrupted)
    LongWordFilter(max_word_length=100),
]
```

### Apply Filters

```python
from nemo_curator import DocumentDataset
from nemo_curator.modifiers import DocumentModifier

# Load raw data
dataset = DocumentDataset.read_json(
    "/data/raw/documents.jsonl",
    backend="cudf",  # GPU-accelerated
)

# Apply filters
filtered_dataset = dataset
for filter_fn in quality_filters:
    filtered_dataset = filtered_dataset.filter(filter_fn)

# Save filtered data
filtered_dataset.to_json("/data/processed/filtered.jsonl")

print(f"Original documents: {len(dataset)}")
print(f"Filtered documents: {len(filtered_dataset)}")
print(f"Removed: {len(dataset) - len(filtered_dataset)} ({(1 - len(filtered_dataset)/len(dataset))*100:.1f}%)")
```

### Language Detection

**Filter by language:**
```python
from nemo_curator.filters import LanguageFilter

# Keep only English documents
lang_filter = LanguageFilter(language="en", min_score=0.8)

english_dataset = dataset.filter(lang_filter)
```

### Custom Quality Filters

```python
from nemo_curator.filters import DocumentFilter

class MinLengthFilter(DocumentFilter):
    def __init__(self, min_length=100):
        self.min_length = min_length

    def score_document(self, text):
        # Return 1 if passes, 0 if fails
        return 1 if len(text) >= self.min_length else 0

class CustomQualityFilter(DocumentFilter):
    def score_document(self, text):
        # Custom quality scoring logic
        score = 1.0

        # Penalize short documents
        if len(text) < 500:
            score *= 0.5

        # Reward documents with good punctuation
        punctuation_ratio = sum(c in '.!?' for c in text) / len(text)
        if punctuation_ratio > 0.02:
            score *= 1.5

        return score

# Use custom filters
dataset = dataset.filter(MinLengthFilter(min_length=200))
dataset = dataset.filter(CustomQualityFilter(), filter_by_score_threshold=0.7)
```

---

## Phase 4: Deduplication

### Exact Deduplication

**Remove exact duplicates:**
```python
from nemo_curator.modules import ExactDuplicates

# Find and remove exact duplicates
exact_dedup = ExactDuplicates(
    id_field="id",
    text_field="text",
    hash_method="md5",
)

deduplicated = exact_dedup(dataset)

print(f"Documents after exact dedup: {len(deduplicated)}")
```

### Fuzzy Deduplication (MinHash)

**Remove near-duplicates:**
```python
from nemo_curator.modules import FuzzyDuplicates

# Use MinHash for fuzzy deduplication
fuzzy_dedup = FuzzyDuplicates(
    id_field="id",
    text_field="text",
    seed=42,
    num_hashes=260,              # Number of hash functions
    num_buckets=20,              # Number of buckets (bands)
    similarity_threshold=0.8,    # Jaccard similarity threshold
)

fuzzy_deduplicated = fuzzy_dedup(dataset)

print(f"Documents after fuzzy dedup: {len(fuzzy_deduplicated)}")
```

### Semantic Deduplication

**Remove semantically similar documents:**
```python
from nemo_curator.modules import SemanticDuplicates

# Use embeddings for semantic deduplication
semantic_dedup = SemanticDuplicates(
    id_field="id",
    text_field="text",
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    similarity_threshold=0.9,
    batch_size=256,
)

semantic_deduplicated = semantic_dedup(dataset)
```

---

## Phase 5: PII Removal and Safety

### PII Detection and Removal

**Remove personally identifiable information:**
```python
from nemo_curator.modifiers import PIIModifier

# Configure PII removal
pii_modifier = PIIModifier(
    # What to remove
    remove_emails=True,
    remove_phone_numbers=True,
    remove_ip_addresses=True,
    remove_credit_cards=True,
    remove_ssn=True,
    remove_names=True,           # Remove person names
    remove_addresses=True,       # Remove street addresses

    # Replacement strategy
    replacement_strategy="mask",  # "mask", "redact", or "synthetic"
)

# Apply PII removal
cleaned_dataset = dataset.modify(pii_modifier)
```

**Example transformation:**
```
Before: "Contact John Doe at john.doe@email.com or call 555-123-4567"
After:  "Contact [NAME] at [EMAIL] or call [PHONE]"
```

### Safety Filtering

**Remove toxic/harmful content:**
```python
from nemo_curator.classifiers import AegisClassifier

# Use Aegis safety classifier
safety_classifier = AegisClassifier(
    model_path="nvidia/Aegis-AI-Content-Safety-LlamaGuard-Defensive-1.0",
    categories=[
        "violence",
        "hate",
        "sexual",
        "self-harm",
        "harassment",
    ],
    threshold=0.5,
)

safe_dataset = dataset.filter(safety_classifier)
```

**Custom toxicity filtering:**
```python
from nemo_curator.filters import DocumentFilter
from transformers import pipeline

class ToxicityFilter(DocumentFilter):
    def __init__(self, threshold=0.7):
        self.threshold = threshold
        self.classifier = pipeline(
            "text-classification",
            model="unitary/toxic-bert",
            device=0,  # GPU
        )

    def score_document(self, text):
        # Get toxicity score
        result = self.classifier(text[:512])[0]  # Limit length
        toxicity_score = result["score"] if result["label"] == "toxic" else 1 - result["score"]

        # Return 1 if safe, 0 if toxic
        return 0 if toxicity_score > self.threshold else 1

# Apply toxicity filter
safe_dataset = dataset.filter(ToxicityFilter(threshold=0.7))
```

---

## Phase 6: Format Conversion

### Convert to JSONL Format

**Standard format for NeMo:**
```python
import json

def convert_to_jsonl(input_docs, output_path, format_type="completion"):
    with open(output_path, 'w') as f:
        for doc in input_docs:
            if format_type == "completion":
                # For completion training
                formatted = {
                    "text": doc["content"]
                }
            elif format_type == "instruction":
                # For instruction tuning
                formatted = {
                    "input": doc["instruction"],
                    "output": doc["response"],
                }
            elif format_type == "conversation":
                # For chat models
                formatted = {
                    "messages": [
                        {"role": "user", "content": doc["user"]},
                        {"role": "assistant", "content": doc["assistant"]},
                    ]
                }

            f.write(json.dumps(formatted) + '\n')
```

### Instruction Format

**Format for supervised fine-tuning:**
```python
def format_for_sft(examples):
    formatted = []
    for example in examples:
        # Alpaca-style format
        text = f"""Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
{example['instruction']}

### Input:
{example['input']}

### Response:
{example['output']}"""

        formatted.append({"text": text})

    return formatted
```

### Chat Format

**Format for conversational models:**
```python
def format_for_chat(conversations):
    formatted = []
    for conv in conversations:
        messages = []
        for turn in conv:
            messages.append({
                "role": turn["role"],  # "user" or "assistant"
                "content": turn["content"]
            })

        formatted.append({"messages": messages})

    return formatted
```

---

## Phase 7: Synthetic Data Generation

### Generate Synthetic Instructions

**Using LLM for data augmentation:**
```python
from nemo_curator.synthetic import SyntheticDataGenerator

# Initialize generator
generator = SyntheticDataGenerator(
    model="meta-llama/Llama-2-70b-hf",
    device="cuda",
)

# Generate synthetic instructions
seed_topics = [
    "machine learning",
    "data science",
    "python programming",
]

synthetic_data = generator.generate_instructions(
    topics=seed_topics,
    num_examples_per_topic=100,
    temperature=0.7,
)

# Save synthetic data
with open("/data/synthetic_instructions.jsonl", 'w') as f:
    for item in synthetic_data:
        f.write(json.dumps(item) + '\n')
```

### Generate Conversational Data

```python
# Generate multi-turn conversations
synthetic_conversations = generator.generate_conversations(
    scenarios=[
        "Technical support",
        "Educational tutoring",
        "General knowledge Q&A",
    ],
    num_conversations_per_scenario=50,
    min_turns=3,
    max_turns=10,
)
```

### Quality Control for Synthetic Data

```python
from nemo_curator.filters import DocumentFilter

class SyntheticQualityFilter(DocumentFilter):
    def score_document(self, text):
        score = 1.0

        # Check for repetition
        words = text.split()
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.5:
            score *= 0.3

        # Check for coherence (simple heuristic)
        sentences = text.split('.')
        if len(sentences) < 2:
            score *= 0.5

        # Check for appropriate length
        if len(text) < 50 or len(text) > 5000:
            score *= 0.5

        return score

# Filter synthetic data
high_quality_synthetic = synthetic_dataset.filter(
    SyntheticQualityFilter(),
    filter_by_score_threshold=0.7
)
```

---

## Phase 8: Dataset Splitting and Statistics

### Split into Train/Val/Test

```python
import random

def split_dataset(dataset, train_ratio=0.8, val_ratio=0.1, test_ratio=0.1):
    # Shuffle dataset
    indices = list(range(len(dataset)))
    random.shuffle(indices)

    # Calculate split points
    train_end = int(len(dataset) * train_ratio)
    val_end = train_end + int(len(dataset) * val_ratio)

    # Split
    train_indices = indices[:train_end]
    val_indices = indices[train_end:val_end]
    test_indices = indices[val_end:]

    return train_indices, val_indices, test_indices

# Apply split
train_idx, val_idx, test_idx = split_dataset(dataset)

train_set = dataset.iloc[train_idx]
val_set = dataset.iloc[val_idx]
test_set = dataset.iloc[test_idx]

# Save splits
train_set.to_json("/data/training/train.jsonl")
val_set.to_json("/data/training/val.jsonl")
test_set.to_json("/data/training/test.jsonl")

print(f"Train: {len(train_set)} ({len(train_set)/len(dataset)*100:.1f}%)")
print(f"Val: {len(val_set)} ({len(val_set)/len(dataset)*100:.1f}%)")
print(f"Test: {len(test_set)} ({len(test_set)/len(dataset)*100:.1f}%)")
```

### Dataset Statistics

```python
def compute_statistics(dataset):
    stats = {
        "num_documents": len(dataset),
        "total_tokens": 0,
        "avg_tokens": 0,
        "min_tokens": float('inf'),
        "max_tokens": 0,
        "token_distribution": {},
    }

    token_counts = []
    for doc in dataset:
        tokens = len(doc["text"].split())
        token_counts.append(tokens)
        stats["total_tokens"] += tokens
        stats["min_tokens"] = min(stats["min_tokens"], tokens)
        stats["max_tokens"] = max(stats["max_tokens"], tokens)

    stats["avg_tokens"] = stats["total_tokens"] / len(dataset)

    # Percentiles
    sorted_tokens = sorted(token_counts)
    stats["p50_tokens"] = sorted_tokens[len(sorted_tokens) // 2]
    stats["p95_tokens"] = sorted_tokens[int(len(sorted_tokens) * 0.95)]
    stats["p99_tokens"] = sorted_tokens[int(len(sorted_tokens) * 0.99)]

    return stats

# Compute and display statistics
train_stats = compute_statistics(train_set)
print("Training Set Statistics:")
print(f"  Documents: {train_stats['num_documents']:,}")
print(f"  Total tokens: {train_stats['total_tokens']:,}")
print(f"  Avg tokens/doc: {train_stats['avg_tokens']:.1f}")
print(f"  Min tokens: {train_stats['min_tokens']}")
print(f"  Max tokens: {train_stats['max_tokens']}")
print(f"  P50 tokens: {train_stats['p50_tokens']}")
print(f"  P95 tokens: {train_stats['p95_tokens']}")
```

---

## Phase 9: Tokenization and Packing

### Tokenize Dataset

```python
from transformers import AutoTokenizer

# Load tokenizer
tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-2-7b-hf")

# Tokenize documents
def tokenize_dataset(dataset, tokenizer, max_length=4096):
    tokenized = []
    for doc in dataset:
        tokens = tokenizer(
            doc["text"],
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        tokenized.append({
            "input_ids": tokens["input_ids"].squeeze().tolist(),
            "attention_mask": tokens["attention_mask"].squeeze().tolist(),
        })

    return tokenized

tokenized_train = tokenize_dataset(train_set, tokenizer)
```

### Sequence Packing

**Pack multiple short sequences into one:**
```python
def pack_sequences(tokenized_data, max_length=4096):
    packed = []
    current_pack = {
        "input_ids": [],
        "attention_mask": [],
        "position_ids": [],
    }
    current_length = 0

    for item in tokenized_data:
        seq_length = len(item["input_ids"])

        # If adding this sequence exceeds max_length, start new pack
        if current_length + seq_length > max_length:
            if current_length > 0:
                packed.append(current_pack)
            current_pack = {
                "input_ids": [],
                "attention_mask": [],
                "position_ids": [],
            }
            current_length = 0

        # Add sequence to current pack
        current_pack["input_ids"].extend(item["input_ids"])
        current_pack["attention_mask"].extend(item["attention_mask"])
        current_pack["position_ids"].extend(range(seq_length))
        current_length += seq_length

    # Add final pack
    if current_length > 0:
        packed.append(current_pack)

    return packed

packed_train = pack_sequences(tokenized_train)
print(f"Packed {len(tokenized_train)} sequences into {len(packed_train)} packed sequences")
```

---

## Complete Data Preparation Pipeline

### End-to-End Example

```python
from nemo_curator import DocumentDataset
from nemo_curator.filters import *
from nemo_curator.modifiers import PIIModifier
from nemo_curator.modules import ExactDuplicates, FuzzyDuplicates
import json

def prepare_data_pipeline(
    input_path,
    output_dir,
    quality_threshold=0.7,
    dedup_similarity=0.8,
):
    print("1. Loading raw data...")
    dataset = DocumentDataset.read_json(input_path, backend="cudf")
    print(f"   Loaded {len(dataset)} documents")

    print("2. Quality filtering...")
    filters = [
        RepeatedLinesFilter(max_repeated_line_fraction=0.3),
        RepeatedParagraphsFilter(max_repeated_paragraph_fraction=0.3),
        URLsFilter(max_url_count=10),
        WhiteSpaceFilter(max_white_space_fraction=0.3),
        LanguageFilter(language="en", min_score=0.8),
    ]
    for f in filters:
        dataset = dataset.filter(f)
    print(f"   After filtering: {len(dataset)} documents")

    print("3. Exact deduplication...")
    exact_dedup = ExactDuplicates(id_field="id", text_field="text")
    dataset = exact_dedup(dataset)
    print(f"   After exact dedup: {len(dataset)} documents")

    print("4. Fuzzy deduplication...")
    fuzzy_dedup = FuzzyDuplicates(
        id_field="id",
        text_field="text",
        similarity_threshold=dedup_similarity,
    )
    dataset = fuzzy_dedup(dataset)
    print(f"   After fuzzy dedup: {len(dataset)} documents")

    print("5. PII removal...")
    pii_modifier = PIIModifier(
        remove_emails=True,
        remove_phone_numbers=True,
        remove_names=True,
    )
    dataset = dataset.modify(pii_modifier)

    print("6. Splitting dataset...")
    train_idx, val_idx, test_idx = split_dataset(dataset)
    train_set = dataset.iloc[train_idx]
    val_set = dataset.iloc[val_idx]
    test_set = dataset.iloc[test_idx]

    print("7. Saving datasets...")
    train_set.to_json(f"{output_dir}/train.jsonl")
    val_set.to_json(f"{output_dir}/val.jsonl")
    test_set.to_json(f"{output_dir}/test.jsonl")

    print("Done!")
    print(f"Final dataset: {len(train_set)} train, {len(val_set)} val, {len(test_set)} test")

# Run pipeline
prepare_data_pipeline(
    input_path="/data/raw/documents.jsonl",
    output_dir="/data/training",
)
```

---

## Best Practices

### Quality Over Quantity

1. **Filter aggressively**: Remove low-quality data
2. **Deduplicate thoroughly**: Exact and fuzzy deduplication
3. **Balance dataset**: Ensure diverse examples
4. **Validate manually**: Spot-check samples regularly

### Scalability

1. **Use GPU acceleration**: NeMo Curator's GPU backend
2. **Process in batches**: For very large datasets
3. **Distributed processing**: Use Dask for multi-GPU/node
4. **Monitor resources**: Track GPU memory and disk space

### Reproducibility

1. **Document pipeline**: Record all steps and parameters
2. **Version data**: Track dataset versions
3. **Set random seeds**: For consistent splits
4. **Save statistics**: For comparing dataset versions

---

## Troubleshooting

### Issue: Out of Memory During Processing

**Solutions:**
- Process in smaller batches
- Use Dask distributed processing
- Increase `chunksize` parameter
- Use CPU backend for initial filtering

### Issue: Deduplication Too Slow

**Solutions:**
- Use exact dedup before fuzzy dedup
- Reduce `num_hashes` parameter
- Process smaller subsets first
- Use multi-GPU processing

### Issue: Too Much Data Removed

**Solutions:**
- Relax filter thresholds
- Review filter logic
- Manually inspect removed samples
- Consider if data source is appropriate

---

## Additional Resources

### NeMo Documentation

- **NeMo Curator**: `https://docs.nvidia.com/nemo/curator/latest/index.html`
- **NeMo Curator GitHub**: https://github.com/NVIDIA/NeMo-Curator

### Research Papers

- **Data Curation Best Practices**: https://arxiv.org/abs/2305.16264
- **Quality Filters (C4)**: https://arxiv.org/abs/2101.00027
- **MinHash Deduplication**: https://arxiv.org/abs/1907.04347
- **The Pile**: https://arxiv.org/abs/2101.00027

---

For related topics, see:
- [📋 NeMo Best Practices](./nemo_best_practices.md)
- [🎯 Training Guide](./nemo_training.md)
- [🚀 Deployment Guide](./nemo_deployment.md)
