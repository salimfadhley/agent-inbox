# Specification Quality Checklist: Single-Owner Authentication

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-25
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Requirement types are separated (Functional / Non-Functional / Constraints)
- [x] IDs are unique across FR-###, NFR-###, and C-### entries
- [x] All requirement rows include a non-empty Status value
- [x] Non-functional requirements include measurable thresholds
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- **Implementation-tech mentions are deliberate and confined.** The settled means
  (Argon2id, TOTP/`otpauth://`, bearer tokens) appear only where they are the *acceptance
  criterion itself* — NFR-001 (what a DB dump must not reveal) and the enrolment/QR
  mechanic the user explicitly asked for ("scan a barcode"). The functional requirements
  are stated as behaviours, not code. This is consistent with the house style of the M2
  spec, which names its wire format and ADRs.
- **Four details are deliberately deferred to plan**, not left ambiguous in the spec:
  exactly how the human session rides through the stateless console to the API,
  token/session lifetimes, TOTP-secret encryption-key management, and recovery-code UX.
  These are design choices with reasonable defaults, not scope questions — each is called
  out in Assumptions / the overview so plan can resolve them without re-opening scope.
- All prior scope forks (single-owner, all-admins, local+TOTP-first, Jenkins bootstrap,
  grace mode) were resolved with the user before this spec; they appear as accepted
  constraints, not open questions.
