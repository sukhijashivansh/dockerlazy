# docker lazy

See a container’s networks, mounts, published ports, and resource usage in one terminal table.

Requires Docker CLI and Python 3.7+. On macOS, install with Homebrew:

```sh
brew install --cask sukhijashivansh/tap/docker-lazy
docker lazy c1
```

Use any container name or ID in place of `c1`. Add `--fast` to skip live stats or `--json` for JSON output.

Compare the settings of two containers and show only what differs:

```sh
docker lazy diff c1 c2
```

On Linux, or to install from source, run `make install` from this folder. If you switch to Homebrew later, delete `~/.docker/cli-plugins/docker-lazy` first.

Run `make test` to test or `make release` to build an archive in `dist/`.