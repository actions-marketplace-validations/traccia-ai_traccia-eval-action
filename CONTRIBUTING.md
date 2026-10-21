# Contributing

Thanks for helping improve the Traccia Eval Action. Bug reports, documentation fixes, and pull requests are welcome.

## Scope

This action is deliberately thin. The pass/fail decision belongs to the Traccia CLI (`traccia eval` in [traccia-py](https://github.com/traccia-ai/traccia-py), `traccia-ts eval` in [traccia-node](https://github.com/traccia-ai/traccia-node)). Changes to gates, thresholds, or exit codes belong in those repositories. This repository handles running the command, checking the summary, the pull request comment, the job summary, and step outputs.

## Development

You need Python 3.10 or later and bash. There are no dependencies to install.

```bash
python3 -m unittest discover -s tests -v
```

- `tests/test_summary.py` covers summary checks and comment rendering.
- `tests/test_comment.py` covers creating and updating comments against `tests/fake_github.py`.
- `tests/test_run.py` runs `run.sh` end to end with fake eval commands.
- `tests/fixtures/` holds summaries in the shape the CLI writes.

CI also runs `shellcheck run.sh` and `actionlint`. Run them locally if you have them installed.

## Rules for changes

- **Never change the eval result after the fact.** The step exits with the CLI's exit code, or `5` when the summary cannot be trusted. Comment or API failures must never change it.
- **Keep the runtime dependency-free.** Only bash and the Python 3.8+ standard library. Users run this on their own runners.
- **Pass inputs through `env:`.** Never interpolate `${{ inputs.* }}` or event fields into shell code.
- **Escape anything from the summary** before it goes into Markdown.
- **Add a test** for every behaviour change, and a fixture when the summary shape changes.
- **Update `CHANGELOG.md`** under `[Unreleased]`, and the README when an input or output changes.

## Releasing

1. Move the `[Unreleased]` entries in `CHANGELOG.md` under a new version and date.
2. Push the commit and check that the Test workflow passes.
3. Tag the release commit `vX.Y.Z` and publish a GitHub release from it.
4. Move the major tag: `git tag -f v1 vX.Y.Z && git push -f origin v1`.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
