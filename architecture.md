
## Project
**Name:** Archive-Sync Engine

# Goal
A Linux-native Python application that archives and synchronizes messaging platforms using a platform-independent canonical model.

Primary intended workflow is **1-to-1 synchronization** (Discord → Fluxer or Fluxer → Fluxer). Multi-destination synchronization is intentionally out of scope.

# The Guiding Principle

If I had to summarize the entire architecture in a single sentence, it would be:

`The Archive-Sync Engine should be a platform-agnostic synchronization engine that operates solely on canonical models, with every platform-specific concern isolated behind thin adapter interfaces and every business decision centralized within the engine.`

## Archive Engine High Level Concept

├── Canonical Model
│   (Conversation, Message, Attachment, ...)
│
├── Persistence
│   (ArchiveStore, SQLite, AssetStore)
│
├── Archive Package
│   (manifest.json, archive.sqlite,
│    attachments/)
│
└── Execution State
    (session.json,
     import sessions,
     export sessions,
     resume information)

## Additional Guiding Principles

> Most components should collaborate rather than inherit.

> The ArchiveEngine is an orchestrator, not an implementation.

> The Archive is the authoritative local system of record. The ArchiveEngine orchestrates synchronization by comparing external systems against the Archive and applying the necessary operations to keep them consistent.

> The canonical model should preserve semantically meaningful information from the source platform whenever that information is platform-independent and may influence future synchronization, export, or archival behavior.

> The Archive should preserve intent, not merely compatibility.

> Archival: "What information existed on the source system?"

> The canonical model should not fabricate identifiers that do not exist conceptually.

> The canonical models drive the schema and not the other way around.

> Each SQL table (schema table) represents exactly one concept.

> Each orchestration layer coordinates only the layer immediately beneath it. Sibling components never orchestrate each other.

> Orchestration and work should be separate responsibilities.

> CanonicalMessage: A message must contain at least one form of content.

> Changes to the canonical model should require a demonstrated use case from implementation, not speculation.

> An ImportOperation should describe one atomic unit of acquisition work.

> Design principle: callers interact with canonical aggregates, while ArchiveWriter decomposes those aggregates into normalized tables managed by ArchiveStore.

## Archive & ArchiveWriter

Writing Design:

    Archive receives CanonicalMessage (which is conceptually a Canonical Aggregate) input
    ↓
    ArchiveWriter
    ↓
    ArchiveStore
    ↓
    Normalized Tables (messages, attachments, message_attachments)

Reading Design:

    Normalized Tables (messages, attachments, message_attachments)
    ↓
    ArchiveStore
    ↓
    Archive reconstruct_message()
    ↓
    CanonicalMessage (which is conceptually a Canonical Aggregate)

### Archive:

Public API
The read-only API.
Aggregate reconstruction.

> Archive → read-only, domain-oriented navigation.
> Archive reconstructs canonical aggregates from normalized persistence operations.
    - If we later add reactions, pins, mentions, embeds, or other aggregate components, only this high level of the Archive reconstruct_message() changes.

### ArchiveWriter

Public API
The write-only API.
Aggregate decomposition.

> ArchiveWriter should answer one question: "What canonical entities should be written into the Archive?"
> ArchiveWriter never commits implicitly except when used as a context manager.
> ArchiveWriter prepares content for the storing step.
> ArchiveWriter decomposes canonical aggregates into normalized persistence operations.
> ArchiveWriter owns transaction policy.

- It speaks in terms of domain objects.

Its responsibilities are:
- Accept validated canonical entities.
- Persist them in a transaction.
- Expose transaction boundaries (commit(), rollback()).
- Coordinate writing of multi-table aggregates (for example, a message plus its` message_attachments` rows in the future).

Its responsibilities are not:
- SQL
- Schema knowledge
- Database queries
- Integrity checking
- Reading


### ArchiveStore:

SQL
Normalized persistence.

The private persistence implementation shared by both (ArchiveWriter and Archive).

- It is purely the persistence layer.

> ArchiveStore should answer a different question: "How are canonical entities stored and retrieved?"
> ArchiveStore should be stateless with respect to the archive contents.
> ArchiveStore should never automatically begin, commit, or roll back transactions. Instead, it should behave like a thin persistence engine.
> ArchiveStore commits or retrieves prepared-content into storage.
> ArchiveStore every public Store method should correspond to exactly one SQL table.
> ArchiveStore never owns canonical aggregate composition—it owns normalized persistence only.

Instead, ArchiveWriter.add_message() should orchestrate the aggregate:

        add_message()
        ├── insert_message()
        ├── insert_attachment()      (if needed)
        └── insert_message_attachment()

Responsibilities:
- Open/create SQLite databases.
- Execute SQL.
- Convert rows ⇄ canonical models.
- Insert/update/delete/query entities.
- Manage the SQLite connection and transactions.

It should not know:
- Discord
- Fluxer
- Synchronization
- Archive package policies
- Cross-entity semantic validation


ArchiveValidator: Responsible for checking and fixing archive-wide semantic invariants

These are rare.

Examples:
- orphan attachment blobs on disk
- manifest checksum mismatches
- archive version incompatibility


> All timestamps stored in `archive.sqlite` are UTC, timezone-aware ISO-8601 strings produced by `datetime.isoformat()`.

> Make the relational model align even more closely with the canonical model by distinguishing `entity tables` from `relationship tables`.

Entity tables store standalone canonical entities:

        conversations
        messages
        attachments
        identities

Relationship tables store associations between those entities:

        message_attachments
        message_reactions


The persistence pattern is also established and every Store method follows the same naming convention.

        insert_xxx()
        get_xxx()
        iter_xxx()


ArchiveStore should become a Unit of Work. Conceptually:

        ArchiveWriter
        │
        ▼
        ArchiveStore
        ├── SQLite connection
        ├── Current transaction
        ├── Entity persistence
        └── Row ↔ Model mapping
        
### ArchiveManifest

> ArchiveManifest.py: Describe the Archive Package itself, not the archived content.

### Messages

> A Message should not directly reference a database row in an identities table. Instead it should store the canonical identity key.

Conceptually this is `author_identity_key`. That makes identity resolution adapter-independent.

It also matches how masquerading works.

### Identity

The Identity table should be treated as a cache of identity metadata rather than a structural dependency of the archive.

### Attachments

A CanonicalAttachment is content-addressed.

The same attachment may appear in multiple messages.

The archive shouldn't duplicate it.

That was one of the original motivations for SHA-256 storage.

> A CanonicalAttachment exists independently as content-addressed data, while the relationship between a message and its attachments is preserved explicitly.

> The structure which preserves the relationship between a CanonicalAttachment and a CanonicalMessage is the `message_attachments` SQL table.

From `CanonicalAttachment` model schema (SQL):

        message_attachments
        -------------------
        message_id
        attachment_id
        ordinal

Then separately:

        attachments
        -----------
        id
        sha256
        filename
        media_type
        size

### Archive Package Persistence Mapping

#### CanonicalConversation

```
Entity Table

conversations

Columns
-------
id
conversation_type
display_name
created_at

Relationships
-------------
Messages
    messages.conversation_id → conversations.id
```

##### Notes

A Conversation is the top-level container for archived messages.

A Conversation does not directly own a collection of messages in memory. Instead, messages are related through the Archive API:

        archive.iter_messages(conversation_id)

#### CanonicalIdentity

```
Entity Table

identities

Columns
-------
identity_key
display_name

Relationships
-------------
Referenced by Messages
Referenced by Reactions
```

##### Notes

Identities are canonical entities describing authors.

Messages reference an Identity by its canonical `identity_key`.

An archived Message remains valid even if the Identity metadata has not yet been imported.

#### CanonicalMessage

```
Entity Table

messages

Columns
-------
id
conversation_id
identity_key
created_at
edited_at
reply_to
content

Relationships
-------------
Conversation
Attachments
Reactions
```

##### Notes

Messages are the central entity of the Archive.

Attachments and Reactions are stored independently and associated through relationship tables.

A Message satisfies the canonical invariant:

- text only
- attachment only
- text + attachment

An empty message is invalid.

#### CanonicalAttachment

```
Entity Table

attachments

Columns
-------
id
sha256
filename
media_type
size

Relationships
-------------
Messages
```

Relationship table:
```
message_attachments
-------------------
message_id
attachment_id
ordinal
```

##### Notes

Attachments are content-addressed.

Their binary contents are stored separately inside:

        attachments/

using SHA-256 filenames.

The SQLite archive stores only metadata.

#### CanonicalReaction

```
Entity Table

reactions

Columns
-------
message_id
identity_key
emoji

Relationships
-------------
Message
Identity
```

##### Notes

Reactions belong to Messages.

Multiple users reacting with the same emoji produce distinct rows.

        
### Syncing

> A SyncOperation represents an atomic synchronization action, not an adapter call. The Planner produces synchronization operations from canonical state. The OperationExecutor interprets those operations and coordinates the required interactions with engine components. Operations describe what must be accomplished; they do not prescribe how it is accomplished.

> Synchronization must be restartable from first principles. The planner should always compute the remaining work from the current Archive and synchronization state, rather than resuming from a persisted list of operations.

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

### Pipeline Diagrams

Pipeline diagrams describe the flow of data between components. Coordinators are orchestration components and are intentionally omitted from pipeline diagrams because they manage execution rather than transform data.

#### Synchronization Pipeline and Importer Pipeline

In both cases, one component produces immutable operations, and another coordinates their execution.

##### Importer Pipeline

Acquisition Pipeline:

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

##### Synchronization Pipeline

Synchronization Pipeline:

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


### Synchronization Runtime

                    Archive
                       │
                       │
Planner ◀──────────────┤
                       │
                       ▼
               SyncCoordinator
                  │       │
                  │       │
                  ▼       ▼
        OperationExecutor  StateRepository
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

Planner responsibility: Produce a deterministic, dependency-safe sequence of SyncOperations. The OperationExecutor must execute operations in the order received and must not reorder them.

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


