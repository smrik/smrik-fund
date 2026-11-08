# Project workflow

The project owner sets the outcome and gives feedback. The orchestrator keeps the
plan and progress clear. Worker agents make and check bounded changes.

## Start and approve work

Use this repository's issues for tasks and its pull requests for review. Existing
boards, labels, milestones, and issue relationships remain authoritative. Read
`docs/agents/issue-tracker.md` for this repository's tracker.

A direct request authorizes work within its stated scope. For a new idea or a
material scope change, the orchestrator proposes the outcome, benefit, smallest
useful change, completion checks, and tradeoffs. Wait for the owner's approval
before implementing that proposal. Resolve routine implementation choices without
repeated approval. While the owner is away, record reasonable assumptions and
continue authorized work; a missing answer does not approve a new proposal.

## Keep progress visible

Each task states its outcome, current status, next action, evidence, and any decision
needed. Use these meanings with the repository's existing labels or board columns:

| Status | Meaning |
| --- | --- |
| Proposed | A new idea is waiting for approval. |
| Ready | Scope is authorized and completion checks are clear. |
| In progress | An agent is doing the work. |
| Needs feedback | A specific decision or review is needed from the owner. |
| Blocked | A named dependency prevents progress. |
| Done | The agreed outcome has evidence; remaining limits are explicit. |

Update the task when its status changes, a blocker appears, or results are ready.
During a live session, give brief updates about useful findings and next steps.
Keep one issue as the source of truth for each outcome. Link existing work rather
than creating duplicate tasks. Task status alone does not start an agent.

## Orchestrator and workers

The orchestrator reads the issue, repository instructions, and relevant evidence.
It keeps decisions and dependencies in the issue, delegates independent work,
reviews the result, and returns a clear summary to the owner.

Give each worker a short handoff: issue link, approved outcome, owned files or
interface, constraints, completion checks, and the evidence it must return. Use
separate branches or worktrees for concurrent edits. Give workers the relevant
context instead of copying an entire conversation. Workers report changed files,
checks, results, and unresolved limits. The orchestrator verifies that report.

Use the host's native subagent facility when available. The profiles in
`.github/agents/` define reusable orchestrator and worker roles for supported
GitHub Copilot clients. Other agents can follow these same roles from this file.
If delegation is unavailable, state that limit and perform explicit planning,
implementation, and review passes. Never describe simulated passes as separate agents.

## Explain results

Use simple technical English inspired by ASD-STE100: short sentences, familiar
words, and one term for each concept. Lead with the outcome and the main logic.
Explain the evidence, practical limits, and next decision. The owner plans software
but does not need a line-by-line code lesson. Offer code detail when it helps a
decision or when requested. This is a communication preference, not a claim of
formal STE100 certification.

Use Answer with HTML when a flow, comparison, or overview is easier to understand
visually. Use its renderer and retain an editable Markdown source. Simple updates
can stay in chat. Share only material appropriate for the repository's visibility.
GitHub file views show HTML source; open a downloaded page locally for the visual.

## Skills and evidence

Use installed skills when they fit the task. Matt Pocock's research, domain
modeling, codebase design, diagnosis, code review, and PR skills support engineering
work. Use TDD when requested or when the task calls for it. Use communication book
frameworks only for relevant conversations; they are not mandatory steps in coding.
Read `docs/agents/domain.md` when exploring project terms or prior design decisions.

Skills installed on one machine are not automatically available in a cloud
checkout. Name an unavailable skill and use the documented workflow; do not claim
that a link installed it. Keep private memory, credentials, and machine paths out
of public issues and commits. Use connected memory tools when available; otherwise
use repository evidence and state the coverage gap. Never claim cross-system
memory synchronization without a receipt from each system.

## Finish and hand back

Preserve existing user edits. Make the smallest change that meets all acceptance
criteria. Run checks appropriate to the change and record the result. Link the PR
to its task. Report what changed, why it helps, what was checked, and what remains.
Keep unverified acceptance criteria open. Treat merge, deployment, destructive
cleanup, and visibility changes as separate actions with their own authorization.

## How to start a session

Open an agent session in this repository and ask: "Act as orchestrator. Read the
project workflow and issue N. Propose the next useful step, then delegate the
approved work and report the result." A direct implementation request can start
at the approved-work step. In a supported Copilot client, select the orchestrator
profile. Availability depends on the client's setup and account access.

These files configure behavior when a session runs. They do not install an
always-running agent or a paid service. GitHub profiles and templates in a PR
become the default repository setup after that PR is merged.

References: [GitHub issues](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-an-issue),
[custom agents](https://docs.github.com/en/copilot/concepts/customizations/custom-agents),
[Matt Pocock skills](https://github.com/mattpocock/skills),
[Answer with HTML](https://github.com/QingYunA/answer-me-with-html).
