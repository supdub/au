# au

<p align="center">
  <strong>A tiny usage dashboard for Codex, Claude Code, and Cursor Agent.</strong>
</p>

<p align="center">
  <a href="https://github.com/supdub/agent-usage-cli/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-0f172a.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-2563eb.svg">
  <img alt="CLI" src="https://img.shields.io/badge/interface-CLI-16a34a.svg">
  <img alt="Watch mode" src="https://img.shields.io/badge/watch-1s%20refresh-f59e0b.svg">
</p>

`au` inspects local auth state and local usage signals for:

- Codex
- Claude Code
- Cursor Agent

It is designed for two very different jobs:

- JSON-first automation for agent harnesses and scripts
- a colorful live dashboard for humans who want a fast read on plan state

## Why it exists

Most agent CLIs are good at doing work and bad at answering simple questions like:

- Am I logged in?
- Am I in plan mode or API mode?
- Which environment variable is overriding normal usage expectations?
- How much of the current window is left?
- What does "usage" even mean for this account?

`au` answers those questions from the machine you are already on.

## Highlights

- Compact JSON by default.
- `--watch` dashboard with in-place refresh in the terminal alternate screen.
- Helpful login guidance when a provider is not authenticated.
- Real local Codex token/window parsing.
- Real local Claude session parsing.
- Real local Cursor billing interpretation.
- Packaging scaffolding for zipapp, curl install, Homebrew, and `.deb`.

## Quick Start

### Install with curl

```bash
curl -fsSL https://raw.githubusercontent.com/supdub/agent-usage-cli/main/install.sh | bash
au -w
```

### Local development install

```bash
./install.sh --from-local
au
```

### Python install

```bash
pip install .
au -p
```

## What it shows

### Codex

- Detects ChatGPT/Codex login from `~/.codex/auth.json`
- Tells the user to run `codex login` if login is missing
- Marks plan-style usage when login exists
- Flags `OPENAI_API_KEY` when present
- Reads local token totals and plan windows from `~/.codex/sessions/**/*.jsonl`

### Claude Code

- Detects Claude login from `~/.claude/.credentials.json` and `claude auth status`
- Tells the user to run `claude auth login` if login is missing
- Switches to `mode=api` when `ANTHROPIC_API_KEY` is active
- Aggregates latest local session usage from `~/.claude/projects/**/*.jsonl`
- In watch mode, probes Claude's `/insights` stream to surface live rate-limit window state when the installed CLI exposes it

### Cursor Agent

- Detects login from local Cursor Agent auth/config plus `cursor-agent status/about`
- Tells the user to run `cursor-agent login` if login is missing
- Distinguishes `usage_based`, `team`, `individual_plan`, and `unknown`
- Explains what "usage" means only after billing context is known
- Reports live local pricing metadata without inventing usage totals

## Usage

```bash
au
au codex
au claude
au cursor
au -p
au -v
au -w
au -w -i 2
```

### Flags

| Flag | Meaning |
| --- | --- |
| `-w`, `--watch` | Live dashboard mode |
| `-i`, `--interval` | Watch refresh interval in seconds, default `1` |
| `-p`, `--pretty` | Pretty-print JSON |
| `-v`, `--verbose` | Include detector evidence and raw signals |
| `-V`, `--version` | Print version |

## Output modes

### Default mode: compact JSON

Default output is intentionally compact and token-efficient.

```bash
au claude | jq '.providers[0].usage.metrics.total_tokens'
```

Example shape:

```json
{
  "generated_at": "2026-03-27T19:06:24Z",
  "tool_version": "0.1.0",
  "providers": [
    {
      "id": "codex",
      "auth": "logged_in",
      "mode": "plan"
    }
  ]
}
```

### Watch mode: live terminal dashboard

`au --watch` is optimized for terminal use:

- refreshes in place
- uses the terminal alternate screen
- hides and restores the cursor correctly
- keeps a true 1s steady-state refresh cadence
- caches slower providers so the dashboard remains responsive
- renders bars when the provider exposes trustworthy percentage data

## Example

```text
au  watch  refresh 1s  3/3 ready
Updated 2026-03-27 12:33:06 PDT

========================================================================================
Codex  logged_in  mode=plan
Plan        pro
5h left     [#####################---]   88.0% left  reset 15:00
7d left     [####################----]   83.0% left  reset Apr 02 19:00
Last turn   33.0k tokens
Uncached    6.8% of last-turn input
```

## Install and distribution

### Zipapp artifact

Build a single-file executable:

```bash
make dist
./dist/au
```

Builder:

- `scripts/build_zipapp.py`

### Curl installer

The installer downloads the release artifact named `au` and installs:

- `~/.local/bin/au`
- `~/.local/bin/agent-usage` as a compatibility symlink

Supported environment variables:

- `AU_REPO`
- `AU_VERSION`
- `AGENT_USAGE_VERSION`
- `AU_BIN_DIR`

### Homebrew

Formula scaffold:

- `packaging/homebrew/agent-usage.rb`

### Debian / apt-style packages

Build a `.deb`:

```bash
./packaging/debian/build-deb.sh 0.1.0 all
```

## Development

### Run

```bash
make run
```

### Test

```bash
make test
```

## Project layout

```text
agent_usage_cli/          Python package
au                        local wrapper entrypoint
install.sh                curl-bash installer
scripts/build_zipapp.py   single-file release build
packaging/homebrew/       Homebrew scaffold
packaging/debian/         Debian package builder
tests/                    unit tests
```

## Data sources

### Codex

- `~/.codex/auth.json`
- `~/.codex/config.toml`
- `~/.codex/sessions/**/*.jsonl`

### Claude Code

- `~/.claude/.credentials.json`
- `~/.claude/settings.json`
- `~/.claude/projects/**/*.jsonl`
- `claude auth status`
- `claude -p '/insights' --output-format stream-json --verbose` in watch mode

### Cursor Agent

- `~/.config/cursor/auth.json`
- `~/.cursor/cli-config.json`
- `~/.cursor/statsig-cache.json`
- `cursor-agent status`
- `cursor-agent about`

## Known limits

- `au` is intentionally local-first. It does not pretend to know server-side totals that the installed CLI does not expose.
- Codex currently exposes the plan windows available in local `rate_limits`, but this implementation does not separate Spark vs non-Spark buckets.
- Claude Code currently exposes a live five-hour window reset/state signal on this machine, but not percentage-left fields. `au` will render percentages if the installed Claude CLI starts emitting them.
- Cursor Agent billing meaning is available locally, but current account usage totals are not exposed by the installed CLI/config on this machine.
- If `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `CURSOR_API_KEY` is active, API behavior can diverge from plan-style expectations.

## Roadmap

- Improve Codex bucket breakdown if the local client exposes Spark/non-Spark windows
- Expand Claude window support beyond the current live reset-state probe
- Add release automation for tagged GitHub releases
- Publish a real Homebrew tap and apt repository metadata

## License

MIT
