# Issue tracker: GitHub

Issues and specs for this repo live in [bmtymrak/alcove](https://github.com/bmtymrak/alcove/issues). Use the `gh` CLI for all operations.

## Conventions

Run commands inside this checkout; `gh` infers the repository from its Git remote. Outside the checkout, pass `--repo bmtymrak/alcove`.

- **Create an issue**: `gh issue create --title "..." --body-file <path>`.
- **Read an issue**: `gh issue view <number> --json number,title,body,labels,comments`.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments`, with appropriate `--label` and `--state` filters.
- **Make an issue a sub-issue of a parent**: `gh api --method POST repos/bmtymrak/alcove/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>`. Get the child's numeric database ID with `gh api repos/bmtymrak/alcove/issues/<child> --jq .id`. Where sub-issues aren't available, put `Part of #<parent>` at the top of the child body and add the child to a task list in the parent body.
- **Comment on an issue**: `gh issue comment <number> --body-file <path>`.
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`.
- **Close**: post any explanation as a comment, then `gh issue close <number>`.

For multiline bodies and comments, write the text to a temporary file and pass it with `--body-file`.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>`.
- **List external PRs for triage**: `gh api --paginate 'repos/bmtymrak/alcove/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`.
- **Comment / label / close**: `gh pr comment --body-file <path>`, `gh pr edit --add-label` / `--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs. Resolve a bare `#42` with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue, using the convention above. Labels: `wayfinder:<type>` (`research` / `prototype` / `grilling` / `task`). Once claimed, the ticket is assigned to the driving developer.
- **Blocking**: use GitHub's native issue dependencies. Add an edge with `gh api --method POST repos/bmtymrak/alcove/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`. Get the blocker's numeric database ID with `gh api repos/bmtymrak/alcove/issues/<blocker> --jq .id`. GitHub reports `issue_dependencies_summary.blocked_by` as the count of open blockers. Where dependencies aren't available, use a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children, scoped to its sub-issues or task list. Drop any with an open blocker or an assignee; first in map order wins.
- **Claim**: `gh issue edit <number> --add-assignee @me`, the session's first write.
- **Resolve**: post the answer with `gh issue comment <number> --body-file <path>`, close the ticket, then append a context pointer (gist + link) to the map's Decisions-so-far.
