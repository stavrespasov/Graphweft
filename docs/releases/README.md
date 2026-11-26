# Build and archive a GraphWeft release

Build from a clean checkout of the intended commit. The package version in `pyproject.toml`, the `version` in `CITATION.cff`, and the release tag without its leading `v` should match.

```sh
python -m pip install build
python -m build
```

The build writes a source distribution and a wheel built from that source distribution. The wheel includes the local workbench. The source distribution also includes the study reports, input preparation scripts, benchmarks, and tests. Verify both artifacts before attaching them to the GitHub release.

1. Extract the source distribution. Install it with `python -m pip install '.[test]'` and run `python -m unittest discover -s tests -v` in the extracted directory.
2. In a fresh virtual environment, install the wheel and change to a directory outside the extracted source. Run `python -m graphweft verify-run` on both saved Bikeshare reports and the household energy report, using their paths in the extracted source. Run the synthetic study script with `--report` and verify the resulting report too.
3. Use the installed wheel to open a verified report in the browser workbench. Attach the wheel, source distribution, and a `SHA256SUMS` file to the draft release. Set the release target to the commit the artifacts came from.

## Archive the GitHub release

For DOI archiving, sign in to Zenodo with GitHub and enable archiving for GraphWeft before publishing the release you want Zenodo to capture. Zenodo reads the repository’s `CITATION.cff` and archives the GitHub release snapshot. Review the Zenodo record’s version, authors, license, and files before using its DOI in project documentation. Use the version-specific DOI when citing a particular experiment snapshot. [Enable a repository](https://help.zenodo.org/docs/github/enable-repository/) · [Describe software](https://help.zenodo.org/docs/github/describe-software/) · [Archive a GitHub release](https://help.zenodo.org/docs/github/archive-software/github-upload/)
