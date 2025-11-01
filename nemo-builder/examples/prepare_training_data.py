"""
Data Preparation Pipeline using NeMo Curator

This example demonstrates a complete data preparation workflow:
1. Load raw data
2. Quality filtering
3. Deduplication (exact and fuzzy)
4. PII removal
5. Format conversion
6. Dataset splitting
"""

import nemo_curator as nc
from nemo_curator import DocumentDataset
from nemo_curator.filters import (
    RepeatedLinesFilter,
    RepeatedParagraphsFilter,
    URLsFilter,
    WhiteSpaceFilter,
    LanguageFilter,
    DocumentFilter,
)
from nemo_curator.modifiers import PIIModifier
from nemo_curator.modules import ExactDuplicates, FuzzyDuplicates
import json
import random
from pathlib import Path


def load_raw_data(input_path: str, output_path: str):
    """
    Load raw data and convert to DocumentDataset format
    """
    print(f"Loading raw data from {input_path}...")

    # Example: Convert raw text files to JSONL
    documents = []
    for file_path in Path(input_path).glob("*.txt"):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            documents.append({
                "id": str(file_path),
                "text": content,
            })

    # Save as JSONL
    with open(output_path, 'w', encoding='utf-8') as f:
        for doc in documents:
            f.write(json.dumps(doc) + '\n')

    print(f"Saved {len(documents)} documents to {output_path}")
    return output_path


def apply_quality_filters(dataset: DocumentDataset) -> DocumentDataset:
    """
    Apply comprehensive quality filtering
    """
    print("\nApplying quality filters...")
    initial_count = len(dataset)

    # Define filters
    filters = [
        # Remove documents with excessive repeated content
        RepeatedLinesFilter(max_repeated_line_fraction=0.3),
        RepeatedParagraphsFilter(max_repeated_paragraph_fraction=0.3),

        # Filter by URL count
        URLsFilter(min_url_count=0, max_url_count=10),

        # Remove documents with excessive whitespace
        WhiteSpaceFilter(max_white_space_fraction=0.3),

        # Keep only English documents
        LanguageFilter(language="en", min_score=0.8),
    ]

    # Apply each filter
    filtered_dataset = dataset
    for filter_fn in filters:
        before = len(filtered_dataset)
        filtered_dataset = filtered_dataset.filter(filter_fn)
        removed = before - len(filtered_dataset)
        print(f"  {filter_fn.__class__.__name__}: removed {removed} documents ({removed/before*100:.1f}%)")

    total_removed = initial_count - len(filtered_dataset)
    print(f"Total removed: {total_removed} documents ({total_removed/initial_count*100:.1f}%)")
    print(f"Remaining: {len(filtered_dataset)} documents")

    return filtered_dataset


def deduplicate_dataset(dataset: DocumentDataset) -> DocumentDataset:
    """
    Remove exact and near-duplicate documents
    """
    print("\nDeduplicating dataset...")
    initial_count = len(dataset)

    # Exact deduplication
    print("  Running exact deduplication...")
    exact_dedup = ExactDuplicates(
        id_field="id",
        text_field="text",
        hash_method="md5",
    )
    dataset = exact_dedup(dataset)
    exact_removed = initial_count - len(dataset)
    print(f"    Removed {exact_removed} exact duplicates ({exact_removed/initial_count*100:.1f}%)")

    # Fuzzy deduplication (MinHash)
    print("  Running fuzzy deduplication...")
    fuzzy_dedup = FuzzyDuplicates(
        id_field="id",
        text_field="text",
        seed=42,
        num_hashes=260,                     # Number of hash functions
        num_buckets=20,                     # Number of bands
        similarity_threshold=0.8,           # Jaccard similarity threshold
    )
    before_fuzzy = len(dataset)
    dataset = fuzzy_dedup(dataset)
    fuzzy_removed = before_fuzzy - len(dataset)
    print(f"    Removed {fuzzy_removed} near-duplicates ({fuzzy_removed/before_fuzzy*100:.1f}%)")

    total_removed = initial_count - len(dataset)
    print(f"Total duplicates removed: {total_removed} ({total_removed/initial_count*100:.1f}%)")
    print(f"Remaining: {len(dataset)} documents")

    return dataset


def remove_pii(dataset: DocumentDataset) -> DocumentDataset:
    """
    Remove personally identifiable information
    """
    print("\nRemoving PII...")

    pii_modifier = PIIModifier(
        # What to remove
        remove_emails=True,
        remove_phone_numbers=True,
        remove_ip_addresses=True,
        remove_credit_cards=True,
        remove_ssn=True,
        remove_names=True,
        remove_addresses=True,

        # Replacement strategy
        replacement_strategy="mask",        # Options: "mask", "redact", "synthetic"
    )

    # Apply PII removal
    cleaned_dataset = dataset.modify(pii_modifier)

    print(f"PII removed from {len(cleaned_dataset)} documents")

    return cleaned_dataset


def split_dataset(dataset: DocumentDataset, output_dir: str, train_ratio=0.8, val_ratio=0.1, test_ratio=0.1):
    """
    Split dataset into train/val/test sets
    """
    print(f"\nSplitting dataset (train: {train_ratio}, val: {val_ratio}, test: {test_ratio})...")

    # Convert to list for shuffling
    data_list = list(dataset)
    random.shuffle(data_list)

    # Calculate split points
    total = len(data_list)
    train_end = int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)

    # Split
    train_data = data_list[:train_end]
    val_data = data_list[train_end:val_end]
    test_data = data_list[val_end:]

    # Save splits
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    train_path = output_path / "train.jsonl"
    val_path = output_path / "val.jsonl"
    test_path = output_path / "test.jsonl"

    for data, path in [(train_data, train_path), (val_data, val_path), (test_data, test_path)]:
        with open(path, 'w', encoding='utf-8') as f:
            for doc in data:
                f.write(json.dumps(doc) + '\n')

    print(f"  Train: {len(train_data)} documents -> {train_path}")
    print(f"  Val: {len(val_data)} documents -> {val_path}")
    print(f"  Test: {len(test_data)} documents -> {test_path}")

    return train_path, val_path, test_path


def compute_statistics(jsonl_path: str):
    """
    Compute and display dataset statistics
    """
    print(f"\nComputing statistics for {jsonl_path}...")

    token_counts = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            doc = json.loads(line)
            tokens = len(doc["text"].split())
            token_counts.append(tokens)

    if not token_counts:
        print("  No documents found")
        return

    sorted_tokens = sorted(token_counts)
    total_tokens = sum(token_counts)

    print(f"  Documents: {len(token_counts):,}")
    print(f"  Total tokens: {total_tokens:,}")
    print(f"  Avg tokens/doc: {total_tokens/len(token_counts):.1f}")
    print(f"  Min tokens: {min(token_counts)}")
    print(f"  Max tokens: {max(token_counts)}")
    print(f"  Median tokens: {sorted_tokens[len(sorted_tokens)//2]}")
    print(f"  P95 tokens: {sorted_tokens[int(len(sorted_tokens)*0.95)]}")
    print(f"  P99 tokens: {sorted_tokens[int(len(sorted_tokens)*0.99)]}")


def main():
    """
    Complete data preparation pipeline
    """
    print("=" * 60)
    print("NeMo Curator Data Preparation Pipeline")
    print("=" * 60)

    # Configuration
    raw_data_dir = "/data/raw"
    intermediate_file = "/data/intermediate/raw_documents.jsonl"
    output_dir = "/data/training"

    # Step 1: Load raw data
    # (Skip if you already have JSONL format)
    # load_raw_data(raw_data_dir, intermediate_file)

    # Step 2: Load as DocumentDataset
    print("\nLoading dataset...")
    dataset = DocumentDataset.read_json(
        intermediate_file,
        backend="cudf",                     # Use GPU acceleration
    )
    print(f"Loaded {len(dataset)} documents")

    # Step 3: Quality filtering
    dataset = apply_quality_filters(dataset)

    # Step 4: Deduplication
    dataset = deduplicate_dataset(dataset)

    # Step 5: PII removal
    dataset = remove_pii(dataset)

    # Step 6: Save processed dataset
    print("\nSaving processed dataset...")
    processed_path = "/data/processed/cleaned_documents.jsonl"
    dataset.to_json(processed_path)
    print(f"Saved to: {processed_path}")

    # Step 7: Split into train/val/test
    train_path, val_path, test_path = split_dataset(dataset, output_dir)

    # Step 8: Compute statistics
    print("\n" + "=" * 60)
    print("Dataset Statistics")
    print("=" * 60)
    compute_statistics(train_path)
    compute_statistics(val_path)
    compute_statistics(test_path)

    print("\n" + "=" * 60)
    print("Data preparation complete!")
    print("=" * 60)
    print(f"\nReady for training:")
    print(f"  Train: {train_path}")
    print(f"  Val: {val_path}")
    print(f"  Test: {test_path}")


if __name__ == "__main__":
    # Set random seed for reproducibility
    random.seed(42)

    # Run pipeline
    main()
