# Releasing

Three artefacts ship from this repository, each to its own registry. All
three need credentials that live with a person, not in CI — so these are
run by hand.

Everything below assumes the working tree is clean, CI is green, and the
version in the manifest is the version you mean to publish.

## 1. `@monapi/client` → npm

```bash
cd clients/node
npm test && npx tsc --noEmit

npm login            # once per machine; 2FA prompt
npm publish --access public
```

`--access public` is required: scoped packages default to private and the
publish fails without it. `prepublishOnly` runs the build, so `dist/`
does not need to be committed.

**Check before publishing** — `npm pack --dry-run` should list exactly
`dist/`, `README.md`, `LICENSE` and `package.json`, and nothing else.

**Check after publishing** — install the published package into an empty
directory and run something against a real engine, rather than trusting
the registry page:

```bash
mkdir /tmp/verify && cd /tmp/verify && npm init -y && npm pkg set type=module
npm install @monapi/client
MONAPI_URL=... MONAPI_API_KEY=... node -e \
  'import("@monapi/client").then(async m => console.log(m.summarize(await m.checkEmail("test@gmail.com"))))'
```

## 2. `monapi-mcp` → PyPI

```bash
cd mcp
python -m pytest
uv build                                  # writes dist/*.whl and *.tar.gz
uv publish                                # needs a PyPI API token
```

The token goes in `UV_PUBLISH_TOKEN` or `~/.pypirc`. Create it at
pypi.org → Account settings → API tokens, scoped to this project once the
project exists (the first upload needs an account-wide token).

**Check after publishing**, again from a clean environment:

```bash
uvx monapi-mcp --help 2>/dev/null || \
  uv run --with monapi-mcp --no-project python -c "import monapi_mcp; print('ok')"
```

## 3. MCP Registry

The registry entry is what makes the server findable from an MCP client.
It reads `mcp/server.json`, which must already point at a **published**
PyPI version — publish step 2 first.

```bash
cd mcp
# one-off: install the publisher CLI (https://github.com/modelcontextprotocol/registry)
mcp-publisher login github          # browser OAuth as the repo owner
mcp-publisher publish
```

The namespace `io.github.dplusf/*` is owned by whoever can authenticate
as that GitHub account, which is why login is interactive.

`server.json` validates against the published schema. Worth re-running
after any edit, because the registry rejects rather than warns:

```bash
python - <<'PY'
import json, urllib.request, jsonschema
spec = json.load(open("server.json"))
jsonschema.validate(spec, json.load(urllib.request.urlopen(spec["$schema"])))
print("ok")
PY
```

Note the field limits that are easy to trip over: `description` is capped
at 100 characters.

## Version bumps

Keep the three versions independent — they are separate artefacts with
separate audiences. What must stay in step:

- `mcp/pyproject.toml` version and the two `version` fields in
  `mcp/server.json` (the server's own, and the one inside `packages`)
- `engine/app/data/signals.yaml` `version` only changes when the shape of
  the catalogue changes, not when a signal is added

## What is not automated, and why

Publishing puts someone's name on an artefact. These commands need a
person's npm account, PyPI token and GitHub identity; wiring them into CI
would mean storing all three in the repository's secrets, which is a
larger decision than it looks. Until then: a clean tree, green CI, and
the checks above.
