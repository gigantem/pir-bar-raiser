# Troubleshooting

Find the symptom, then the fix. If yours is not here, see the [FAQ](faq.md) or
[open an issue](https://github.com/gigantem/pir-bar-raiser/issues) with what you ran, what you
expected, and the exact message.

- [Python](#python)
- [VS Code](#vs-code)
- [Antigravity](#antigravity)
- [What the tools tell you](#what-the-tools-tell-you)
- [The rendered document](#the-rendered-document)

## Python

**The agent stops with "run `python -m pip install -r …/requirements.txt`".**
The prerequisite check (`python -c "import yaml, jsonschema, docx"`) failed in the agent's terminal.
Run the command it gives you, in the same environment the agent uses (see
[Install, step 2](install.md#2-python-and-its-packages)). The agents stop here on purpose rather than
working around it.

**`python` says "Python was not found" (Windows).**
That is Windows' Microsoft Store placeholder. Install Python 3.12 or later
(`winget install --id Python.Python.3.12 -e`) and open a new terminal. If it persists, turn off the
`python` entries under **Settings › Apps › Advanced app settings › App execution aliases**.

**`python --version` prints Python 2.7, or something below 3.12 (Linux, macOS, WSL).**
Your system's `python` is an older interpreter. Create a virtual environment with a newer one and
activate it in every terminal (the [Install](install.md#2-python-and-its-packages) guide shows how);
inside it, `python` is the right version. The tools themselves stop with "requires Python 3.12 or
later" when run by an older one.

**`python3 -m venv` fails with "ensurepip is not available" (Debian, Ubuntu).**
Install the venv module for your Python first, for example `sudo apt install python3-venv` (or
`python3.12-venv`), then create the environment again.

**`pip install` fails, or says "externally-managed-environment".**
Your system Python does not let pip install into it. Use a virtual environment as above and run the
install inside it.

**It worked in one terminal but not in the editor.**
The editor's terminal may start a different shell or not activate your environment. Open a new
terminal in the editor and run `python --version` and `python -c "import yaml, jsonschema, docx"`
there; add the activation line to your shell's startup file if needed.

## VS Code

**`/assess-pir` does not appear in Copilot Chat.**

- Check the extension is installed: `code --list-extensions --show-versions` lists
  `gigantem.pir-assessor`.
- Check VS Code is 1.109 or later (**Help › About**) and GitHub Copilot Chat is installed and signed
  in, with agent mode available.
- Reload the window (**Developer: Reload Window**) after installing.
- **Connected to WSL, SSH or a container?** The extension must be installed on that side. Install it
  from the connected window itself ([Install, 3a](install.md#3a-vs-code-with-github-copilot)).

**The agent asks where the skill folder is, or says it cannot find a tool.**
Give it the folder that holds `SKILL.md`; [Install](install.md#2-python-and-its-packages) lists the
path for each setup. In a POSIX shell,
`ls -d ~/.vscode*/extensions/gigantem.pir-assessor-*/skills/pir-assessment` prints it.

**VS Code says the version is already installed.**
Reinstall with `code --install-extension pir-assessor-<version>.vsix --force`.

**Two copies of the agents appear.**
An older copy of the extension, installed under a different name, is still present. Remove the one
you do not want from the Extensions view.

## Antigravity

**The plugin does not load.**

- The folder must be `…/plugins/pir-assessor/`, with `plugin.json` directly inside it. Unpacking the
  archive *into* an existing `pir-assessor` folder gives `pir-assessor/pir-assessor/`, which does not
  load: delete the folder and unpack into the plugins directory itself.
- Restart Antigravity after installing or replacing the plugin.
- For the CLI, install the unpacked folder with `agy plugin install`; the CLI does not read the App's
  plugins directory.

**No `/assess-pir` slash command.**
Antigravity documents skills as slash commands in the App and the CLI; its documentation does not say
whether the IDE offers them. Ask for the workflow by name instead: "assess this PIR", "interview the
owner for pirs/<stem>.yaml, round 1", "review pirs/<stem>.yaml at the go stage".

**Old files are still there after an upgrade.**
Unpacking over an old folder keeps files the new release removed. Delete the `pir-assessor` folder
first, then unpack.

## What the tools tell you

**A validator "fails" with a list of findings (exit 1).**
That is the result, not a broken tool: the findings are the gaps. Exit 2 is different: the tool could
not run (a wrong argument, an unreadable file). See
[Usage: what the results mean](usage.md#what-the-results-mean).

**"REFUSING TO WRITE … reviews/ holds attestations a reviewer signed".**
The review scaffold is not a review, so the tool will not write it anywhere a review could be
mistaken for one: inside a directory called `reviews`, through a symbolic link, or under a review's
file name. Write it elsewhere (for example `<stem>.scaffold.json` at the workspace root) and let the
reviewer write the review.

**`REVIEW-PASS-UNVERIFIED`: "the packet has changed since it was reviewed".**
A passing review records the exact packet it reviewed. The packet has changed since, so the pass no
longer counts. Review the packet as it is now (`/review-pir` again).

**`REVIEW-STAGE-AHEAD`.**
The review claims a stage the PIR has not reached, such as a `go` review of a packet still in
`draft`. Move the packet's `status` on when it really is in that review, or review at an earlier
stage.

**`LEDGER-…` findings about questions or pointers.**
The ledger is held to the interview it came from (same questions, word for word) and to the packet
(every `applied_to` pointer must name something that exists). If you edited the packet by hand and
removed a value an answer had put there, the ledger reports it.

**`check_artifact_conventions.py` says SKIP.**
Nothing is filed under `interviews/`, `clarifications/` or `reviews/` yet. A skip is not a pass; it
means there was nothing to check.

**"… leaves the repository root, so it is not opened", "an artifact may be at most 1048576 bytes",
or "YAML aliases … are not accepted".**
The tools read every artifact as someone else's input: a cited path must stay inside the workspace
(run the tools from its root), a file over 1 MiB is refused unread, and YAML aliases (`*name`) are
refused. Keep cited files inside the workspace, or mark evidence that lives elsewhere as `external:`.

## The rendered document

**The table of contents is empty.**
Word fills it on request: right-click it and choose **Update Field**, or press F9.

**Sections say "not yet provided".**
The packet has no content for them yet. The renderer never fills a gap; close it through the
interview and render again.

**The graphs are missing.**
Figures render as captions with their source; the graphs themselves live where the packet says, and
are pasted in by the PIR owner.
