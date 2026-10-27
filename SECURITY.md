<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com> -->
# Security

## Reporting a vulnerability

Report it privately: on this repository's **Security** tab, choose **Report a vulnerability**. Please
do not open a public issue for it.

Useful to include: the release (the version in the package name), what you did, what happened, and
what an attacker could gain. A small made-up example is better than a real one.

## Never paste a real PIR

A Post-Incident Review can be confidential, and it names the people who own it and answered for it.
Do not put a real PIR, a real packet, interview or ledger, or a real incident's sources into an
issue, a report or a pull request. Describe the shape of the problem instead, or reproduce it on the
fictional worked example under `examples/`.

## What is in scope

The tools under `tools/`, the agents, prompts and skill under `assistant/`, and the two packages
built from them. The AI services the extensions drive (GitHub Copilot, Google Antigravity) have their
own security processes.
