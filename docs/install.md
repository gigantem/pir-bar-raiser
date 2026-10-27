# Installing PIR Assessor

Download the package for your editor, install Python 3.12 or later, install the extension, then
install the three packages the tools use from the list the extension carries. Each step below has a
part for each system; skip the ones that are not yours.

Both packages are verified on every build, and their tools run end to end from a fresh workspace,
but neither has yet been run in a live VS Code with Copilot Chat or a live Antigravity session. If
something does not work, [open an issue](https://github.com/gigantem/pir-bar-raiser/issues) with
your editor and its version.

- [1. Download](#1-download)
- [2. Python and its packages](#2-python-and-its-packages)
- [3a. VS Code with GitHub Copilot](#3a-vs-code-with-github-copilot)
- [3b. Google Antigravity](#3b-google-antigravity)
- [Upgrading](#upgrading) · [Uninstalling](#uninstalling) · [Building from source](#building-from-source)

## 1. Download

From the [latest release](https://github.com/gigantem/pir-bar-raiser/releases/latest), download:

| Editor | File |
|---|---|
| VS Code with GitHub Copilot | `pir-assessor-<version>.vsix` |
| Antigravity on Windows | `pir-assessor-<version>-antigravity.zip` |
| Antigravity on macOS or Linux | `pir-assessor-<version>-antigravity.tar.gz` |

Each release also lists a `SHA256SUMS` file. To check that what you downloaded is what was released:

```bash
sha256sum -c SHA256SUMS --ignore-missing          # Linux
shasum -a 256 -c SHA256SUMS --ignore-missing      # macOS
```

```powershell
# Windows: prints True when the file matches its line in SHA256SUMS
$file = "pir-assessor-<version>.vsix"
(Get-FileHash $file -Algorithm SHA256).Hash.ToLower() -eq ((Select-String -SimpleMatch $file SHA256SUMS).Line -split '\s+')[0]
```

Every file inside the packages is built reproducibly: the same release builds the same files. The
archives themselves match `SHA256SUMS` byte for byte when they are built with the same compression
library ([Building from source](#building-from-source)).

## 2. Python and its packages

The agents run the bundled tools with `python`, so `python` must be **Python 3.12 or later** in the
terminal your editor uses. Check:

```bash
python --version
```

**Windows.** If `python` says *Python was not found*, Windows is offering its Microsoft Store
placeholder. Install Python, then open a **new** terminal:

```powershell
winget install --id Python.Python.3.12 -e
python --version
```

If it still says *not found*, turn off the two `python` entries under **Settings › Apps › Advanced app
settings › App execution aliases** and open a new terminal.

If `python --version` prints an older version, another Python comes first on your `PATH`. `py -0`
lists the versions installed. Make a virtual environment with 3.12 and use it in the terminal the
agents use:

```powershell
py -3.12 -P -m venv "$env:USERPROFILE\.venvs\pir-assessor"
& "$env:USERPROFILE\.venvs\pir-assessor\Scripts\Activate.ps1"
python --version
```

With the Python extension installed, VS Code can do the activation for you: choose that environment
with **Python: Select Interpreter**, and new terminals activate it.

**macOS.** Install Python 3.12 or later from [python.org](https://www.python.org/downloads/) or with
Homebrew (`brew install python@3.12`). If `python` is not found but `python3` is, use a virtual
environment (below), which provides `python`.

**Linux and WSL.** Most distributions provide `python3`; some still point `python` at Python 2.
The dependable way to get a `python` of the right version is a virtual environment:

```bash
python3 --version                       # 3.12 or later
python3 -P -m venv ~/.venvs/pir-assessor
source ~/.venvs/pir-assessor/bin/activate
echo 'source ~/.venvs/pir-assessor/bin/activate' >> ~/.bashrc    # so every new terminal has it
```

**Then install the packages** (PyYAML, jsonschema, python-docx). The extension carries the list as
`requirements.txt` inside its skill folder, so do this **after** installing the extension (step 3),
with the path for your editor from the table below:

```bash
python -P -m pip install -r "<skill folder>/requirements.txt"
```

Every command in these guides that runs Python with `-c` or `-m` carries `-P`. It stops Python
importing files from the folder you run it in, so a file in a workspace cannot stand in for a
package. Keep it. If Python answers *Unknown option: -P*, it is older than 3.11, below the 3.12 the
tools need.

| Installed in | `<skill folder>` |
|---|---|
| VS Code on macOS and Linux | `~/.vscode/extensions/gigantem.pir-assessor-<version>/skills/pir-assessment` |
| VS Code on Windows (PowerShell) | `$env:USERPROFILE\.vscode\extensions\gigantem.pir-assessor-<version>\skills\pir-assessment` (in cmd, `%USERPROFILE%` instead of `$env:USERPROFILE`) |
| VS Code connected to WSL, SSH or a container | `~/.vscode-server/extensions/gigantem.pir-assessor-<version>/skills/pir-assessment` |
| Antigravity App or IDE | `~/.gemini/config/plugins/pir-assessor/skills/pir-assessment` |
| Antigravity in one workspace | `<workspace>/.agents/plugins/pir-assessor/skills/pir-assessment` |
| Antigravity CLI | `~/.gemini/antigravity-cli/plugins/pir-assessor/skills/pir-assessment` |

Check it worked: `python -P -c "import yaml, jsonschema, docx"` prints nothing. The agents run the same
check before their first command, and stop with this instruction if it fails.

## 3a. VS Code with GitHub Copilot

You need VS Code 1.109 or later with the GitHub Copilot Chat extension, signed in, with agent mode
available.

Install the downloaded file in either of two ways:

- **Extensions view** (`Ctrl+Shift+X`, or `Cmd+Shift+X` on macOS) › `…` menu › **Install from
  VSIX…** › choose `pir-assessor-<version>.vsix`; or
- in a terminal: `code --install-extension pir-assessor-<version>.vsix`

**WSL, SSH and containers.** The extension runs on the workspace side, next to the shell the agents
use. When your VS Code window is connected to WSL, a container or SSH (the remote indicator in the
bottom-left corner says so), install it **in that window**: use **Install from VSIX…** there, or run
the `code --install-extension` command in that window's own terminal. From a plain WSL shell outside
VS Code, `code` may be the Windows launcher and install the extension on the Windows side instead.

Check: `code --list-extensions --show-versions` lists `gigantem.pir-assessor@<version>`, and in
Copilot Chat typing `/` offers `assess-pir`, `interview-pir` and `review-pir`.

## 3b. Google Antigravity

Antigravity installs plugins from folders, not from archives: unpack the package, and you get a
single `pir-assessor/` folder. Remove any older `pir-assessor` folder first, so no stale files
survive.

**App and IDE, for your user** (every workspace you open):

```bash
mkdir -p ~/.gemini/config/plugins
tar -xzf pir-assessor-<version>-antigravity.tar.gz -C ~/.gemini/config/plugins/
```

```powershell
Expand-Archive pir-assessor-<version>-antigravity.zip -DestinationPath "$HOME\.gemini\config\plugins"
```

**One workspace only:** unpack into `<workspace>/.agents/plugins/` instead.

**CLI:** unpack anywhere, then let the CLI install the folder:

```bash
agy plugin install <where you unpacked>/pir-assessor
```

**A team repository:** unpack into `<team repo>/.agents/plugins/` and commit
`.agents/plugins/pir-assessor`. Everyone who opens that repository in the App or the IDE gets the
plugin. It is a pinned copy: replace the folder with a newer release and commit again to update it.
Each colleague installs the Python prerequisites once.

Restart Antigravity after installing. Check: in the App or the CLI, typing `/` offers `assess-pir`,
`interview-pir`, `review-pir` and `pir-assessment`. Antigravity's documentation does not say whether
the IDE shows skills as slash commands; if it does not, ask for the workflow by name ("assess this
PIR").

## Upgrading

- **VS Code:** install the new `.vsix` the same way. If VS Code says the version is already
  installed, add `--force` to the command.
- **Antigravity:** delete the `pir-assessor` folder and unpack the new package in its place (or, for
  the CLI, install the new folder).

Your PIRs, interviews, ledgers and reviews live in your workspace, not in the extension, so
upgrading never touches them. The release notes say whether anything in a workspace needs to change.

## Uninstalling

- **VS Code:** `code --uninstall-extension gigantem.pir-assessor`, or from the Extensions view.
- **Antigravity:** delete the `pir-assessor` folder from the plugins directory, or use the CLI's own
  uninstall for a CLI install.

## Building from source

The packages are built from this repository; you can build them yourself:

```bash
git clone https://github.com/gigantem/pir-bar-raiser.git && cd pir-bar-raiser
git checkout v<version>                     # the release you want
uv venv --python 3.12 .venv                 # with uv (https://docs.astral.sh/uv/), or with plain Python:
uv pip install --python .venv/bin/python --require-hashes -r requirements-dev.lock
#   python3.12 -P -m venv .venv && .venv/bin/python -P -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python tools/build_vsix.py --package          # needs node 22 or later and npm
.venv/bin/python tools/build_antigravity.py --package
```

The packages land in `out/`. Every file inside them is the same as in the release. The archives'
own bytes match the release's `SHA256SUMS` when your Python's compression library matches the one
the release was built with, since another version may compress the same files differently.

From a clone, `.venv/bin/python tools/build_antigravity.py --install` installs the Antigravity
plugin straight into your App and IDE plugins directory (`--workspace <dir>` or `--plugins-dir <dir>`
for another one).
