# Trusted Capability Registry v1

## Purpose

Separates **eligible for trust** from **trusted by Axiom**.

A capability becomes eligible through successful validation.
A capability becomes trusted only through explicit human promotion.
Mutation/high-risk capabilities remain permanently blocked.

## Chain Position

```
Knowledge → Plan → Plan Review → Validation Request → Validation Execution
→ Trusted Capability Registry (PR #54)
```

## Models

| Model | Role |
|-------|------|
| `TrustedCapability` | Capability with trust status, evidence, counts |
| `TrustStatus` | Enum: unknown, eligible, trusted, revoked, blocked |
| `TrustAction` | Enum: promoted, revoked, blocked, eligibility_granted, validation_passed/failed |
| `TrustEvidence` | Evidence supporting a trust decision |
| `TrustRevocation` | Record of a revocation event |
| `TrustHistory` | Audit log of all trust actions for a capability |

## Trust Lifecycle

```
UNKNOWN → (validation passes) → ELIGIBLE → (explicit promote) → TRUSTED
                                                    ↓
                                               (revoke) → REVOKED
```

Blocked capabilities (SetParameterValue, DeleteElements, MoveElements,
RotateElements, CreateWalls, CreateFloors, CreateRoofs) can never reach
TRUSTED regardless of evidence.

## CLI Commands

```bash
axiom trusted-capabilities [--status <status>] [--json-output]
axiom trusted-capability --name <name> [--json-output]
axiom trusted-capability-promote --capability <name> [--by <actor>] [--json-output]
axiom trusted-capability-revoke --capability <name> [--by <actor>] [--reason <text>] [--json-output]
```

## Safety Rules

1. Promotion is always explicit — never automatic
2. Blocked capabilities cannot be promoted regardless of evidence
3. Capabilities with recorded failures cannot be promoted
4. Revocation preserves full history
5. No execution occurs — governance only

## Non-Goals

- No autonomous promotion
- No execution
- No learning
- No scheduling
