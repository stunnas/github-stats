# GitHub Stats

![Overview card](https://raw.githubusercontent.com/stunnas/github-stats/master/generated/overview.svg#gh-dark-mode-only)
![Languages card](https://raw.githubusercontent.com/stunnas/github-stats/master/generated/languages.svg#gh-dark-mode-only)
![Overview card](https://raw.githubusercontent.com/stunnas/github-stats/master/generated/overview.svg#gh-light-mode-only)
![Languages card](https://raw.githubusercontent.com/stunnas/github-stats/master/generated/languages.svg#gh-light-mode-only)

My GitHub stats cards, regenerated every day by GitHub Actions. They include my
private repos and repos I've contributed to but don't own, which a GitHub
profile doesn't show in full. The cards follow GitHub's light or dark theme.

This is my copy of [jstrieb/github-stats](https://github.com/jstrieb/github-stats).
See [Credits and License](#credits-and-license).

## How It Works

The "Generate Stats Images" workflow runs daily at 00:05 UTC, on every push to
`master`, and by hand from the [Actions
page](../../actions?query=workflow%3A"Generate+Stats+Images"). It collects
statistics through the GitHub API using the `ACCESS_TOKEN` secret, fills in the
SVGs from `templates/`, and commits the results to `generated/`.

Only cards that changed get a commit. A card that hasn't moved in a while usually
means its numbers didn't change, not that the workflow failed.

| Path | What it holds |
|---|---|
| `.claude/` | Claude Code settings for this repo |
| `.github/` | Workflows and the Dependabot config |
| `generated/` | The generated cards |
| `templates/` | The SVG templates for the cards |
| `tests/` | Tests for the API layer |
| `generate_images.py` | Reads the settings and writes the cards |
| `github_stats.py` | Collects the statistics from the GitHub API |

## Known Limits

**Private repo names can leak.** The token can read private repos, and `aiohttp`
may include the requested URL in an exception. Those errors show up in the
Actions logs, and on a public repo anyone can read them.

**Some numbers are approximate.** View counts and lines changed are probably
somewhat off because of how GitHub's statistics API behaves, and they get more
accurate as GitHub caches statistics for each repo. Repos last contributed to
more than a year ago may be missing. The original project's issues
[#2](https://github.com/jstrieb/github-stats/issues/2),
[#3](https://github.com/jstrieb/github-stats/issues/3) and
[#13](https://github.com/jstrieb/github-stats/issues/13) have more detail.

## Run Your Own Copy

The original project has since been rewritten in Zig, so use
[its repo](https://github.com/jstrieb/github-stats) for the current version. To
run this Python version instead:

1. Fork this repo, then turn on workflows in the fork's Actions tab.
2. Create a classic personal access token with the `repo` and `read:org` scopes.
   A fine-grained token only covers one owner, so it misses repos from an
   organization. The `repo` scope can also write to your repos, so keep the token
   only as an Actions secret.
3. On the [Secrets page](../../settings/secrets/actions), add it as a repository
   secret called `ACCESS_TOKEN`.
4. Optionally, change what the cards count:
   - `EXCLUDED` secret: repos to ignore, in `owner/name` format, separated by
     commas.
   - `EXCLUDED_LANGS` secret: languages to ignore, separated by commas, such as
     `html,tex`.
   - `EXCLUDE_FORKED_REPOS` in [the workflow](.github/workflows/main.yml): set it
     to `true` to drop every repo you don't own, organization repos included.
     Your own forks are left out either way.

   The first two are secrets so they don't reveal private repo names.
5. Run the workflow from the [Actions
   page](../../actions?query=workflow%3A"Generate+Stats+Images"). The cards appear
   in [`generated/`](generated).
6. To show them on your profile, add these lines to your profile README, with
   your GitHub username in place of `username`:
   ```md
   ![](https://raw.githubusercontent.com/username/github-stats/master/generated/overview.svg#gh-dark-mode-only)
   ![](https://raw.githubusercontent.com/username/github-stats/master/generated/overview.svg#gh-light-mode-only)
   ![](https://raw.githubusercontent.com/username/github-stats/master/generated/languages.svg#gh-dark-mode-only)
   ![](https://raw.githubusercontent.com/username/github-stats/master/generated/languages.svg#gh-light-mode-only)
   ```

## What I Changed

- Moved to Python 3.13, set in `.python-version`, after `ubuntu-latest` dropped
  the old Python version and the daily run started failing.
- Pinned every action to a full commit SHA.
- Moved packages to a hashed lockfile, installed as wheels only.
- Added Dependabot for actions and Python packages.
- Added a PR Checks workflow and tests for the API layer.

## Updating Dependencies

`requirements.in` lists the direct dependencies. `requirements.txt` is the
lockfile generated from it, with a hash for every package. Don't edit
`requirements.txt` by hand: both workflows install with `--require-hashes`, so
the install fails if a package doesn't match.

Dependabot is set to check weekly, with one PR for Python updates and separate
PRs for the pinned actions, and a 14-day cooldown on the versions it targets.
Going by its source, it rebuilds `requirements.txt` with `pip-compile`, which
keeps the hashes but drops the header (the command at the top of the file,
including its cutoff date). Security updates are a separate repo setting. They
can arrive at any time and skip the cooldown.

The PR Checks workflow is set to run on every PR, with no secrets, but it isn't
a required check yet. It does the locked install and runs `tests/`, which make
real `aiohttp` and `requests` calls against a local stub, not GitHub. To run them
yourself, use `python3 -m unittest discover -s tests`.

It doesn't check package ages, HTTPS or a real run against GitHub, so also check
these by hand. For Dependabot's Python PRs:

- PR Checks ran and passed.
- Every package in `requirements.txt` still has `--hash=sha256:` lines.
- No package is newer than two weeks, unless it fixes a known advisory in the
  version it replaces. The cooldown doesn't cover a package the update pulls in
  or forces up. To check, on a checkout of the PR's branch, run
  the command below without `--upgrade`, using a date two weeks ago. If a
  version moves back, a package disappears or the command fails, something is
  too new, unless it's the package the advisory fixes. Restore
  `requirements.txt` afterwards.
- After merging, the run's log has no `aiohttp failed` lines and the cards show
  real values. A green job alone doesn't prove the update works. Any error prints
  that line, so compare a lone one with the next run. If the check keeps failing, revert the merge. The
  next good run regenerates the cards.

For Dependabot's Actions PRs:

- PR Checks ran and passed.
- The reference stays a full commit SHA with its version in a comment.
- The release is at least two weeks old, with the same exception for advisories.
- The first run after merging passes.

To update by hand, run this with [`uv`](https://docs.astral.sh/uv/), using a
date two weeks ago:

```sh
uv pip compile requirements.in --generate-hashes --python-version 3.13 \
  --python-platform linux --exclude-newer YYYY-MM-DDT00:00:00Z --upgrade \
  -o requirements.txt
```

`--upgrade` is what moves the versions. Without it, `uv` keeps the ones already
in `requirements.txt`, so leave it out to add a package to `requirements.in`
without updating the rest. A cutoff older than a locked version moves that
version back. The command at the top of `requirements.txt`, when there is one,
only records how that file was generated, and it doesn't update versions.

`--python-version` must match `.python-version`. Both workflows are set to read
that file, and going by its source, Dependabot does too. Regenerate the lockfile
when that changes.

## Credits and License

- Copied from [jstrieb/github-stats](https://github.com/jstrieb/github-stats),
  which came up with the idea and wrote the code and card design here. That
  project was inspired by
  [anuraghazra/github-readme-stats](https://github.com/anuraghazra/github-readme-stats).
- Icons are [GitHub Octicons](https://primer.style/octicons/).
- Licensed under GPL-3.0, the same as the original. See [LICENSE](LICENSE).
