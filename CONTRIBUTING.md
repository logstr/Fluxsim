# Contributing to FluxSim

Thanks for your interest in improving FluxSim! This guide explains how to set up your environment,
style your code, and submit changes that maintainers can review quickly.

## Ways to contribute

- Report bugs or propose enhancements via [GitHub Issues](https://github.com/fastfluxlab/multi-flux-sim/issues).
- Improve documentation, tutorials, and examples.
- Add tests, new network topologies, or observability improvements.
- Join discussions about research/teaching use cases once community channels are enabled.

## Development setup

FluxSim requires Python 3.10 or newer.

```bash
git clone https://github.com/fastfluxlab/multi-flux-sim.git
cd multi-flux-sim
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pre-commit install
```

Install Docker Desktop (or an equivalent) so you can start the simulator stack locally. See the
[README](README.md) for CLI usage patterns.

## Quality checks

Always keep the automated checks green:

```bash
ruff check .
ruff format --check .
black --check .
mypy fluxsim
pytest --cov=fluxsim --cov-report=term
```

Running `pre-commit run --all-files` before pushing catches the most common issues automatically.

## Branches & pull requests

1. Create a feature branch from `main`.
2. Make focused commits with clear messages (e.g., `feat`, `fix`, `docs`). Rebase onto `main` if your branch drifts.
3. Include tests and documentation updates that explain the behaviour change.
4. Open a pull request:
   - Describe the problem and solution.
   - Link related issues (e.g., `Fixes #123`).
   - Confirm local checks passed.
5. Engage with review comments quickly; maintainers may push small follow-up commits during review.

## Code of Conduct

FluxSim follows the Contributor Covenant (v2.1 recommended). Respectful communication is required—review the
future `CODE_OF_CONDUCT.md` (once published) and use the listed contact method for any conduct-related concerns.

## Releases

Maintainers:

- Keep `main` releasable.
- Use GitHub Releases to tag versions, summarising highlights and sponsor acknowledgements.
- Regenerate documentation, Docker images, and demo recordings as needed.

Thank you for helping us build a rich playground for DNS fast-flux research and education!
