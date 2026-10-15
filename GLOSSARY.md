# VPS Services

Vocabulary for the platform that hosts applications on a single VPS.

## Language

**VPS platform**:
Shared server capabilities that applications depend on to be hosted.
_Avoid_: global application stack.

**Application**:
Product identified by its repository, with its own needs and its own delivery cycle.
_Avoid_: service, when you mean the whole product.

**Application service**:
Component of an application, for example its web UI, API, or database.

**Instance**:
Isolated occurrence of an application in a given environment.
_Avoid_: application, when you mean only its occurrence in staging or preview.

**Production**:
Long-lived environment that serves the product to its users.

**Staging**:
Long-lived validation environment for an application, separate from its production and its previews.
_Avoid_: permanent preview.

**Preview**:
Temporary environment tied to one pull request of an application.
_Avoid_: PR staging.

**Preview slot**:
Unit of the shared cap that limits how many previews are on the VPS at once, across all applications.
_Avoid_: quota per repository.

**Admission**:
Decision to accept creating or changing an instance given the VPS shared capacity and rules.

**Test data**:
Data meant to validate an instance, separate from production data and from other instances.
