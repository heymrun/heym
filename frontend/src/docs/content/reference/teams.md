# Teams

Teams let you share workflows, credentials, global variables, and vector stores with a group of users at once.

## Overview

- **Team** – A named group with a creator and members
- **Creator** – Always a member; can edit team, delete team, add members
- **Member** – Can add and remove other members (except creator); has access to resources shared with the team

## Creating and Managing Teams

Create teams from the [Teams tab](../tabs/teams-tab.md). Add members by email; they must have an account. The creator cannot be removed. Deleting a team removes all team shares.

## Sharing Model

Resources can be shared with:

1. **Individual users** – By email (user-to-user share)
2. **Teams** – By selecting a team (team share)

Both models are additive. A user gains access if they are either:

- Shared directly (user share), or
- A member of a team that has a team share

## What Can Be Shared with Teams

| Resource | Share Location |
|----------|----------------|
| Workflows | Share dialog in workflow editor |
| Workflow Templates | Share dialog when creating/editing a workflow template |
| Node Templates | Share dialog when creating/editing a node template |
| Credentials | Share dialog in Credentials tab |
| Global Variables | Share dialog in Variables tab |
| Vector Stores | Share dialog in Vectors tab |

For templates, when visibility is **Specific users**, you can also select teams. All members of selected teams gain access to the template.

## API Endpoints

- `GET /api/teams` – List teams the user belongs to
- `GET /api/teams/{id}` – Get team details with members
- `GET /api/teams/{id}/shared-entities` – Returns entities shared with the team (workflows, credentials, global variables, vector stores, workflow templates, node templates)
- `POST /api/teams` – Create team
- `PATCH /api/teams/{id}` – Update team
- `DELETE /api/teams/{id}` – Delete team (creator only)
- `POST /api/teams/{id}/members` – Add member (body: `{ "email": "..." }`)
- `DELETE /api/teams/{id}/members/{user_id}` – Remove member

Team shares per resource:

- `GET/POST/DELETE /api/workflows/{id}/team-shares`
- `GET/POST/DELETE /api/credentials/{id}/team-shares`
- `GET/POST/DELETE /api/global-variables/{id}/team-shares`
- `GET/POST/DELETE /api/vector-stores/{id}/team-shares`

## Related

- [Teams Tab](../tabs/teams-tab.md) – Create and manage teams
- [Templates Tab](../tabs/templates-tab.md) – Share workflow and node templates with teams
- [Credentials Sharing](./credentials-sharing.md) – Share credentials with users and teams
- [Workflow Organization](./workflow-organization.md) – Folders and workflow sharing
