# Data2G maintained fork

This public fork maintains Data2G improvements and reproducible testing, with
focused contributions back to `arodland/Data2G`. Private experimental modem
work belongs in its separate repository.

## Scope and instruction provenance

- This is fork-maintainer guidance for `finitor/Data2G`, for human and agent
  contributors using any vendor. It is not an upstream Data2G policy.
- This root `AGENTS.md` is the canonical, version-controlled guide and belongs
  on the fork's `master` and maintained development branches. Update it through
  normal commits and integration, not ignored local copies or a separate
  guidance-only branch. Identify its source/version in handoffs. Older branches
  must receive the current guide before agent work; report any local changes
  before replacing them. Reconcile upstream guidance deliberately if it appears.
- On 2026-11-21 the maintainer explicitly approved using `master` for fork
  integration and `upstream/master` as the upstream reference. This supersedes
  the upstream-identical-master rule recorded in guide commit `37bf0f0` on
  2026-11-18; explicit maintainer authorization for that older rule was not
  established. The historical `codex/agent-guide` branch is no longer canonical.
- Verify that the chosen tool loads this file, or explicitly supply it as
  context. Vendor-specific instruction files should point here rather than
  duplicate policy. Report conflicting applicable instructions and their
  sources; do not silently present machine preferences as project policy.
- Keep durable rules here, feature decisions and progress in a feature note
  or PR, and machine paths, credentials and tool configuration outside shared
  project policy. Use repository-relative paths in portable documentation.

## Current maintainer-directed validation policy

These temporary restrictions were confirmed by the maintainer on 2026-11-20
and remain in force until explicitly changed. Review them when work resumes;
elapsed time, a new agent, or a quota reset does not lift them.

- On 2026-11-20 the user resumed release-source builds and local tests on
  macOS ARM64 hosts, superseding the 2026-11-18 retraining pause for
  that work. Benchmarks, profiling, training and dependent implementation
  studies remain paused until explicitly requested. A sync or setup request
  alone does not resume paused work. Documentation and read-only checks may
  continue; use appropriate local correctness checks for authorized changes.
- Keep repository GitHub Actions disabled, including manual hosted runs.
  Do not enable, dispatch or rerun hosted workflows without a policy change
  from the user. This applies even though this fork is public.
- Use local macOS ARM64 validation. Other platform
  builds remain suspended until requested. Do not change billing settings.

## Repository boundaries and workflow

- Read `README.md`, `docs/ARCHITECTURE.md` and the relevant protocol/native
  documentation before substantial work. Read this guide explicitly when
  this repository is a secondary workspace folder. Take build and test
  commands from those documents and verify local prerequisites.
- Before editing, inspect the checkout, remotes, branch, base commit and
  working-tree status. Preserve unrelated edits and untracked files. Do not
  reset, clean, force-push or discard another contributor's work to prepare
  a task. Run Git commands in the intended repository.
- Use the fork's `master` as its integration branch; it may contain fork
  changes, including this guide. Track upstream through `upstream/master`.
  Fetch and integrate selected upstream updates deliberately; do not reset or
  force-align the fork's `master` to upstream and discard fork work.
- Default new contributions to the fork's `master`. When the maintainer directs
  work onto an existing incremental branch, use that explicit base and record
  it; do not import unrelated history. Merge focused, reviewed changes into the
  intended fork branch with appropriate local validation. Upstream publication
  remains a separate action requiring explicit user direction.
- Name branches by feature or issue, independently of the coding tool, for
  example `feature/android-rigctld` or `fix/disc-reply-timer`. Continue the
  existing feature branch during sequential handoffs; do not rename existing
  branches merely because the agent or vendor changes. Record the intended
  base and integration target explicitly; do not infer a merge into `master`.
- Use one writer per checkout. For authorized concurrent implementation,
  use separate worktrees and subtask branches with one designated integrator.
  Worktree locations are local choices, not build dependencies. Remember that
  worktrees share repository refs; coordinate branch changes and integration.
- Act within the current explicit user task. Setup or guidance changes do
  not authorize feature implementation; do not inherit an unattended
  implementation loop from another repository. Carry forward the task's scope
  and stop/pause instructions across handoffs. Changing agents does not
  authorize additional work or resume a stopped feature.
- Keep each contribution narrowly scoped and independently reviewable. Do
  not publish issues, comments or PRs to upstream unless the user asks for
  that communication. Private experiments and history stay out of this fork;
  import only deliberately selected, self-contained changes.

## Handoffs and review

- Keep a concise handoff in a portable feature note or draft PR: repository,
  branch, base and current commit; accepted requirements and decisions;
  completed and remaining work; validation commands, results, environment and
  untested platforms; uncommitted changes, blockers and authorization limits.
  Include the instruction source/version and any explicit policy overrides.
  Exclude credentials, private data and unrelated chat transcripts.
- The receiving contributor must verify the handoff against Git and the
  code. Chat history and vendor-specific memory are supplementary context,
  not the only record of project decisions or validation evidence.
- Keep commits reviewable and report validation against the actual final
  revision, distinguishing existing failures from regressions. Review the
  integrated diff and rerun affected checks after integration changes. Apply
  the same acceptance criteria to human and agent contributions; another
  agent's review does not substitute for correctness checks or authorize
  publication, merging or release.

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
