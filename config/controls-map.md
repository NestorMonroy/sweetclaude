# Controls Map

Version: 1.0
Date: 2026-06-20
Status: canonical — release control plane (MS-007)

This is the canonical, shipped controls map for SweetClaude. It is the source
of truth the release gate's control-lint validates against: every `CTL-NNN`
referenced in a release-linted artifact must be defined here, and the map
itself must be free of implementation-significant numeric ranges. Originally
developed under the MS-007 Failure Mode Controls effort and promoted here as
the canonical control-plane artifact.

## Purpose

This design converts the discovery catalog into the first MS-007 control map.
It defines which controls are promoted into the 4.x hardening path, where they
run, what they block, what evidence they require, and which candidates are
deferred.

The goal is narrow: keep beta 4.x feature-thawed without letting known
high-severity failure modes produce false status, unsafe mutation, unsupported
maintenance advice, or unsafe release/update behavior.

## Design Position

SweetClaude should implement these controls as part of the MS-007
orchestrator/control plane, not as more prompt instructions.

The deterministic layer owns:

- state transitions
- context binding
- evidence receipt validation
- manifest/capability resolution
- release and mutation blocking
- installed-entrypoint smoke checks
- backlog routing checks

LLM workers and reviewers may produce artifacts and judgment receipts, but they
do not become the source of truth for gate passage when a machine check is
available.

Control-index consistency is itself a design requirement: no controls map,
implementation plan, release gate, or test strategy may reference an undefined
`CTL-*` ID. References must use explicit IDs, not numeric ranges, in any place
where implementation or gate behavior depends on them.

## Control Layers

| Layer | Responsibility | Primary Failure Modes |
|---|---|---|
| L1 evidence and context substrate | Bind receipts to current repo/install/release context and reject stale evidence. | FM-009, FM-011, FM-012, FM-043, FM-047, FM-048 |
| L2 mutation lifecycle | Block unsafe update/migrate/recover/repair writes unless plan, approval, snapshot, restore, and postconditions are proven. | FM-021, FM-023, FM-024, FM-039 through FM-044, FM-048 |
| L3 manifest-aware maintenance | Prevent doctor/update/migrate/recover from guessing by version string or path shape. | FM-019, FM-020, FM-022, FM-045, FM-046 |
| L4 source/spec anti-drift | Require governing-source discovery, precedence, and executable contract/invariant checks for high-risk design and implementation. | FM-001, FM-002, FM-003, FM-004, FM-005, FM-034, FM-035, FM-050 |
| L5 status/release closure | Prevent false completion, false rollup, unsupported docs, wrong branch/channel, and public distribution trust failures. | FM-006 through FM-010, FM-013, FM-014, FM-025, FM-026, FM-031, FM-032, FM-037, FM-049, FM-051 |
| L5a release identity | Bind branch, tag, channel, package/plugin metadata, changelog, update discovery, and published artifact identity. | FM-011, FM-012, FM-013, FM-014, FM-047 |
| L6 optional observability | Detect provider/model degradation as context, not as a substitute for deterministic gates. | FM-029, FM-033, FM-038 |

## Promoted Controls

### L1 Evidence And Context Substrate

| Control ID | Source Candidates | Runs In | Blocks | Required Receipt | Acceptance Criteria |
|---|---|---|---|---|---|
| CTL-001 Evidence receipt schema | CC-005, CC-006 | Orchestrator, status, release, mutation commands | phase_transition, status, release, mutation | `evidence_receipt` | Receipt includes id, generated_at, cwd, repo root, branch, commit, command, relevant paths, result, and evidence files. |
| CTL-002 Evidence freshness validator | CC-006 | Orchestrator gate runner | phase_transition, status, release, mutation | `freshness_check` | Receipt fails if cwd, branch, commit, file hash, manifest, or install identity changed since evidence was captured. |
| CTL-003 Gate context binding | CC-007, CC-031 | Gate runner | release, mutation | `context_binding` | Gate result is valid only for the exact repo, branch, commit, tag, install path, package/plugin version, manifest version, and channel captured. |
| CTL-004 Source-of-truth declaration | CC-031 | Effort/workflow intake; release/status | phase_transition, status, release | `source_of_truth_receipt` | Workflow declares authoritative source for product status, runtime state, release identity, code, and evidence before closure. |

Design notes:

- This layer must be implemented first. Later controls rely on the same receipt
  identity, freshness, and context rules.
- Receipt files should be machine-readable YAML or JSON. Human-readable
  summaries may be generated from them, but summaries are not proof.

### Common Receipt Envelope

Every blocking receipt should share this minimum envelope before adding
command-specific fields:

```yaml
receipt_id: string
receipt_type: evidence|context_binding|mutation_plan|approval|snapshot|restore_proof|postcondition|capability_resolution|release_identity|finding_disposition|backlog_promotion|judgment
schema_version: integer
generated_at: iso8601
command_or_workflow_step: string
cwd: string
repo_root: string
branch: string
commit: string
install_path: string|null
package_version: string|null
plugin_version: string|null
manifest_id: string|null
manifest_version: string|null
input_artifacts:
  - path: string
    sha256: string|null
output_artifacts:
  - path: string
    sha256: string|null
result: pass|warn|fail|blocked|judgment_pass
blocking_surfaces:
  - phase_transition|mutation|status|release|public_distribution
unresolved_findings:
  - id: string
    severity: critical|high|medium|low
freshness:
  expires_at: iso8601|null
  invalidated_by:
    - cwd_change|branch_change|commit_change|manifest_change|file_hash_change|install_change|write_set_change
```

Command-specific receipts may extend the envelope. They may not replace or
rename common identity, result, context, or freshness fields.

### L2 Mutation Lifecycle

| Control ID | Source Candidates | Runs In | Blocks | Required Receipt | Acceptance Criteria |
|---|---|---|---|---|---|
| CTL-010 Mutation plan gate | CC-011 | `update`, `migrate`, `recover`, future repair flows | mutation | `mutation_plan` | Plan names operation, project shape, target files/state, external data boundaries, risk class, postconditions, and rollback route before writes. |
| CTL-011 Write-set and blast-radius monitor | CC-009, CC-011 | Mutation runner | mutation, status | `write_set_receipt` | Actual changed files are within declared write set; out-of-scope writes block completion or require renewed approval. |
| CTL-012 Approval scope validator | CC-010 | Mutation approval gate | mutation | `approval_receipt` | Approval is bound to plan hash, write-set hash, snapshot hash, current context, and expiration. |
| CTL-013 Snapshot scope validator | CC-012 | Mutation safety library | mutation | `snapshot_receipt` | Snapshot covers declared blast radius or explicitly fails closed with a recoverability warning. |
| CTL-014 Restore proof gate | CC-013, CC-032 | `recover`, `migrate`, `update` | mutation, release | `restore_proof_receipt` | Restore command is known and validated by dry run or round-trip fixture before risky mutation. |
| CTL-015 Postcondition validator | CC-014 | Command-specific verifier | mutation, status | `postcondition_receipt` | Operation success requires objective checks of final state, not exit code or agent prose alone. |
| CTL-016 Repair loop budget | CC-015 | Repair/recover orchestrator | mutation, status | `repair_attempt_receipt` | Repeated failed attempts, unchanged postconditions, or new regressions stop the loop and route to backlog/escalation. |

Design notes:

- `doctor` remains read-only by default. A future doctor-fix mode must use this
  lifecycle before writing.
- A checkpoint, backup path, or version history entry cannot satisfy rollback
  requirements unless CTL-013 and CTL-014 pass.
- "Proceed" only approves the current bound plan. Any context or write-set
  change requires renewed approval.

### L3 Manifest-Aware Maintenance

| Control ID | Source Candidates | Runs In | Blocks | Required Receipt | Acceptance Criteria |
|---|---|---|---|---|---|
| CTL-020 Capability manifest resolver | CC-016 | `doctor`, `update`, `migrate`, `recover`, `status`, `release` | mutation, release | `capability_resolution` | Command resolves operation from manifest capability id, project shape, schema version, and supported entrypoint, not version string alone. |
| CTL-021 Manifest/schema validator | CC-016 | Maintenance preflight | mutation, release | `manifest_validation` | Missing, stale, invalid, or incompatible manifest fails closed for mutation and release-impacting recommendations. |
| CTL-022 Capability support receipt | CC-017 | `doctor`, `status`, docs/release checks | status, release | `capability_support_receipt` | User-facing claim names the installed entrypoint, supporting script/module, project shapes, and support status. |
| CTL-023 Installed-entrypoint smoke gate | CC-018 | Release gate | release | `installed_smoke_receipt` | Direct script tests and installed slash/plugin invocation both pass for claimed maintenance capabilities. |

Design notes:

- This is the answer to the version-chasing concern: commands should resolve
  supported behavior from capability data and project shape, not from hardcoded
  per-release skills.
- The manifest resolver must be conservative. Unknown shape means diagnose and
  report, not mutate.
- Version may be manifest metadata, but it cannot be the primary dispatch key
  for mutating recommendations. Capability, project shape, schema compatibility,
  and preconditions drive behavior.

Minimum capability manifest shape:

```yaml
manifest_schema_version: integer
manifest_id: string
project_shape:
  id: string
  detected_by:
    - path_or_probe: string
capabilities:
  - id: string
    title: string
    supported_project_shapes:
      - string
    command_entrypoint:
      slash_command: string|null
      script: string|null
      module: string|null
    mutation_class: read_only|planned_write|destructive|release
    required_preconditions:
      - string
    snapshot_scope_hints:
      - path_or_state: string
    postconditions:
      - id: string
        check: string
    rollback_support:
      supported: boolean
      command: string|null
      limitations:
        - string
    unsupported_states:
      - condition: string
        behavior: diagnose_only|block|escalate
    version_metadata:
      introduced_in: string|null
      deprecated_in: string|null
```

### L4 Source And Spec Anti-Drift

| Control ID | Source Candidates | Runs In | Blocks | Required Receipt | Acceptance Criteria |
|---|---|---|---|---|---|
| CTL-030 Source discovery validator | CC-001 | Pre-design, pre-implementation, high-stakes review | phase_transition, mutation | `source_discovery_receipt` | Receipt names searched locations, governing sources found, likely sources excluded, and confidence/help-needed fields. |
| CTL-031 Source precedence gate | CC-002 | Design/review gate | mutation | `source_precedence_receipt` | Design/implementation cannot treat drifted implementation or shallow docs as canonical over ADRs/contracts/specs. |
| CTL-032 Spec gap disclosure | CC-003 | Design gate | phase_transition | `spec_gap_receipt` | Ambiguous or missing authority is labeled and routed to design decision before implementation. |
| CTL-033 Contract conformance test requirement | CC-019 | Test/release gate | release; mutation for contracts | `contract_test_receipt` | Contract-backed behavior has executable conformance checks that run in the relevant gate, or a named High/Critical exemption accepted by an authorized human. |
| CTL-034 Load-bearing invariant requirement | CC-020, CC-021 | Test strategy; release gate | release | `invariant_test_receipt` | High/Critical fix identifies the negative/bypass property that would catch the historical failure and provides executable test evidence, or a named exemption accepted by an authorized human. |
| CTL-035 Test patch freeze | CC-022 | Test/review gate | mutation, release | `test_change_receipt` | Test behavior changes for high-risk areas cite governing source and cannot silently ratify unsafe behavior. |

Design notes:

- Human source review is still useful, but it is not enough for load-bearing
  correctness.
- Contract and invariant tests are the structural defense against "read the spec
  and still implemented the wrong thing."
- `contract_test_receipt` and `invariant_test_receipt` must include test file
  path, test command, expected assertion, last run result, and bound commit.

### L5 Status, Release, Review, And Canon Closure

| Control ID | Source Candidates | Runs In | Blocks | Required Receipt | Acceptance Criteria |
|---|---|---|---|---|---|
| CTL-040 Objective criteria artifact | CC-004 | Work-item intake | status, release | `objective_criteria_receipt` | Criteria and evidence types exist before implementation or are marked late/weak. |
| CTL-041 Phase exit receipt | CC-005 | Orchestrator state machine | phase_transition, status | `phase_exit_receipt` | Required artifacts, checks, findings, and outcome are recorded before state advances. |
| CTL-042 Review packet isolation | CC-023 | Review/caucus context assembler | status, release | `review_packet_receipt` | Reviewers receive files, diffs, receipts, command output, and criteria, not producer summaries. |
| CTL-043 Finding disposition gate | CC-024 | Orchestrator/review gate | phase_transition, mutation, status, release | `finding_disposition_receipt` | Open High/Critical findings block transition unless explicitly accepted by an authorized human. |
| CTL-044 Backlog promotion proof | CC-025 | Wrap-up/status gate | phase_transition, status | `backlog_promotion_receipt` | Every bug, failing test, unsafe route, unsupported recommendation, or surprising mutation gets a backlog item or no-action rationale. |
| CTL-045 Product-canon promotion gate | CC-026 | Effort closure | status | `canon_promotion_receipt` | Local effort decisions needed by future work are promoted to roadmap/docs/tests/backlog/release gates or explicitly left local. |
| CTL-046 Work-item readiness gate | CC-027 | Workflow intake | phase_transition | `readiness_receipt` | Scope, parent goal, objective criteria, required sources, artifact tree, and owner are known before design/implementation. |
| CTL-047 Recent-change/open-PR review | CC-028 | Workflow intake; release gate | phase_transition, release | `change_context_receipt` | Recent commits, dirty tree, branch divergence, open PRs, and touched files are reviewed before high-stakes work. |
| CTL-048 Public distribution privacy preflight | CC-029 | Public release gate | public_distribution, release | `privacy_distribution_receipt` | Public plugin/docs/release checks permissions, secrets, auth assumptions, channel, visibility, installed-user file access, network access, hooks, project mutation commands, and provider-bound data before distribution. |
| CTL-049 Documentation capability proof | CC-030 | Docs/release gate | release when critical | `docs_capability_receipt` | Docs do not claim unsupported installed behavior; future behavior is labeled as future. |

Design notes:

- These controls directly target the false-closure chain: artifact existence,
  criteria checkboxes, audit trails, and release notes are not enough.
- Review/caucus remains useful only when findings can block transitions and are
  backed by evidence packets.

### L5a Release Identity

| Control ID | Source Candidates | Runs In | Blocks | Required Receipt | Acceptance Criteria |
|---|---|---|---|---|---|
| CTL-050 Release identity receipt | CC-008, CC-031 | Release gate | release, public_distribution | `release_identity_receipt` | Release identity binds branch, commit, tag, package version, plugin version, changelog entry, channel, update discovery result, install path, and artifact path/hash. |
| CTL-051 Branch and channel identity gate | CC-008 | Release gate | release | `release_identity_receipt` | Branch and release channel match policy; stable cannot see beta-only update/distribution paths. |
| CTL-052 Version metadata consistency gate | CC-008, CC-030 | Release gate | release | `release_identity_receipt` | Package, plugin, manifest, changelog, tag, and release notes agree or explicitly explain a supported mismatch. |
| CTL-053 Published artifact identity gate | CC-008, CC-031 | Release gate | release, public_distribution | `release_identity_receipt` | The artifact being published is built from the bound commit and has recorded path/hash or package identifier. |
| CTL-054 Update discovery channel gate | CC-008, CC-029 | Release/update gate | release, public_distribution | `release_identity_receipt` | Stable and beta update discovery are tested separately and cannot route stable users to beta. |
| CTL-055 Release notes capability proof | CC-030 | Release/docs gate | release | `release_identity_receipt`, `docs_capability_receipt` | Release notes and changelog only claim capabilities proven by installed-entrypoint or explicit future/deferred labels. |

Design notes:

- Release identity is a compound chain, not one branch check.
- The release gate should fail closed if any identity field is missing for a
  public or user-facing release.
- Channel leakage is a first-class release failure, not a docs typo.

### L6 Optional Provider Observability

| Control ID | Source Candidates | Runs In | Blocks | Required Receipt | Acceptance Criteria |
|---|---|---|---|---|---|
| CTL-060 Provider health snapshot | CC-033 | Optional high-stakes workflow context | none initially | `provider_health_receipt` | Records model/provider identity when observable, latency, retries/errors, and user-observed degradation. |
| CTL-061 Synthetic provider probe | CC-034 | Optional diagnostic | none initially | `provider_probe_receipt` | Runs deterministic shape checks for instruction following, structured output, and evidence discipline. |
| CTL-062 Degraded-provider high-stakes block | CC-035 | Future optional gate | mutation, status, release if enabled | `provider_health_receipt` | If enabled, suspect provider health fails closed for irreversible high-stakes gates. |
| CTL-063 Model/provider switch approval | CC-036 | Future optional routing | phase_transition | `model_switch_approval` | Any provider/model fallback requires explicit approval and records changed behavior assumptions. |

Design notes:

- Do not include L6 in the first implementation plan unless scope changes.
- L6 can explain anomalous agent quality, but it must not excuse missing local
  evidence controls.
- L6 cannot block beta 4.x feature thaw unless a later story explicitly adopts
  it as a supported observability feature.

## Rejected Or Non-Standalone Controls

These are not promoted as standalone controls:

| Idea | Decision | Reason |
|---|---|---|
| Generic supervisor approval | Reject as standalone | Human approval without evidence packet and blocking disposition recreates review theater. |
| Raw stage-gate prompts | Reject as standalone | Cadence is useful, but prompts do not enforce state transitions. |
| Promise documents that restate canon | Reject by default | They increase contradiction surface unless they add a distinct decision/control. |
| Checkpoint existence | Reject as restore proof | Must include scope, restore command, and validation. |
| Version label or branch name alone | Reject as release identity | Must be bound to tag, commit, package/plugin metadata, channel, and install path. |
| "Tests passed" alone | Reject as completion evidence | Must map to objective criteria, contract, invariant, or postcondition. |
| Provider failover without approval | Reject | Different model/provider behavior is a product decision, not hidden plumbing. |

## Receipt Inventory

The first implementation plan should define schemas for these receipt families:

| Receipt Family | Controls | Durable Location |
|---|---|---|
| Evidence/context | CTL-001, CTL-002, CTL-003, CTL-004 | `.sweetclaude/state/receipts/` or workflow state |
| Mutation | CTL-010, CTL-011, CTL-012, CTL-013, CTL-014, CTL-015, CTL-016 | `.sweetclaude/state/receipts/`, command run directory |
| Capability/manifest | CTL-020, CTL-021, CTL-022, CTL-023 | `.sweetclaude/state/receipts/`, release evidence |
| Source/spec | CTL-030, CTL-031, CTL-032, CTL-033, CTL-034, CTL-035 | Workflow artifact tree; release evidence for blockers |
| Status/release/review | CTL-040, CTL-041, CTL-042, CTL-043, CTL-044, CTL-045, CTL-046, CTL-047, CTL-048, CTL-049 | Workflow state, effort tree, release evidence |
| Release identity | CTL-050, CTL-051, CTL-052, CTL-053, CTL-054, CTL-055 | Release evidence |
| Provider observability | CTL-060, CTL-061, CTL-062, CTL-063 | Optional local telemetry, disabled by default |

Implementation should avoid scattering bespoke receipt formats across commands.
Define common fields once, then command-specific extensions.

## Command Surface Mapping

| Command / Surface | Required Controls |
|---|---|
| `doctor` | CTL-001, CTL-002, CTL-016, CTL-020, CTL-021, CTL-022, CTL-030 |
| `update` | CTL-001, CTL-002, CTL-003, CTL-010, CTL-011, CTL-012, CTL-013, CTL-014, CTL-015, CTL-016, CTL-020, CTL-021, CTL-022, CTL-023, CTL-054 |
| `migrate` | CTL-001, CTL-002, CTL-003, CTL-010, CTL-011, CTL-012, CTL-013, CTL-014, CTL-015, CTL-016, CTL-020, CTL-021, CTL-022, CTL-023, CTL-030, CTL-031, CTL-032 |
| `recover` | CTL-001, CTL-002, CTL-003, CTL-010, CTL-011, CTL-012, CTL-013, CTL-014, CTL-015, CTL-016, CTL-020, CTL-021, CTL-022 |
| `status` | CTL-001, CTL-002, CTL-003, CTL-004, CTL-040, CTL-041, CTL-042, CTL-043, CTL-044, CTL-045, CTL-046, CTL-047 |
| `release` | CTL-001, CTL-002, CTL-003, CTL-004, CTL-023, CTL-033, CTL-034, CTL-040, CTL-041, CTL-042, CTL-043, CTL-044, CTL-045, CTL-047, CTL-048, CTL-049, CTL-050, CTL-051, CTL-052, CTL-053, CTL-054, CTL-055 |
| Orchestrator workflow transitions | CTL-001, CTL-002, CTL-003, CTL-004, CTL-030, CTL-031, CTL-032, CTL-033, CTL-034, CTL-035, CTL-040, CTL-041, CTL-042, CTL-043, CTL-044, CTL-045, CTL-046, CTL-047 |
| Public distribution | CTL-003, CTL-023, CTL-048, CTL-049, CTL-050, CTL-051, CTL-052, CTL-053, CTL-054, CTL-055 |

## Beta 4.x Blocking Set

These controls are the minimum design blockers for beta 4.x release safety:

- CTL-001 Evidence receipt schema
- CTL-002 Evidence freshness validator
- CTL-003 Gate context binding
- CTL-010 Mutation plan gate
- CTL-011 Write-set and blast-radius monitor
- CTL-012 Approval scope validator
- CTL-013 Snapshot scope validator
- CTL-014 Restore proof gate
- CTL-015 Postcondition validator
- CTL-016 Repair loop budget
- CTL-020 Capability manifest resolver
- CTL-021 Manifest/schema validator
- CTL-022 Capability support receipt
- CTL-023 Installed-entrypoint smoke gate
- CTL-030 Source discovery validator
- CTL-031 Source precedence gate
- CTL-033 Contract conformance test requirement for user-facing maintenance and release contracts
- CTL-034 Load-bearing invariant requirement
- CTL-040 Objective criteria artifact
- CTL-041 Phase exit receipt
- CTL-043 Finding disposition gate
- CTL-044 Backlog promotion proof
- CTL-047 Recent-change/open-PR review
- CTL-049 Documentation capability proof
- CTL-050 Release identity receipt
- CTL-051 Branch and channel identity gate
- CTL-052 Version metadata consistency gate
- CTL-053 Published artifact identity gate
- CTL-054 Update discovery channel gate
- CTL-055 Release notes capability proof

The remaining promoted controls are important but can be sequenced after the
minimum blocker set if implementation pressure requires it.

## Design Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Overbuilding the receipt system | Delays release-safety work | Start with one common receipt schema and command-specific minimal extensions. |
| Controls become advisory prose again | Recreates current failure mode | Each implementation story must name the transition it blocks and the failing fixture. |
| Manifest resolver becomes another version table | Reintroduces version chasing | Capabilities must describe supported behavior and project shape, not release-specific scripts only. |
| Human review still rubber-stamps | False confidence | Review packet isolation plus finding disposition gates make review findings transition-blocking. |
| Checkpoint/restore proof is expensive | Mutation work slows down | Use fixture/dry-run restore proof first; require full round-trip only for high-risk mutations. |
| Provider observability distracts | Scope creep | Keep L6 deferred unless a future story explicitly accepts it. |

## Next Design Step

Draft the test strategy for the beta 4.x blocker set before implementation
planning. The test strategy should define adversarial fixtures for:

1. stale or mismatched evidence receipts
2. gate-context mismatch across checkout/install/release state
3. mutation outside the approved write set
4. unsupported manifest/capability recommendations
5. source/spec precedence failures
6. missing contract or invariant test evidence
7. false status rollup and false release
8. stable/beta update discovery leakage
