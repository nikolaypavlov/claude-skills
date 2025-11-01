# NeMo Speech AI Tools Guide

This guide covers the specialized tools available in NeMo for developing speech AI applications, including ASR, TTS, and dataset preparation.

**Official Documentation**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tools/intro.html`

---

## Overview

NeMo provides a comprehensive toolkit for speech processing development, designed to support the entire lifecycle of speech AI projects from data preparation to model deployment.

### Available Tools

**Core Speech Tools:**
1. **NeMo Forced Aligner (NFA)** - Text-to-audio alignment at phoneme/word level
2. **CTC-Segmentation Tool** - Dataset creation based on CTC-segmentation
3. **Speech Data Explorer** - Interactive visualization and analysis of speech datasets
4. **ASR Model Comparison Tool** - Performance evaluation across different ASR models
5. **ASR Evaluator** - Accuracy measurement for speech recognition systems

**Related Tools:**
- **Speech Data Processor (SDP)** - Comprehensive speech data processing toolkit
- **Text Normalization** - Standard and inverse text normalization utilities

---

## Speech Data Explorer (SDE)

### What is Speech Data Explorer?

**Speech Data Explorer** is a Dash-based web application for interactive exploration and analysis of speech datasets. It enables researchers and engineers to understand and validate speech data through visualization and statistical analysis.

**Documentation**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tools/speech_data_explorer.html`

### Key Capabilities

**1. Dataset Statistics:**
- Alphabet and vocabulary analysis
- Duration-based histograms
- Dataset size metrics (total hours, utterance count)
- Character and word frequency distributions

**2. Interactive Navigation:**
- Sortable and filterable data tables
- Individual utterance inspection
- Waveform and spectrogram visualization
- Integrated audio playback

**3. Error Analysis:**
- Word Error Rate (WER) calculation
- Character Error Rate (CER) metrics
- Word Match Rate visualization
- Side-by-side comparison of reference and predicted transcripts

**4. Audio Analysis:**
- Peak level estimation
- Frequency bandwidth analysis
- Duration statistics
- Audio quality metrics

### Installation and Setup

```bash
# Install dependencies
cd NeMo
pip install -r tools/speech_data_explorer/requirements.txt

# Launch Speech Data Explorer
python tools/speech_data_explorer/data_explorer.py \
    --manifest path/to/manifest.json
```

### Data Format

**Manifest JSON format:**
```json
{
  "audio_filepath": "/path/to/audio.wav",
  "duration": 5.23,
  "text": "reference transcription"
}
{
  "audio_filepath": "/path/to/audio2.wav",
  "duration": 3.45,
  "text": "another transcription",
  "pred_text": "predicted transcription"
}
```

**Required fields:**
- `audio_filepath`: Path to audio file
- `duration`: Audio duration in seconds
- `text`: Reference transcription

**Optional fields:**
- `pred_text`: Predicted transcription (for error analysis)
- Custom metadata fields

### Use Cases

**1. Dataset Quality Validation:**
```python
# Use SDE to identify:
# - Transcription errors
# - Audio quality issues
# - Duration outliers
# - Vocabulary coverage gaps
```

**2. Error Analysis:**
```python
# Compare predictions vs ground truth:
# - Identify systematic errors
# - Find problematic audio conditions
# - Discover transcription inconsistencies
```

**3. Data Exploration:**
```python
# Understand dataset characteristics:
# - Duration distribution
# - Vocabulary diversity
# - Character frequency
# - Speaker demographics (if metadata available)
```

### Practical Workflow

**Step 1: Load Dataset**
- Prepare manifest file with audio paths and transcriptions
- Launch Speech Data Explorer

**Step 2: Explore Statistics**
- Review duration histograms
- Check vocabulary coverage
- Analyze character distributions

**Step 3: Filter and Sort**
- Filter by duration, WER, or custom criteria
- Sort to find outliers or problematic samples
- Identify out-of-vocabulary words

**Step 4: Inspect Individual Samples**
- Listen to audio
- View waveforms and spectrograms
- Compare reference vs predicted text
- Flag samples for correction or removal

**Step 5: Export Filtered Data**
- Create cleaned subset
- Generate reports on data quality
- Document findings for team

---

## NeMo Forced Aligner (NFA)

### What is Forced Alignment?

**Forced alignment** is the process of aligning text transcriptions with audio at the phoneme or word level, producing timestamps for when each word or phoneme is spoken.

### Use Cases

**1. TTS Training Data Preparation:**
- Create accurate phoneme-level alignments
- Generate training targets for attention mechanisms
- Validate audio-text correspondence

**2. Subtitle Generation:**
- Automatic subtitle timing
- Word-level timestamps for accessibility
- Precise synchronization with video

**3. Dataset Validation:**
- Verify audio matches transcription
- Detect misaligned segments
- Quality control for speech datasets

**4. Prosody Analysis:**
- Study speaking rate variations
- Analyze phoneme durations
- Research speech patterns

### Key Features

- **High accuracy**: Uses neural acoustic models
- **Multiple granularities**: Word-level or phoneme-level alignment
- **Language support**: Multiple languages available
- **Batch processing**: Efficient processing of large datasets
- **NeMo integration**: Works seamlessly with NeMo ASR models

### Usage Example

```bash
# Basic forced alignment
python tools/nemo_forced_aligner/align.py \
    --manifest path/to/manifest.json \
    --model_path path/to/asr_model.nemo \
    --output_dir /output/alignments \
    --align_using_pred_text false
```

**Manifest format:**
```json
{
  "audio_filepath": "audio.wav",
  "text": "the quick brown fox",
  "duration": 2.5
}
```

**Output format:**
```json
{
  "audio_filepath": "audio.wav",
  "text": "the quick brown fox",
  "words": [
    {"word": "the", "start": 0.0, "end": 0.2},
    {"word": "quick", "start": 0.2, "end": 0.5},
    {"word": "brown", "start": 0.5, "end": 0.8},
    {"word": "fox", "start": 0.8, "end": 1.1}
  ]
}
```

---

## CTC-Segmentation Tool

### What is CTC-Segmentation?

**CTC-Segmentation** is a tool for creating speech datasets by automatically segmenting long audio files with corresponding text transcriptions into shorter, aligned segments.

### Use Cases

**1. Dataset Creation:**
- Convert audiobooks with text to training data
- Segment podcast transcripts
- Create datasets from long-form content

**2. Data Augmentation:**
- Extract clean segments from noisy audio
- Filter out low-confidence alignments
- Create high-quality training samples

**3. Subtitle Generation:**
- Automatic segmentation for subtitles
- Sentence-level timing
- Natural break point detection

### How It Works

**Process:**
1. Load long audio file and full transcript
2. Use CTC acoustic model to compute frame-level probabilities
3. Find optimal segmentation based on alignment scores
4. Extract segments with timestamps
5. Filter by confidence threshold

### Key Features

- **Automatic segmentation**: No manual annotation needed
- **Confidence scores**: Quality filtering built-in
- **Batch processing**: Handle large corpora efficiently
- **Flexible granularity**: Segment by sentence, phrase, or custom boundaries

### Usage Example

```bash
# Segment audio using CTC
python tools/ctc_segmentation/segment_audio.py \
    --audio long_audio.wav \
    --text transcript.txt \
    --model_path asr_model.nemo \
    --output_manifest segments.json \
    --min_segment_length 1.0 \
    --max_segment_length 15.0
```

**Input text format:**
```
This is the first sentence.
This is the second sentence.
This is the third sentence.
```

**Output manifest:**
```json
{
  "audio_filepath": "segment_0001.wav",
  "text": "This is the first sentence.",
  "duration": 2.3,
  "confidence": 0.95
}
{
  "audio_filepath": "segment_0002.wav",
  "text": "This is the second sentence.",
  "duration": 2.8,
  "confidence": 0.92
}
```

---

## ASR Evaluator

### Purpose

**ASR Evaluator** measures the accuracy of automatic speech recognition systems using standard metrics.

### Key Metrics

**Word Error Rate (WER):**
```
WER = (Substitutions + Deletions + Insertions) / Total Words
```

**Character Error Rate (CER):**
```
CER = (Substitutions + Deletions + Insertions) / Total Characters
```

**Word Match Rate (WMR):**
```
WMR = Correct Words / Total Words
```

### Usage

```bash
# Evaluate ASR model
python tools/asr_evaluator/evaluate.py \
    --manifest test_manifest.json \
    --model_path asr_model.nemo \
    --batch_size 16 \
    --output_file results.json
```

**Output includes:**
- Overall WER, CER, WMR
- Per-utterance metrics
- Confusion matrix
- Common error patterns

---

## ASR Model Comparison Tool

### Purpose

Compare performance of multiple ASR models side-by-side to select the best model for your use case.

### Features

**1. Multi-model Evaluation:**
- Test multiple models on same dataset
- Fair comparison with identical test conditions
- Batch processing for efficiency

**2. Detailed Analytics:**
- Per-model metrics (WER, CER)
- Per-utterance comparison
- Error type breakdown
- Speed/accuracy trade-offs

**3. Visualization:**
- Performance charts
- Error distribution plots
- Speed comparison graphs

### Usage

```bash
# Compare models
python tools/asr_model_comparison/compare.py \
    --models model1.nemo model2.nemo model3.nemo \
    --test_manifest test.json \
    --output_dir comparison_results
```

**Output:**
- Comparative metrics table
- Error analysis reports
- Visualization plots
- Recommendations

---

## Speech Data Processor (SDP)

### Overview

**Speech Data Processor** is a comprehensive toolkit for processing speech data at scale. It's hosted separately but integrates with NeMo.

**Documentation**: Check NeMo documentation for SDP integration

### Capabilities

**1. Data Preprocessing:**
- Audio format conversion
- Sample rate normalization
- Silence trimming
- Audio augmentation

**2. Text Processing:**
- Text normalization
- Tokenization
- Vocabulary extraction
- Language-specific processing

**3. Manifest Generation:**
- Create training manifests
- Validate data format
- Generate statistics

**4. Quality Control:**
- Audio quality checks
- Duration filtering
- Text validation
- Duplicate detection

---

## Text Normalization Tools

### Standard Text Normalization

**Purpose:** Convert written text to spoken form for TTS.

**Examples:**
- `$100` → "one hundred dollars"
- `Dr.` → "doctor"
- `2023` → "twenty twenty three"

### Inverse Text Normalization

**Purpose:** Convert spoken form to written form for ASR.

**Examples:**
- "one hundred dollars" → "$100"
- "doctor" → "Dr."
- "twenty twenty three" → "2023"

### Usage

```python
from nemo_text_processing.text_normalization import Normalizer

# Standard normalization (for TTS)
normalizer = Normalizer(input_case="cased", lang="en")
normalized = normalizer.normalize("I paid $100 in 2023")
# Output: "I paid one hundred dollars in twenty twenty three"

# Inverse normalization (for ASR)
from nemo_text_processing.inverse_text_normalization import InverseNormalizer

inv_normalizer = InverseNormalizer(lang="en")
text = inv_normalizer.inverse_normalize("I paid one hundred dollars")
# Output: "I paid $100"
```

---

## Practical Workflows

### Workflow 1: Creating ASR Training Dataset

**Goal:** Convert audiobook + text to training dataset

**Steps:**

1. **Segment audio:**
   ```bash
   # Use CTC-Segmentation
   python tools/ctc_segmentation/segment_audio.py \
       --audio audiobook.mp3 \
       --text book_text.txt \
       --model_path pretrained_asr.nemo \
       --output_manifest segments.json
   ```

2. **Validate segments:**
   ```bash
   # Use Speech Data Explorer
   python tools/speech_data_explorer/data_explorer.py \
       --manifest segments.json
   # Manually review and filter low-quality segments
   ```

3. **Refine alignments:**
   ```bash
   # Use Forced Aligner for precise timestamps
   python tools/nemo_forced_aligner/align.py \
       --manifest filtered_segments.json \
       --model_path asr_model.nemo \
       --output_dir alignments/
   ```

4. **Final validation:**
   ```bash
   # Export cleaned dataset
   python scripts/create_final_manifest.py \
       --input alignments/ \
       --output train_manifest.json
   ```

### Workflow 2: ASR Model Evaluation

**Goal:** Evaluate ASR model on test set

**Steps:**

1. **Run inference:**
   ```bash
   python tools/asr_evaluator/evaluate.py \
       --manifest test.json \
       --model_path my_model.nemo \
       --output_file predictions.json
   ```

2. **Analyze errors:**
   ```bash
   # Use Speech Data Explorer for error analysis
   python tools/speech_data_explorer/data_explorer.py \
       --manifest predictions.json
   # Review high-WER utterances
   ```

3. **Compare models:**
   ```bash
   # Test multiple models
   python tools/asr_model_comparison/compare.py \
       --models model_v1.nemo model_v2.nemo \
       --test_manifest test.json
   ```

### Workflow 3: TTS Data Preparation

**Goal:** Prepare high-quality data for TTS training

**Steps:**

1. **Forced alignment:**
   ```bash
   # Get phoneme-level alignments
   python tools/nemo_forced_aligner/align.py \
       --manifest recordings.json \
       --model_path asr_model.nemo \
       --align_using_pred_text false \
       --use_local_attention true
   ```

2. **Text normalization:**
   ```python
   # Normalize text to spoken form
   from nemo_text_processing.text_normalization import Normalizer

   normalizer = Normalizer(lang="en")
   for item in dataset:
       item["normalized_text"] = normalizer.normalize(item["text"])
   ```

3. **Quality validation:**
   ```bash
   # Check alignment quality
   python tools/speech_data_explorer/data_explorer.py \
       --manifest aligned_data.json
   ```

---

## Best Practices

### Data Validation

1. **Always use Speech Data Explorer** before training
   - Catch transcription errors early
   - Identify audio quality issues
   - Remove outliers

2. **Set quality thresholds**
   - Minimum duration: 1 second
   - Maximum duration: 15 seconds
   - Confidence score: > 0.8
   - WER on validation: < 15%

3. **Regular quality checks**
   - Sample random utterances
   - Listen and verify alignment
   - Check for systematic errors

### Tool Selection

**For dataset creation:**
- Use **CTC-Segmentation** for long audio
- Use **Forced Aligner** for precise timing
- Use **SDP** for batch preprocessing

**For model evaluation:**
- Use **ASR Evaluator** for quick metrics
- Use **Model Comparison Tool** for multiple models
- Use **Speech Data Explorer** for error analysis

**For TTS preparation:**
- Use **Forced Aligner** for phoneme timing
- Use **Text Normalization** for proper text format
- Use **Speech Data Explorer** for quality checks

### Performance Tips

1. **Batch processing**: Process multiple files in parallel
2. **GPU acceleration**: Use GPU for forced alignment and evaluation
3. **Caching**: Cache normalized text and model outputs
4. **Incremental processing**: Save intermediate results

---

## Integration with NeMo Training

### From Tools to Training

**Complete pipeline:**

```python
# 1. Prepare data with tools
# (Run CTC-Segmentation, Forced Alignment, etc.)

# 2. Load prepared manifest
from nemo.collections.asr.data import AudioToCharDataset

train_dataset = AudioToCharDataset(
    manifest_filepath="prepared_train.json",
    labels=labels,
    sample_rate=16000,
)

# 3. Train model
from nemo.collections.asr.models import EncDecCTCModel

model = EncDecCTCModel(cfg=model_cfg)
trainer.fit(model, train_dataloader)

# 4. Evaluate with tools
# (Run ASR Evaluator on test set)
```

---

## Troubleshooting

### Common Issues

**Issue 1: Low alignment confidence**

**Solution:**
- Use better ASR model for alignment
- Clean audio (denoise, normalize)
- Verify transcription accuracy

**Issue 2: Segmentation errors**

**Solution:**
- Adjust min/max segment length
- Use different CTC threshold
- Pre-segment audio at natural breaks

**Issue 3: High WER in evaluation**

**Solution:**
- Check audio quality
- Verify correct model for domain
- Review error patterns in SDE
- Consider model fine-tuning

---

## Additional Resources

### Official Documentation

- **Speech Tools Overview**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tools/intro.html`
- **Speech Data Explorer**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tools/speech_data_explorer.html`
- **NeMo ASR Collection**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/intro.html`
- **NeMo TTS Collection**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tts/intro.html`

### Community Resources

- **GitHub Tools**: https://github.com/NVIDIA/NeMo/tree/main/tools
- **Examples**: https://github.com/NVIDIA/NeMo/tree/main/examples/asr
- **Tutorials**: Check NeMo documentation for step-by-step tutorials

---

For related topics, see:
- [📋 NeMo Best Practices](./nemo_best_practices.md)
- [🎯 Training Guide](./nemo_training.md)
- [📊 Data Preparation Guide](./nemo_data_preparation.md)
- [📘 NeMo 2.0 Guide](./nemo_2.0_guide.md)
