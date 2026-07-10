
## Project
**Name:** Archive-Sync Engine

# Goal
A Linux-native Python application that archives and synchronizes messaging platforms using a platform-independent canonical model.

Primary intended workflow is **1-to-1 synchronization** (Discord → Fluxer or Fluxer → Fluxer). Multi-destination synchronization is intentionally out of scope.

# The Guiding Principle

If I had to summarize the entire architecture in a single sentence, it would be:

`The Archive-Sync Engine should be a platform-agnostic synchronization engine that operates solely on canonical models, with every platform-specific concern isolated behind thin adapter interfaces and every business decision centralized within the engine.`

## Additional Guiding Principles

> Most components should collaborate rather than inherit.

> The ArchiveEngine is an orchestrator, not an implementation.

> The Archive is the authoritative local system of record. The ArchiveEngine orchestrates synchronization by comparing external systems against the Archive and applying the necessary operations to keep them consistent.

> The canonical model should preserve semantically meaningful information from the source platform whenever that information is platform-independent and may influence future synchronization, export, or archival behavior.

> The Archive should preserve intent, not merely compatibility.

> Archival: "What information existed on the source system?"

> The canonical model should not fabricate identifiers that do not exist conceptually.

> Each orchestration layer coordinates only the layer immediately beneath it. Sibling components never orchestrate each other.

> Orchestration and work should be separate responsibilities.

> CanonicalMessage: A message must contain at least one form of content.

> Changes to the canonical model should require a demonstrated use case from implementation, not speculation.

> An ImportOperation should describe one atomic unit of acquisition work.

### Syncing

> A SyncOperation represents an atomic synchronization action, not an adapter call. The Planner produces synchronization operations from canonical state. The OperationExecutor interprets those operations and coordinates the required interactions with engine components. Operations describe what must be accomplished; they do not prescribe how it is accomplished.

> SyncState is just another kind of archived data.

> A SyncOperation is an atomic synchronization action produced by the Planner.

> Synchronization: "What is the minimum information required to reproduce content?"

> Each type of SyncOperations should answer the question: "What canonical entity does this operation concern?"

> When syncing: Every feature becomes an Operation.

### Operation

> The OperationExecutor interprets the SyncOperation and performs whatever work is necessary to satisfy it.

## Single Responsibility

Every component has one job.

## Code Design

### Synchronization Pipeline and Importer Pipeline

In both cases, one component produces immutable operations, and another coordinates their execution.

#### Importer Pipeline

Acquisition Pipeline

SourceAdapter
      │
      ▼
Importer
      │
      ▼
ImportOperations
      │
      ▼
ImportCoordinator
      │
      ▼
Archive

#### Synchronization Pipeline

Synchronization Pipeline

Archive
      │
      ▼
Planner
      │
      ▼
SyncOperations
      │
      ▼
OperationExecutor
      │
      ▼
DestinationAdapter


### Inheritance and Non-Inheritance Design Usage

The synchronization pipeline uses an inheritance hierarchy:

    SyncOperation
    ├── ConversationOperation
    ├── MessageOperation
    ├── AttachmentOperation
    ├── IdentityOperation
    └── ReactionOperation

But ImportOperations do not. ImportOperations represent work, not entities.

    ImportOperation
    ├── EnumerateConversationsOperation
    ├── ImportConversationOperation
    ├── EnumerateMessagesOperation
    └── ImportMessageOperation

Notice the difference.

Synchronization is entity-centric:

    Create Message
    Delete Message
    Edit Message

Import is workflow-centric:

    Enumerate Messages
    Download Attachment
    Store Attachment
    
### Code Imports

> Import Rule: All internal imports shall be absolute package imports.
>   Preferred:
>
>     from archive_sync_engine.models import CanonicalMessage
>   Avoid:
>     from ..models import CanonicalMessage
>   Avoid:
>     from models import CanonicalMessage


# Relationships


1. Canonical-First Architecture

Principle

The Archive-Sync Engine is not a Discord synchronization tool or a Fluxer synchronization tool.

It is a synchronization engine that operates on a platform-independent representation.

```
Discord
        \
         \
          Canonical Model ---> Fluxer
         /
        /
Fluxer
```

Nothing in the engine should depend on Discord concepts, Fluxer concepts, or any future platform.

2. Planning and Execution are Separate

One of our biggest design decisions.

Planner:
```
Current State

↓

Desired State

↓

Operations
```

Executor:
```
Operations

↓

Work
```

The planner never performs work.

The executor never decides what work should exist.

3. Thin Adapters

Adapters should be almost boring.

Example
```
Discord Message

↓

Canonical Message
```

No planning.

No reconciliation.

No synchronization.

No business rules.

Those belong inside the engine.

# Identifier Model

The Archive-Sync Engine deliberately separates identifiers into three distinct categories.

        Canonical Message
                │
                ▼
        MessageId
                │
                ▼
        Sync Mapping
                │
        DestinationId
                │
                ▼
        Platform Message Reference
                │
                ▼
        Discord / Fluxer

These three identifiers intentionally represent different concepts.

They must never be treated as interchangeable.

## 1. Canonical Identifier

Examples:

- ConversationId
- MessageId
- AttachmentId
- IdentityKey

Purpose:

- identifies canonical archive entities
- platform-independent
- immutable
- used throughout the engine

These identifiers represent the Archive's view of the world.
---

## 2. Destination Identifier

Example:

- DestinationId

Destination identifiers do **not** identify platform resources.

Instead they identify where synchronization is occurring.

Examples:

- discord-main
- fluxer-archive
- backup-server

Destination identifiers identify a logical synchronization destination.

---

## 3. ### Destination References

Examples:

- DestinationConversationRef
- DestinationMessageRef
- DestinationAttachmentRef
- DestinationIdentityRef

Destination references are returned by destination adapters after
successfully creating platform resources.

Their identifiers are opaque.

The Archive Engine must never interpret their contents.

They exist solely so future adapter operations can reference previously
created resources.


---

## Adapter Model

Adapters isolate the Archive Engine from platform-specific APIs.

Every platform implementation must implement one of two abstract
interfaces.

### SourceAdapter

Responsibilities:

- Read platform state
- Translate platform objects into canonical models
- Download attachment bytes

Source adapters never:

- Write data
- Synchronize
- Plan operations
- Persist archive state

---

### DestinationAdapter

Responsibilities:

- Create platform resources
- Update platform resources
- Delete platform resources
- Upload attachments
- Return destination references

Destination adapters never:

- Plan synchronization
- Reconcile state
- Maintain mappings
- Persist archive state

---

Adapters expose only canonical models and opaque destination references.

Platform-specific objects must never cross the adapter boundary.


# Final High-Level Architecture

> Every long-lived resource has exactly one owner, and every shorter-lived component borrows that resource rather than creating its own.



| Resource          | Owner                              | Borrowed By              |
| ----------------- | ---------------------------------- | ------------------------ |
| Archive           | ArchiveEngine                      | SyncSession              |
| SQLite connection | Archive                            | Repositories             |
| Logger            | ArchiveEngine                      | All services             |
| Configuration     | ArchiveEngine                      | All services             |
| HTTP client       | SourceAdapter / DestinationAdapter | Internal adapter methods |
| Planner           | SyncSession                        | Nobody                   |
| OperationExecutor | SyncSession                        | Nobody                   |


Archive Sync Engine
├── SyncSession
│
├── ImportCoordinator
│   ├── Importer
│   └── Import Operations
│
├── Models
│   ├── Canonical Models
│   └── Sync Operations
│
├── Planner
├── OperationExecutor
│
├── Archive
├── AssetStore
├── Adapter Interfaces
│   ├── SourceAdapter
│   └── DestinationAdapter
│
└── StateRepository

External Packages
├── Discord Adapter
├── Fluxer Adapter
└── Future Adapters


Part of the engine:

               ArchiveEngine
                     │
         ┌───────────┴───────────┐
         │                       │
    SourceAdapter         DestinationAdapter
    
- The adapter interfaces (SourceAdapter, DestinationAdapter) are part of the engine.
- Concrete adapter implementations (Discord, Fluxer, etc.) are outside the engine.


Or put another way:

ArchiveEngine
 ┌───────────┐
 │ Config    │
 │ Logger    │
 │ Archive   │◄─────────────┐
 └───────────┘              │
         │                  │
 new_session()              │
         │                  │
         ▼                  │
 ┌───────────────────┐      │
 │   SyncSession     │──────┘
 ├───────────────────┤
 │ Planner           │
 │ Executor          │
 │ SourceAdapter     │
 │ DestinationAdapter│
 └───────────────────┘

## Component Responsibilities

### ArchiveEngine

Coordinates synchronization.

### Importer

The Importer translate the data exposed by a SourceAdapter into a stream of ImportOperations, and the ImportCoordinator should be responsible for executing those operations, checkpointing progress, and handling pause/resume.

### SyncSession

Owns all state for a single synchronization run.

### Planner

Produces SyncOperations.

### OperationExecutor

Executes SyncOperations.

### Archive

Archive = canonical content (source of truth)
StateRepository = engine metadata and operational state

Stores canonical conversations, identities, messages, attachments, and reactions. This is the source of truth for imported content.

The Archive owns the _what_ (canonical content), while the StateRepository owns the _how_ and _where_ (operational state).

### AssetStore

Stores binary attachment data addressed by SHA-256.

### StateRepository

Persists synchronization state and destination mappings.

Stores synchronization metadata and engine state, such as destination mappings, import sessions, sync sessions, checkpoints, and future operational metadata. It never owns canonical content.

### SourceAdapter

Imports canonical data.

### DestinationAdapter

Exports canonical data.


## Dependency Rule

Dependencies always point inward.

```
Platform Adapter
        │
        ▼
Adapter Interfaces
        │
        ▼
Canonical Models
        │
        ▼
Planner
Executor
ArchiveEngine
```

Higher-level components never depend on platform implementations.

Canonical models never depend on adapters.

Adapters never depend on Planner, Executor, StateRepository or Archive.

This rule preserves testability, portability and separation of concerns.


