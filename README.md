# docker lazy

See a container’s networks, mounts, published ports, and resource usage in one terminal table.

Requires Docker CLI, Python 3.7+, and Make on macOS or Linux. From this folder, run:

```sh
make install
docker lazy c1
```

Use any container name or ID in place of `c1`. Add `--fast` to skip live stats or `--json` for JSON output.

Run `make test` to test or `make release` to build an archive in `dist/`.