# Changelog

## [Unreleased]

### Config: model and pipeline constants (`generator/config.py`)
- **Generator model**: Switched from Haiku to **Sonnet** (`claude-sonnet-4-5-20241022`) for higher-quality task generation.
- **Evaluation model**: Added **Opus** (`claude-opus-4-0-20250115`) as the target agent model. Tasks are calibrated so Opus passes 1-3 out of 5 runs.
- **Pre-filter model**: Kept **Haiku** as a cheap pre-filter to screen out trivially easy tasks before expensive Opus evaluation.
- Added pipeline constants: learnable range (1-3/5), eval trials (5), task categories for diversity.
- **Design decision**: Three-model architecture (Sonnet generates, Haiku filters, Opus evaluates) balances quality and cost. Haiku pre-filter saves ~$2-10 per batch by catching easy tasks before running 5 Opus trials.
