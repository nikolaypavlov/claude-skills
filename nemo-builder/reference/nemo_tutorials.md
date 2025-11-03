# NeMo Framework Tutorials

**Official Documentation**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/starthere/tutorials.html`

This guide provides a comprehensive list of interactive tutorials covering all aspects of NVIDIA NeMo framework. Tutorials are available as Jupyter notebooks that can be run locally or in Google Colab.

## How to Use These Tutorials

**Running in Colab:**
- Click on any Colab link below
- Notebook opens in Google Colab with GPU support
- Follow step-by-step instructions

**Running Locally:**
- Clone NeMo repository: `git clone https://github.com/NVIDIA/NeMo.git`
- Navigate to `tutorials/` directory
- Install dependencies and run notebooks

---

## General Tutorials

Essential tutorials for getting started with NeMo framework:

| Tutorial | Description | Link |
|----------|-------------|------|
| **NeMo Fundamentals** | Getting started with NeMo framework basics | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/00_NeMo_Primer.ipynb) |
| **NeMo Models** | Understanding NeMo model architecture and components | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/01_NeMo_Models.ipynb) |
| **NeMo Adapters** | Parameter-efficient fine-tuning with adapters | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/02_NeMo_Adapters.ipynb) |
| **Hugging Face Integration** | Publishing NeMo models to Hugging Face Hub | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/Publish_NeMo_Model_On_Hugging_Face_Hub.ipynb) |
| **Audio Translation** | Building end-to-end audio translation pipelines | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/AudioTranslationSample.ipynb) |
| **Voice Swap** | Voice synthesis and conversion techniques | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/VoiceSwapSample.ipynb) |

---

## Multimodal Tutorials

Vision-language models and image generation:

| Tutorial | Description | Link |
|----------|-------------|------|
| **Data Preparation** | Organizing and preprocessing multimodal datasets | [GitHub](https://github.com/NVIDIA/NeMo/blob/main/tutorials/multimodal/Multimodal%20Data%20Preparation.ipynb) |
| **NeVA (LLaVA)** | Training vision-language models | [GitHub](https://github.com/NVIDIA/NeMo/blob/main/tutorials/multimodal/NeVA%20Tutorial.ipynb) |
| **Stable Diffusion** | Image generation fundamentals | [GitHub](https://github.com/NVIDIA/NeMo/blob/main/tutorials/multimodal/Stable%20Diffusion%20Tutorial.ipynb) |
| **DreamBooth** | Custom model fine-tuning for personalized generation | [GitHub](https://github.com/NVIDIA/NeMo/blob/main/tutorials/multimodal/DreamBooth%20Tutorial.ipynb) |
| **SDXL Quantization** | Model compression for efficient inference | [GitHub](https://github.com/NVIDIA/NeMo/blob/main/tutorials/multimodal/SDXL%20Quantization.ipynb) |

---

## Automatic Speech Recognition (ASR)

### Core ASR Tutorials

| Tutorial | Description | Link |
|----------|-------------|------|
| **ASR with NeMo** | Basic ASR implementation and training | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/ASR_with_NeMo.ipynb) |
| **Subword Tokenization** | Advanced tokenization for improved accuracy | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/ASR_with_Subword_Tokenization.ipynb) |
| **Offline ASR** | Batch processing for recorded audio | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Offline_ASR.ipynb) |
| **ASR with Adapters** | Parameter-efficient ASR fine-tuning | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/asr_adapters/ASR_with_Adapters.ipynb) |
| **Multilingual ASR** | Training models for multiple languages | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Multilang_ASR.ipynb) |

### Streaming & Real-Time ASR

| Tutorial | Description | Link |
|----------|-------------|------|
| **Online ASR (Cache-Aware)** | Real-time streaming with cache-aware mechanisms | [GitHub](https://github.com/NVIDIA/NeMo/blob/stable/tutorials/asr/Online_ASR_Microphone_Cache_Aware_Streaming.ipynb) |
| **Online ASR (Buffered)** | Alternative buffered streaming approach | [GitHub](https://github.com/NVIDIA/NeMo/blob/stable/tutorials/asr/Online_ASR_Microphone_Demo_Buffered_Streaming.ipynb) |
| **Streaming ASR** | Low-latency decoding for live audio | [GitHub](https://github.com/NVIDIA/NeMo/blob/stable/tutorials/asr/Streaming_ASR.ipynb) |
| **Buffered Transducers** | Optimized inference for streaming | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Buffered_Transducer_Inference.ipynb) |
| **Transducers with LCS** | Advanced merge algorithms for better accuracy | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Buffered_Transducer_Inference_with_LCS_Merge.ipynb) |

### Advanced ASR Topics

| Tutorial | Description | Link |
|----------|-------------|------|
| **CTC Language Fine-tuning** | Adapting acoustic models to new languages | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/ASR_CTC_Language_Finetuning.ipynb) |
| **Transducers Introduction** | Understanding sequence-to-sequence ASR | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Intro_to_Transducers.ipynb) |
| **ASR with Transducers** | End-to-end transducer training | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/ASR_with_Transducers.ipynb) |
| **Self-Supervised Pre-training** | Representation learning for ASR | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Self_Supervised_Pre_Training.ipynb) |
| **Confidence Estimation** | Reliability scoring for predictions | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/ASR_Confidence_Estimation.ipynb) |
| **Hybrid ASR-TTS** | Dual-task training frameworks | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/ASR_TTS_Tutorial.ipynb) |
| **Telephony Speech** | Handling phone-quality audio | [GitHub](https://github.com/NVIDIA/NeMo/blob/stable/tutorials/asr/ASR_for_telephony_speech.ipynb) |

### Audio Classification & Detection

| Tutorial | Description | Link |
|----------|-------------|------|
| **Speech Commands** | Sound classification for keyword spotting | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Speech_Commands.ipynb) |
| **Microphone Speech Commands** | Live keyword detection demo | [GitHub](https://github.com/NVIDIA/NeMo/blob/stable/tutorials/asr/Online_Offline_Speech_Commands_Demo.ipynb) |
| **Voice Activity Detection** | Detecting speech vs silence | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Voice_Activity_Detection.ipynb) |
| **Microphone VAD** | Real-time activity detection | [GitHub](https://github.com/NVIDIA/NeMo/blob/stable/tutorials/asr/Online_Offline_Microphone_VAD_Demo.ipynb) |
| **Offline ASR with VAD** | Combined preprocessing pipeline | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Offline_ASR_with_VAD_for_CTC_models.ipynb) |

### Speaker Recognition & Diarization

| Tutorial | Description | Link |
|----------|-------------|------|
| **Speaker Recognition** | Voice identification and verification | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/speaker_tasks/Speaker_Identification_Verification.ipynb) |
| **Speaker Diarization** | Who spoke when analysis | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/speaker_tasks/Speaker_Diarization_Inference.ipynb) |
| **ASR with Diarization** | Combined transcription and speaker attribution | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/speaker_tasks/ASR_with_SpeakerDiarization.ipynb) |

### Data Augmentation

| Tutorial | Description | Link |
|----------|-------------|------|
| **Online Noise Augmentation** | Real-time data enhancement for robustness | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/asr/Online_Noise_Augmentation.ipynb) |

---

## Text-to-Speech (TTS)

### Core TTS Tutorials

| Tutorial | Description | Link |
|----------|-------------|------|
| **NeMo TTS Primer** | Getting started with TTS fundamentals | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/NeMo_TTS_Primer.ipynb) |
| **Inference & Model Selection** | Choosing and deploying TTS models | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/Inference_ModelSelect.ipynb) |
| **Aligner Inference** | Temporal alignment techniques | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/Aligner_Inference_Examples.ipynb) |

### Model Training

| Tutorial | Description | Link |
|----------|-------------|------|
| **FastPitch & MixerTTS** | Training modern TTS architectures | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/FastPitch_MixerTTS_Training.ipynb) |
| **FastPitch Fine-tuning** | Transfer learning for custom voices | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/FastPitch_Finetuning.ipynb) |
| **German TTS Training** | Language-specific TTS customization | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/FastPitch_GermanTTS_Training.ipynb) |
| **Tacotron2 Training** | Sequence-to-sequence synthesis | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/Tacotron2_Training.ipynb) |

### Advanced TTS Control

| Tutorial | Description | Link |
|----------|-------------|------|
| **Duration & Pitch Control** | Prosody manipulation for expressiveness | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/Inference_DurationPitchControl.ipynb) |
| **Speaker Interpolation** | Multi-speaker voice generation | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/FastPitch_Speaker_Interpolation.ipynb) |
| **Pronunciation Customization** | Lexicon-based adjustments | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tts/Pronunciation_customization.ipynb) |

---

## Tools & Utilities

Essential tools for working with speech data:

| Tutorial | Description | Link |
|----------|-------------|------|
| **NeMo Forced Aligner** | Aligning text with audio timestamps | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/main/tutorials/tools/NeMo_Forced_Aligner_Tutorial.ipynb) |
| **Speech Data Explorer** | Dataset visualization and analysis | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tools/SDE_HowTo_v2.ipynb) |
| **CTC Segmentation** | Automated dataset creation from long audio | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/tools/CTC_Segmentation_Tutorial.ipynb) |

---

## Text Processing (Normalization)

Text normalization and inverse text normalization (ITN):

| Tutorial | Description | Link |
|----------|-------------|------|
| **Text Normalization** | Standardizing text formats for TTS/ASR | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/text_processing/Text_%28Inverse%29_Normalization.ipynb) |
| **ITN with Thutmose** | Tagger-based inverse normalization | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/nlp/ITN_with_Thutmose_Tagger.ipynb) |
| **WFST Tutorial** | Weighted finite-state transducers | [Colab](https://colab.research.google.com/github/NVIDIA/NeMo/blob/stable/tutorials/text_processing/WFST_Tutorial.ipynb) |

---

## Tutorial Selection Guide

**For LLM Development:**
- Start with: NeMo Fundamentals → NeMo Models
- For reference: See training guides in `reference/nemo_training.md`

**For Speech AI (ASR):**
- Beginners: ASR with NeMo → Offline ASR
- Production: Streaming ASR → Online ASR tutorials
- Advanced: Self-Supervised Pre-training → Transducers

**For Speech AI (TTS):**
- Beginners: NeMo TTS Primer → Inference & Model Selection
- Training: FastPitch & MixerTTS → FastPitch Fine-tuning
- Control: Duration & Pitch Control → Speaker Interpolation

**For Multimodal AI:**
- Start with: Data Preparation → NeVA Tutorial
- Image Gen: Stable Diffusion → DreamBooth

**For Tools:**
- Data prep: Speech Data Explorer → CTC Segmentation
- Alignment: NeMo Forced Aligner

---

## Additional Resources

- **NeMo GitHub Repository**: `https://github.com/NVIDIA/NeMo`
- **NeMo Examples**: `https://github.com/NVIDIA/NeMo/tree/main/examples`
- **Official Docs**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/`
