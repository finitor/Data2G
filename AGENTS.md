# Data2G upstream contribution fork

This public fork hosts reproducible testing and small, reviewable improvements
to `arodland/Data2G`. It is not the home for a separate experimental modem.

## Current user-directed state

- On 2026-11-20 the user resumed release-source builds and local tests on
  this macOS ARM64 host, superseding the 2026-11-18 retraining pause for
  that work. Benchmarks, profiling, training and dependent implementation
  studies remain paused until explicitly requested. A sync or setup request
  alone does not authorize further testing or studies.
- Keep repository GitHub Actions disabled, including manual hosted runs.
  Do not enable, dispatch or rerun hosted workflows without a policy change
  from the user. This applies even though this fork is public.
- Use local macOS ARM64 validation. Other platform
  builds remain suspended until requested. Do not change billing settings.

## Repository boundaries and workflow

- Read `README.md`, `docs/ARCHITECTURE.md` and the relevant protocol/native
  documentation before substantial work. Read this guide explicitly when
  this repository is a secondary folder in a Codex project.
- Keep `master` identical to upstream `master`; synchronize with fast-forward
  updates. Start focused `codex/<topic>` branches from that baseline. Do not
  merge local development or agent-guide commits into `master`.
- Public agent guidance lives on `codex/agent-guide`. The local master
  checkout has an ignored copy of this file so instructions remain available
  without altering the upstream baseline or adding guidance to fix PRs.
  If upstream later adds its own AGENTS.md, reconcile the files deliberately.
- The setup request authorizes fork/configuration/guidance only. Follow later
  user tasks for implementation; do not inherit an unattended experimental
  implementation loop from another repository.
- Keep each contribution narrowly scoped and independently reviewable. Do
  not publish issues, comments or PRs to upstream unless the user asks for
  that communication. Private experiments and history stay out of this fork;
  import only deliberately selected, self-contained changes.

## Engineering and evidence

- Reuse the C++20 core, Python reference, generated tables and existing test
  harnesses. Preserve copyright, licenses, native/reference parity, ordinary
  on-air compatibility and host behavior. Avoid rewrites and new waveforms.
- Reproduce suspected defects on a pinned, unchanged upstream revision before
  labeling them bugs. Check existing reports and acknowledged limitations.
  Distinguish acquisition, control, data decoding and full-session failures.
- Share minimal standalone fixtures and reproduction commands that work on
  upstream without access to another repository. Retain seeds, source/module
  revisions, environment, raw paired outcomes and relevant limitations.
- For authorized work, run correctness checks appropriate to every code
  change. Separate correctness from performance claims; measure processing
  cost when needed for a DSP decision, not automatically for every change.
  Distinguish CPU time, decoder latency and application/channel goodput.
- Preserve false-lock rejection and timing/deadline behavior when expanding
  receiver search. A selected recovered packet is not broad qualification.
- Do not edit generated tables by hand or rewrite them merely to suppress
  platform floating-point differences; follow upstream generation checks.
