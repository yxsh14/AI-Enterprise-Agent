# Confluence Upload Checklist

Upload these pages into the Confluence space configured by `CONFLUENCE_SPACE_ID` or `CONFLUENCE_SPACE_KEY`.

Recommended Confluence structure:

```text
Enterprise Assistant Knowledge Base
  Meeting Logs          folder id: 1277953
  Enterprise Policies   folder id: 1638401
  Employee Profiles     folder id: 1179656
```

You can use Live Docs for all of these. The app already supports `CONFLUENCE_PAGE_SUBTYPE=live`.

## Meeting Log Pages

Use the `.docs` files in `enterprise_docs/meeting_logs/` as the source content:

- `2026-07-01-engineering-standup.docs` -> Engineering Daily Standup
- `2026-07-02-customer-escalation-review.docs` -> Customer Escalation Review
- `2026-07-03-operations-sync.docs` -> Operations Sync
- `2026-07-04-security-review.docs` -> Security Review
- `2026-07-05-sales-operations.docs` -> Sales Operations Review
- `2026-07-06-platform-release.docs` -> Platform Release Readiness
- `2026-07-07-hr-onboarding.docs` -> HR Onboarding Sync
- `meeting-log-index.docs` -> Meeting Log Index table

Each meeting page should keep these fields:

- `Date`
- `Department`
- `Attendees`
- `Issues Addressed`
- `Decisions`
- `Action Items`

## Employee Profile Pages

Create one Confluence page per employee the assistant should answer questions about. Source files are in `enterprise_docs/employee_profiles/`:

- `employee-profile-priya-sharma.docs` -> Employee Profile - Priya Sharma
- `employee-profile-daniel-chen.docs` -> Employee Profile - Daniel Chen
- `employee-profile-maya-johnson.docs` -> Employee Profile - Maya Johnson

Recommended title format:

```text
Employee Profile - Full Name
```

Recommended fields:

- Name
- Role
- Department
- Location
- Manager
- Email
- Responsibilities
- Systems owned
- Current projects
- Escalation contact rules

Example page title:

```text
Employee Profile - Priya Sharma
```

## Search Notes

- Keep all pages in the same Confluence space used by `CONFLUENCE_SPACE_ID`.
- Leave `CONFLUENCE_PAGE_TITLE_FILTER` blank if you want the assistant to search meeting logs and employee profiles together.
- If all content lives in one folder, use `CONFLUENCE_FOLDER_ID`.
- If content lives in multiple folders, use `CONFLUENCE_FOLDER_IDS=meeting_folder_id,policy_folder_id,employee_folder_id`.
- If you want to search the whole space, leave both `CONFLUENCE_FOLDER_ID` and `CONFLUENCE_FOLDER_IDS` blank.
- If you want to restrict retrieval during testing, set `CONFLUENCE_PAGE_TITLE_FILTER` to a shared prefix used in page titles.

## Enterprise Policy Pages

Create these pages in an `Enterprise Policies` folder. Source files are in `enterprise_docs/policies/`:

- `enterprise-it-access-policy.docs` -> Enterprise IT Access Policy
- `enterprise-incident-management-policy.docs` -> Enterprise Incident Management Policy
- `enterprise-data-handling-policy.docs` -> Enterprise Data Handling Policy
- `enterprise-vpn-and-remote-access-policy.docs` -> Enterprise VPN and Remote Access Policy Guidelines

These pages let the assistant answer policy questions such as:

- "What is the remote access policy?"
- "When should I create an incident instead of a bug?"
- "What fields are required for an access request?"
- "Can confidential customer data be pasted into public AI tools?"
