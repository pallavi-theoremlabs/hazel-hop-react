---
title: "Create Your Hazel Account React implementation specification"
document_type: "react-implementation-spec"
source: "generated"
status: "approved"
authority: "approved-scope-a-implementation"
feature_id: "member-create-account"
source_spec: "02-design-and-workflows/specs/member-portal/create-account.md"
source_spec_status: "approved"
source_spec_version: "1.0"
source_spec_sha256: "4750108963a9f2ce3f8b2611936679d1da5dc92b2061c8444de0dbceb2e3d9d4"
source_kb_commit: "04c6d1adc9d224d3cf6bfc68115b2b5cd44c44ed"
target_repository: "hazel-hop-react"
target_commit: "88df7b28ac43793cbf5ae49a7529acf317905fc0"
generated_on: "2026-08-20"
implementation_spec_version: "1.0"
approved_route: "/create-account"
approved_route_status: "temporary-ui-review"
approved_by: "Requester (human approval in this task)"
approved_at: "2026-08-20"
approval_source: "Direct human instruction approving the Scope A temporary UI/review route"
---

> [!IMPORTANT]
> **APPROVED FOR SCOPE A IMPLEMENTATION.** Approval is limited to frontend prototype-parity UI at the temporary `/create-account` review route. This route is not the final production invitation, registration, or authentication URL.

# Create Your Hazel Account — React implementation specification

## 1. Source specification

- Feature ID: `member-create-account`.
- Approved-source candidate: `02-design-and-workflows/specs/member-portal/create-account.md` at version `1.0` and status `approved`.
- Raw source SHA-256: `4750108963a9f2ce3f8b2611936679d1da5dc92b2061c8444de0dbceb2e3d9d4`.
- Hazel-KB snapshot: `04c6d1adc9d224d3cf6bfc68115b2b5cd44c44ed`; source tracked and unchanged at that commit: `yes`.
- Relevant approved decisions: `DEC-006`, `DEC-020`, `DEC-025`, `DEC-031`, `DEC-036`, `DEC-047`, `DEC-066`.
- Relevant open questions: `Q-008`, `Q-016`, `Q-026`, `Q-027`.
- React snapshot: `main` at `88df7b28ac43793cbf5ae49a7529acf317905fc0`; worktree dirty: `no`.
- The feature registry supplies repository/path mapping and inspection probes; product requirements come from the source spec.

## 2. Objective

Implement Scope A frontend prototype-parity UI for Create Account in `apps/member-portal` at the temporary UI/review route `/create-account`, following the current prototype for layout, supplied copy, fields, styling, validation presentation, and interaction appearance, with one explicit React-only override: omit the visible `Sign in` button. Production invitation, registration, authentication, and integration behavior remain out of scope.

## 3. Current implementation state

- Configured application: `apps/member-portal`.
- Routes currently discovered in that source tree: `*`, `/case/:caseId/*`, `/submit-interest`, `documents`, `due-diligence`, `institution-profile`, `nda`, `overview`, `review`, `risk-questions`.
- No Create Account route or `CreateAccountPage` component exists in the inspected source.
- Route configuration and case context/state: `apps/member-portal/src/App.jsx`; authenticated case navigation shell: `apps/member-portal/src/components/AppShell.jsx`.
- Related page: `apps/member-portal/src/pages/SubmitInterestPage.jsx`; reusable control: `apps/member-portal/src/components/Button.jsx`.
- Localization setup/files: `apps/member-portal/src/i18n.js` and `apps/member-portal/src/locales/en/public.json`.
- Relevant styles: `apps/member-portal/src/styles/global.css`; API calls: `apps/member-portal/src/services/api.js`.
- Existing relevant test convention: `apps/member-portal/src/components/risk/riskQuestionState.test.js`.
- Shared packages discovered: `packages/.gitkeep`.
- The member app already loads the `public` i18n namespace and contains centered auth-card/form styling used by Submit Interest.
- No account/authentication/registration service export was found in `apps/member-portal/src/services/api.js`.
- The existing test uses Node's built-in `node:test`; the package declares no `test` script or browser/component-test harness.
- Registry baseline `Current member routes`: The member application currently exposes case routes but no Create Account route. Evidence: `apps/member-portal/src/App.jsx`.
- Registry baseline `Current public routes`: The standalone public application currently exposes only Submit Interest. Evidence: `apps/public-web/src/App.jsx`.
- Registry baseline `Authentication integration state`: The BFF documents External ID session resolution as unimplemented; authenticated routes must not fall back to an anonymous session. Evidence: `apps/bff/proxy.py`.

## 4. Target application

Human-approved ownership is `apps/member-portal` for `frontend-prototype-parity`. The approved Scope A route is `/create-account`, classified as a temporary UI/review route only. It does not establish the final production invitation, registration, or authentication URL. `apps/public-web` remains outside the allowed change surface and unchanged.

## 5. Implementation gaps

- **Missing page/component:** no Create Account route, page, or feature state module exists.
- **Layout:** the generic auth-card foundation exists, but the approved Create Account composition is absent.
- **Content/i18n:** the `public` namespace exists, but it contains no Create Account keys or approved feature copy.
- **Visual styling:** shared tokens/form styles exist; feature-scoped password checklist, visibility-control, and validation presentation are absent.
- **Navigation:** use the approved temporary Scope A route `/create-account` and intentionally exclude the visible Sign in action; final invitation, registration, authentication, and post-submit routing remain outside Scope A.
- **State handling:** no password-visibility, password-rule, mismatch, validation-summary, or submitting UI state exists for this feature.
- **Accessibility:** there is no rendered feature to provide labels, described-by links, error-summary focus, keyboard flow, or disabled-state semantics.
- **Integration dependency:** Microsoft External ID registration/session/error contracts are not implemented or specified in the current React/BFF surface.

Probe-level evidence:

- **Page title: absent** — Show the page title exactly as ‘Create your Hazel account’.
- **Explanatory text: absent** — Show the prototype explanatory sentence directly below the title.
- **Create password field: absent** — Provide a required Create password field with a Show control and new-password autocomplete semantics.
- **Confirm password field: absent** — Provide a required Confirm password field with a Show control.
- **Password rules: absent** — Display the prototype password checklist: at least 12 characters, one uppercase letter, one lowercase letter, one number, and one symbol.
- **Primary action: absent** — Show Create account as the primary action.
- **Secondary action: intentionally excluded by approved React override** — [HUMAN-APPROVED REACT OVERRIDE] Preserve this as prototype evidence but do not render the visible Sign in button in React.
- **Submitting state: absent** — Disable the actions while submission is in progress and change the primary label to ‘Creating account…’.
- **Validation summary: absent** — Present an accessible error summary and field errors for missing, noncompliant, or nonmatching passwords.
- **Page layout: absent** — Use the prototype's centered white authentication card on its soft mint-to-warm gradient background, excluding prototype-review controls.

## 6. Allowed change surface

Only the following registry-declared candidates are in scope. Presence here is not permission to resolve a blocker silently:

- `apps/member-portal/src/App.jsx`
- `apps/member-portal/src/pages/CreateAccountPage.jsx`
- `apps/member-portal/src/pages/createAccountState.js`
- `apps/member-portal/src/pages/createAccountState.test.js`
- `apps/member-portal/src/locales/en/public.json`
- `apps/member-portal/src/styles/global.css`

All other paths require the implementation spec to be amended and re-reviewed.

## 7. Forbidden change surface

No implementation generated from this spec may change:

- `apps/api/**`
- `apps/bff/**`
- `apps/api/migrations/**`
- `apps/api/app/schemas/**`
- `apps/member-portal/src/services/api.js`
- `apps/public-web/**`
- `app.yaml`

In particular: do not add Hazel-owned credential storage, an authentication API, migrations, identity-provider configuration, invitation-token semantics, or Databricks workflow changes.

## 8. Functional behavior to preserve

The following files and their behavior are explicit regression boundaries:

- `apps/member-portal/src/pages/SubmitInterestPage.jsx`
- `apps/member-portal/src/services/api.js`
- `apps/public-web/src/App.jsx`
- `apps/public-web/src/pages/SubmitInterestPage.jsx`

Preserve the existing public inquiry API handoff, member case routes and guards, `CaseContext`/onboarding state, BFF forwarding boundary, and Microsoft External ID ownership. Do not introduce prototype timers, localStorage state, synthetic credentials, or review controls. See the source spec's **Functional boundaries** section for the normative wording.

## 9. UX/UI implementation requirements

- Add `CreateAccountPage` at the registry-declared page path in the confirmed owning application.
- Wire `/create-account` in `apps/member-portal/src/App.jsx` as the approved temporary Scope A UI/review route; do not describe it as the final production URL and do not invent invitation-token, authentication-submit, or post-submit navigation behavior.
- Keep the page outside `CaseApp` unless a later decision explicitly makes account creation part of case-authenticated routing.
- Do not duplicate the page in the public bundle; `apps/public-web` is explicitly preserved and forbidden.
- Do not render the prototype's visible `Sign in` action; this is a human-approved React-only override.

Implement page-local presentation state only: password visibility, client-side checklist/validation, matching confirmation, error-summary focus, and disabled/submitting presentation. Extract pure validation/state rules to the allowed `apps/member-portal/src/pages/createAccountState.js` module for deterministic tests.

Credential submission remains blocked until the Microsoft External ID contract exists. Do not simulate success, persist passwords, invent an API, or choose post-submit navigation. The source UX/UI requirements remain authoritative:

- [PROTOTYPE] Show the page title exactly as ‘Create your Hazel account’. (`versions/2026-08-17/index.html:1746`)
- [PROTOTYPE] Show the prototype explanatory sentence directly below the title. (`versions/2026-08-17/index.html:1747`)
- [PROTOTYPE] Provide a required Create password field with a Show control and new-password autocomplete semantics. (`versions/2026-08-17/index.html:1750`)
- [PROTOTYPE] Provide a required Confirm password field with a Show control. (`versions/2026-08-17/index.html:1752`)
- [PROTOTYPE] Display the prototype password checklist: at least 12 characters, one uppercase letter, one lowercase letter, one number, and one symbol. (`versions/2026-08-17/index.html:1751`)
- [PROTOTYPE] Show Create account as the primary action. (`versions/2026-08-17/index.html:1753`)
- [HUMAN-APPROVED REACT OVERRIDE] Do not render the prototype's visible `Sign in` button in React. Preserve the unchanged prototype evidence at `versions/2026-08-17/index.html:1753`; this override is not prototype-derived.
- [PROTOTYPE] Disable the actions while submission is in progress and change the primary label to ‘Creating account…’. (`versions/2026-08-17/index.html:1753`)
- [PROTOTYPE] Present an accessible error summary and field errors for missing, noncompliant, or nonmatching passwords. (`versions/2026-08-17/index.html:1882` (+1 more))
- [PROTOTYPE] Use the prototype's centered white authentication card on its soft mint-to-warm gradient background, excluding prototype-review controls. (`versions/2026-08-17/index.html:1746`)

## 10. i18n and copy changes

Add a `createAccount` object under the already-loaded `public` namespace in `apps/member-portal/src/locales/en/public.json`. Proposed keys are derived from registry probes; keys marked TBD must remain without invented copy until product review supplies it.

- `public:createAccount.title` — `Create your Hazel account`
- `public:createAccount.description` — `Create a password to securely access the Hazel Network.`
- `public:createAccount.fields.password.label` — `Create password`
- `public:createAccount.fields.confirmPassword.label` — `Confirm password`
- `public:createAccount.requirements.minLength` — `At least 12 characters`
- `public:createAccount.actions.create` — `Create account`
- `public:createAccount.actions.creating` — `Creating account…`
- `public:createAccount.validation.summary` — `Create a password that meets every requirement.`
- `public:createAccount.requirements.<remaining-rule>` — exact key suffixes/copy TBD unless present in the approved source
- `public:createAccount.validation.<field-error>` — exact key suffixes/copy TBD

Keep JSX free of new user-facing hard-coded strings. The source spec's **Copy and content expectations** section remains authoritative; do not copy unrelated product-spec content into this engineering document.

## 11. Shared component guidance

- Reuse `apps/member-portal/src/components/Button.jsx` without modifying it; it already supports primary/secondary variants and disabled state.
- Reuse the existing `.auth`, `.auth-card`, `.input`, `.field`, `.actions`, focus, and responsive conventions; add only feature-scoped selectors when necessary.
- Keep password visibility and validation helpers page-local unless another approved feature demonstrates genuine reuse.
- Do not introduce a new design system, form library, state library, or shared package for this feature.

## 12. Authentication boundary

The prototype is a visual/content reference and shows local password-entry controls. The approved product boundary assigns production identity to Microsoft External ID. The React implementation may build inert, client-side visual parity and validation within the approved Scope A application; it may not store credentials, authenticate locally, add a registration API, configure Entra, or simulate a successful production handoff.

Actual submit behavior, invitation binding, External ID errors/redirects/session establishment, final production routing, and post-submit navigation remain outside Scope A. `/create-account` is temporary and may change when Microsoft External ID or invitation-token integration is implemented. The visible Sign in control is intentionally excluded from React. Scope A must not present a fake production success path.

## 13. Acceptance criteria

Required focused checks:

- [ ] Pure validation tests cover empty, too-short, missing character classes, valid passwords, and mismatch.
- [ ] Tests cover visibility state and prevention of duplicate submits without asserting an invented backend success path.
- [ ] Manual/browser review covers keyboard order, visible focus, accessible labels/descriptions, error-summary focus/links, disabled state, responsive layout, the Create account control, and confirmed absence of visible Sign in.
- [ ] Regression review confirms Submit Interest and existing case routes are unchanged.

There is no declared component/browser test command. Adding tooling is outside this feature's current allowed surface and remains a reviewer decision.

Engineering completion additionally requires:

- [ ] The approved prototype-parity layout and copy render responsively without redesign.
- [ ] All supplied visible copy is represented through i18n and all unsupplied copy remains explicitly TBD.
- [ ] Keyboard order, visible focus, semantic labels, password-field descriptions, error-summary focus/links, and disabled states meet the repository's accessibility baseline.
- [ ] Existing public inquiry and member case routes remain valid and behaviorally unchanged.
- [ ] `/create-account` renders the Scope A page in `apps/member-portal` and is documented only as a temporary UI/review route, not a final production authentication URL.
- [ ] No backend, BFF, API schema, migration, persistence, RAFA, Databricks, authentication-architecture, or Entra-configuration change is present.
- [ ] The relevant build, all existing tests, the new pure-state tests, and `git diff --check` pass.

These criteria implement, but do not replace or duplicate, the source spec's **Acceptance criteria** section.

## 14. Verification commands

Run from the React repository root, in this order:

1. `node --test apps/member-portal/src/components/risk/riskQuestionState.test.js apps/member-portal/src/pages/createAccountState.test.js`
2. `npm --workspace apps/member-portal run build`
3. `git diff --check`

No package-level `test` or component/browser test command is declared, so this spec does not invent one. Existing Node tests can be run explicitly with `node --test` when doing the full regression pass.

## 15. Remaining out-of-scope dependencies

There are no unresolved blockers to Scope A frontend implementation.

- The final production invitation, registration, and authentication route remains unresolved; `/create-account` is temporary and may change with Microsoft External ID or invitation-token integration.
- Microsoft External ID registration, errors, redirects, and session contracts remain outside Scope A; visible local-password UX is not authority for Hazel-owned credentials.
- Post-account-creation behavior remains unresolved and outside Scope A; no Sign in destination is needed because the visible control is excluded.
- No React component/browser test harness is declared. The approved Scope A verification approach is the existing Node tests, build, manual accessibility review, and `git diff --check` defined above.
- Registered questions `Q-008`, `Q-016`, `Q-026`, and `Q-027` remain open outside Scope A.
- The KB corpus limitations, identity subdomain/tenant ownership, and authority-to-act/institution binding remain outside Scope A.

## 16. Human developer review approval

- [x] Confirmed the source product spec is approved, committed, and represented by the recorded SHA-256.
- [x] Confirmed `apps/member-portal` ownership and the `frontend-prototype-parity` Scope A boundary.
- [x] Approved `/create-account` as a temporary UI/review route only; final production invitation, registration, and authentication routing remains out of Scope A.
- [x] Confirmed the implementation remains visual/client-validation only and does not invent invitation, External ID, credential, success, or post-submit behavior.
- [x] Confirmed the visible Sign in control and its i18n key must be absent as required by the approved React-specific override.
- [x] Confirmed the allowed and forbidden change surfaces remain unchanged.
- [x] Confirmed validation behavior and supplied copy against the approved product spec.
- [x] Approved existing Node tests plus build/manual accessibility review; no new component/browser test tooling is authorized.
- [x] Approved this implementation specification for Scope A code implementation through direct human review.

## Approval history

| Date | Version | Status | Approved by | Change |
|---|---|---|---|---|
| 2026-08-20 | 1.0 | Approved | Requester (human approval in this task) | Approved Scope A implementation at temporary `/create-account`; retained final production routing and all authentication/integration behavior outside scope. |
