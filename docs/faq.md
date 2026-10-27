# Frequently asked questions

**[About](#about) · [Your data](#your-data) · [Using it](#using-it) · [Changing it](#changing-it) · [Getting help](#getting-help)**

## About

### What is a Post-Incident Review, and what does PIR Assessor add?

A Post-Incident Review (PIR) is the written account of an incident: what happened, how it was
detected, diagnosed and fixed, why it happened, and what will change so it does not happen again.
PIR Assessor checks that account against a definition of what good looks like, turns every gap into
a question for the person who owns the PIR, records the answers with who gave them, and reviews the
result before it goes to the team and to GO.

### Will it write my PIR for me?

No, and that is the point. The agents transcribe what your sources say and ask about everything
else; they never invent a timestamp, a count, a cause or an owner. A PIR an assistant made up would
read well and be wrong. What you get instead is a PIR in which every statement comes from a source or
from a named person.

### What is "the gate"?

The validators: three Python tools that check a PIR packet, an interview ledger and a review against
their schemas and the rules in [method.md](method.md). Each finding has a stable rule id, the template
section it belongs to, and the question that closes it.

### If the gate passes, is my PIR done?

Not necessarily. The gate proves that everything is present, well-formed, consistent and free of
blame and vague-action vocabulary. It cannot tell whether a root cause is true or an action would
actually prevent recurrence; those are judgements for the owner and the reviewer, which is why
`/review-pir` exists.

### Why does it refuse to name people in the PIR, but insist on names for owners?

Because both matter. The PIR is about processes, design and tooling: "the engineer made a mistake"
stops the analysis exactly where it should begin, so blame vocabulary is a blocker. But an action
item nobody agreed to own will not happen, so every owner, answerer and reviewer must be a named
person or team who agreed, never "TBD" or a bare role.

### What is the reference for "what good looks like"?

The deck *What Good Looks Like for Post-Incident Reviews* (Mike Gigante, 2025) and the PIR template
derived from it. The template is used both ways: its sections and appendices define what is expected,
and the finished PIR is rendered back into it.

## Your data

### Does PIR Assessor send my PIR anywhere?

The tools do not: they run locally and make no network call. The assistant does. Whatever the agents
read (your sources, the packet, the interview and the ledger, including names) is sent to the model
behind GitHub Copilot Chat or Antigravity under your terms with that service. Share only what your
organisation allows, and keep real PIRs in a private repository.

### Where are the AI services' terms for my data?

With the service, not here: your organisation's agreement with GitHub for Copilot, or Google's terms
for Antigravity, govern what happens to what the agents send. Whoever administers those services in
your organisation can say which terms apply to you.

### Can someone hide instructions in a source to steer the agent?

The agents are told that what they read is data, never instructions: an instruction inside a chat
export, a gap report, an interview or a ledger is never followed.
The tools also treat every file as untrusted input (cited paths must stay in the workspace, large
files and YAML aliases are refused). No assistant can be guaranteed immune, so review what it
writes.

## Using it

### Do I need VS Code or Antigravity?

No. Every step is a plain Python command-line tool, and you can run them yourself or with any other
assistant ([Usage: running the tools yourself](usage.md#running-the-tools-yourself)). The extensions
add the agents and slash commands that drive those tools for you.

### Which version of Python?

3.12 or later, with PyYAML, jsonschema and python-docx ([Install](install.md#2-python-and-its-packages)).

### Where do my PIRs live?

In your workspace, never in the extension: `pirs/`, `interviews/`, `clarifications/` and `reviews/`
at its root ([Usage](usage.md#set-up-the-workspace)). Upgrading or removing the extension does not
touch them.

### Can one repository hold several PIRs?

Yes. Each PIR has its own stem: its packet is `pirs/<stem>.yaml`, and its interviews, ledgers and
reviews sit under `interviews/<stem>/`, `clarifications/<stem>/` and `reviews/<stem>/`.

### Can several people work on the same PIR?

Yes: the packet, interviews, ledgers and reviews are text files in your repository, so they are
reviewed, merged and versioned like code. Each interview round and each review is its own file,
named by time, so they do not collide.

### What are the review stages?

`readiness` (before it goes to people), `team`, `go` and `exec_go`. The GO review is the one a PIR
passes before it is published. A team review needs the packet in team review or later; a GO review
needs it in GO review or later ([Usage: review](usage.md#3-review)).

### Why does the interview ask about things I already know?

The interview asks what the packet does not yet say. Once the answer is recorded in the ledger and
applied to the packet, the next round no longer asks it.

## Changing it

### Can I change the rules or the template for my organisation?

Yes, in your own copy: it is free software under GPL-3.0-or-later. Clone the repository, change the
catalogs, rules or template, and build your own packages ([Install: building from
source](install.md#building-from-source)). [CONTRIBUTING.md](../CONTRIBUTING.md) explains what a
change must carry so the gate stays honest: a new rule ships with its catalog entry, its interview
question and a fixture that proves it fires.

### Can my organisation share a modified build internally?

GPL-3.0-or-later lets you change the software and use it. Copies made and used inside one
organisation are generally not "conveying" it, while giving a modified build to anyone outside means
passing on its source under the same licence. The
[GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html#InternalDistribution) explains where that line
sits; this is not legal advice, so check with whoever advises your organisation.

### Can I just edit the bundled tools in my install?

Please do not: the agents are told never to edit them, and a change there is lost on the next upgrade
and invisible to everyone else. Change the source and rebuild, or suggest the change upstream.

## Getting help

### Something does not work.

See [Troubleshooting](troubleshooting.md). If it is not there, [open an
issue](https://github.com/gigantem/pir-bar-raiser/issues) with your editor and version, what you ran,
what you expected and the exact message. Never paste a real PIR into an issue; a security problem
goes privately through the repository's Security tab instead ([SECURITY.md](../SECURITY.md)).

### How do I hear about a new release?

On GitHub, **Watch** the repository and choose **Custom › Releases**. Neither extension updates
itself: install the new package the same way ([Install: upgrading](install.md#upgrading)). The
[release notes](release-notes.md) say what changed and whether anything in a workspace must change.

### What if the gate is wrong about my PIR?

Do not edit the tools or the catalogs in your install to make it pass. Open an issue with the rule
id and the shape of the text it fired on, never the confidential PIR itself. In the meantime the
interview can record a waiver with its reason, which keeps the decision visible; the gate still holds
the packet to the rule. In your own copy you can change the rule
([Changing it](#can-i-change-the-rules-or-the-template-for-my-organisation)).

### Has it been tried in VS Code and Antigravity?

Both packages are verified on every build, and their tools run the whole loop end to end from a
fresh workspace. This release has not yet been run in a live VS Code with Copilot Chat or a live
Antigravity session; reports from first users are welcome.

### What licence is it under?

GPL-3.0-or-later. Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>. See
[LICENSE](../LICENSE) and [NOTICE](../NOTICE).
