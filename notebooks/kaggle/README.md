# PRIXON Kaggle training

This directory contains the first reproducible QLoRA adapter-training notebook. It does **not**
train a new foundation model and does **not** upload or modify the original Qwen checkpoint.

## First run

1. Open `PRIXON_QLoRA_Starter.ipynb` in Kaggle.
2. Select a GPU accelerator. Choose a T4 when available; P100 availability and accelerator
   choices can vary by account and current platform capacity.
3. Enable Internet for the notebook session so Hugging Face can resolve the public base model
   and Python packages.
4. Add a Kaggle Dataset containing the reviewed PRIXON JSONL examples. The notebook expects
   `/kaggle/input/prixon-training-data/seed_v1.jsonl`. For a pipeline smoke check only, it can
   fall back to the repository's eight-example synthetic seed set; the notebook blocks a real
   training run below 100 eligible examples.
5. Run cells from top to bottom. Record the model revision, package versions, configuration,
   data manifest, baseline generations and adapter artifact.
6. Download the generated adapter ZIP from the Kaggle output panel and retain the accompanying
   manifest. Do not merge it into the foundation model for the first release.

## Dataset requirements

The training file is UTF-8 JSONL. Each line requires:
- `schema_version: 1`
- a unique `id`
- a category: initially only `identity`, `conversation_style` or `contextual_language`
- source name, licence and `review_status: approved`
- `data_classification: public`, `synthetic` or `user_contributed`
- explicit `user_consent: true` for user-contributed examples
- a `messages` array ending in an assistant response

Do not upload private computer logs, credentials, API keys, cookies, messages from other people
without permission, proprietary material without a licence, or sensitive personal data.
The seed file is synthetic and intentionally tiny; it is a schema/sample fixture, not a useful
fine-tuning corpus.

## First adapter scope

The first adapter is limited to PRIXON identity, conversational style and contextual language.
It must not be trained on general reasoning, coding, mathematics, Windows internals, networking,
cybersecurity or troubleshooting in this phase. Those capabilities are preservation benchmarks.
Improve them later with retrieval, live evidence, tools and orchestration before considering
specialist adapters.

## Resource expectations

QLoRA uses a quantized 4-bit base model for training while keeping the foundation parameters
frozen and training small LoRA adapter weights. A single 16 GB GPU can be a reasonable starting
point with batch size 1, gradient accumulation, gradient checkpointing and a 2048-token sequence
limit, but success depends on the available accelerator, memory fragmentation and package
compatibility. Reduce sequence length or target modules if memory is insufficient; do not switch
to full fine-tuning.

Kaggle GPU quota and available accelerator types vary. Check the current quota and session
settings before starting long runs. Save checkpoints to `/kaggle/working` and copy important
artifacts into notebook output before the session expires.

## Promotion gate

The notebook produces an adapter candidate, not an approved release. Review its generations and
compare it with the untouched Qwen foundation on a held-out benchmark covering:
- general reasoning and multi-step tasks
- coding and structured outputs
- mathematics and planning
- Windows internals and troubleshooting
- networking and defensive cybersecurity
- language/context understanding and over-refusal

Keep the foundation, tokenizer and original Qwen chat template pinned. Reject the adapter if
important capabilities regress, output format reliability drops, or factuality/safety worsens.
