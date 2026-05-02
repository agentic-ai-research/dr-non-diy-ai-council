# Free providers — keeping the council at $0

The council runs on free-tier inference. When a provider's daily quota hits, the [resilience.md](../../docs/resilience.md) endpoint failover kicks in and the next provider takes over. As long as your `endpoints` arrays are stocked, **a quota outage on any single provider is invisible to the user.**

This doc lists every provider currently used (or worth using), with signup links and the daily quotas you can rely on.

## Currently in active use

| Provider | Free tier | Daily quota | Bots that use it as primary | Notes |
|---|---|---|---|---|
| **NVIDIA NIM** | Yes (developer key) | ~10k requests/day across models | Tenet, Radar, Hannah, Ana, Civic, Aviva, Bob, Pip, Nun, Ada (fallback), noN | Most generous free tier; widest model catalog. [Sign up](https://build.nvidia.com/). |
| **Groq** | Yes (developer key) | ~100k tokens/day per model (TPD) | Otto | Fastest inference on the bench; Otto's `llama-3.3-70b-versatile` blew through TPD on 2026-05-02. |
| **ThaiLLM (Pathumma)** | Yes (community) | Generous, no published cap | Ada | Thai-native model. [Sign up](https://thaillm.or.th). |
| **Anthropic** | No (paid only) | n/a — pay per token | Eve, LOL | Cost ~$3/mo at council usage. The one paid bot tier. |

## Worth adding to your `endpoints` arrays (free tier, not yet wired)

| Provider | Free tier | Daily quota | Best for | Sign up |
|---|---|---|---|---|
| **Cerebras Cloud** | Yes | ~1M tokens/day on Llama 3.3 70B | Otto / Hannah / Radar fallback. ~5x faster than Groq. | [cerebras.ai](https://cloud.cerebras.ai) |
| **SambaNova Cloud** | Yes | ~5k requests/day across models | Hannah / Radar fallback for Llama 405B. | [sambanova.ai](https://cloud.sambanova.ai) |
| **Google AI Studio (Gemini)** | Yes | 1500 requests/day on Flash, 50 requests/day on Pro | Vision tasks (Hermes broken-vision-config bug); Ada fallback (Thai). | [aistudio.google.com](https://aistudio.google.com) |
| **Mistral Le Plateforme** | Yes | Generous on `mistral-small-latest` | Pip / Civic fallback. | [console.mistral.ai](https://console.mistral.ai) |
| **Together AI** | Yes (free credits at signup) | $5 free credits + ongoing free tier on selected models | Eve / LOL fallback (Qwen Coder, etc.). | [together.ai](https://www.together.ai) |
| **HuggingFace Inference API** | Yes | Rate-limited but free for small models | Last-resort fallback for narrow tasks. | [huggingface.co/inference-api](https://huggingface.co/inference-api) |
| **DeepSeek (direct)** | No (paid) | n/a — but ~$0.14 / M tokens — *functionally* near-free | Bob / Nun primary if you'd rather pay than depend on NIM's TPD shifts. | [platform.deepseek.com](https://platform.deepseek.com) |
| **Cohere Trial** | Yes | ~1k requests/day on Command-R | Tenet / Bob fallback. | [cohere.com](https://cohere.com) |
| **Fireworks** | Yes (free credits) | $1 free at signup; no ongoing free | Last-resort, when you'd rather burn credits than fail. | [fireworks.ai](https://fireworks.ai) |

## The always-free fallback — local Ollama

The most important entry in every bot's `endpoints` array is the last one:

```json
{ "provider": "ollama-local", "model": "<model>", "host": "http://localhost:11434" }
```

[Ollama](https://ollama.ai) runs Llama, Qwen, Mistral, DeepSeek, and others natively on your Mac. **Free forever, no quota, no key.** It's slower than cloud (5-15s per response on the M3 Air; faster on the M5 Max), but it's what stands between you and a fully-dark council when every cloud provider is throttling at the same time.

To install once:

```bash
brew install ollama
ollama pull llama3.3:70b      # ~40GB download; pick smaller models for the M3 Air
ollama pull qwen2.5:72b
ollama pull deepseek-v3:latest
ollama pull mistral:latest
ollama serve                  # runs at localhost:11434
```

Wrap `ollama serve` in a launchd plist if you want it always-on. The `endpoints` array entries above all assume it's running.

## Strategies that compound the savings

The endpoints array is *one* layer. Three more, in order of how much you save:

1. **Cache identical inputs.** Otto answers `5 + 2` the same way every time. If a prompt-hash + response cache lives in front of the model call, identical prompts skip the API entirely. Cheap and Lock-2-clean (cache file under `~/.council/cache/` with the redaction filter applied).
2. **Smaller models for simple tasks.** Pip and Bob can run on 7-8B models without quality loss for their actual lanes (format transforms, sanity checks). Currently Pip is on `mistral-small`, which is right; Bob is on DeepSeek V3, which may be over-spec for "yeah but in practice" — try a 70B local for a week and compare.
3. **Prompt compression.** Otto's 2026-05-02 outage was a 409KB session file. The session-summarization step in OpenClaw exists; ensure it's running. For other frameworks, a simple "summarize prior 10 turns into 200 words" pass before each new request keeps the prompt below 8K tokens reliably.

## Recommended migration order

If you're wiring all of this for the first time:

1. **Week 1 — local Ollama.** Install and pull the models above. Get one bot (Pip is easiest — small model, narrow lane) working end-to-end on `provider: ollama-local`. Confirm response quality.
2. **Week 2 — secondary providers.** Sign up for Cerebras, Mistral, Google AI Studio. Add their entries as fallbacks in each bot's `endpoints`.
3. **Week 3 — caching layer.** A 50-line `~/.council/lib/llm-cache.py` in front of every endpoint. Hash the prompt + model + temperature; cache the response under `~/.council/cache/<hash>.json`. Skip identical calls.
4. **Week 4 — runtime fail-over.** Until M1 (per-framework loaders) ships, the `endpoints` array is documentation. Building the Layer-1 walker into each framework's HTTP client is the work that actually realizes the failover.

After week 4, you have the resilience.md three-layer stack working end-to-end, on every justice, with $0 ongoing cost (Eve and LOL aside, $3/mo). That's the council's true production posture.

## What this doc does NOT do

- **Doesn't auto-update.** Provider catalogs shift. The `<verify-on-provider>` markers in `policy.example.json` are honest — model IDs change, TPDs change, free tiers tighten. Re-check yearly.
- **Doesn't sign you up.** Each provider link sends you to their UI; account creation is yours.
- **Doesn't store keys.** Per [SECURITY.md](../../SECURITY.md), every API key lives in macOS Keychain; the `key_ref` field in `endpoints` is the keychain item name, not the key itself.
- **Doesn't replace per-framework loaders.** This is the *list*; the loaders are what make a bot actually walk the list at runtime. M1 in [ROADMAP.md](../../ROADMAP.md).
