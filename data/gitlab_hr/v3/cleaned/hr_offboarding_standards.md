> Source: GitLab Handbook — https://handbook.gitlab.com/handbook/people-group/offboarding/offboarding_standards/
> License: CC BY-SA 4.0 — https://creativecommons.org/licenses/by-sa/4.0/
> Changes: extracted policy body; HTML converted to Markdown; relative links resolved.

# GitLab Offboarding Standards

Offboarding process and steps on the backend

#### This is a Controlled Document

In line with GitLab’s regulatory obligations, changes to [controlled documents](https://handbook.gitlab.com/handbook/security/controlled-document-procedure/) must be approved or merged by a code owner. All contributions are welcome and encouraged.

 Visibility: Audit 

## Purpose

These standards specify requirements related to the offboarding of GitLab team members from all GitLab related computing resources and data assets so as to protect our customers, team members, contractors, company, and other partners from harm caused by both deliberate and inadvertent misuse. Our intention in publishing these standards is to outline information security standards intended to protect GitLab assets.

## Scope

These standards apply to all GitLab team-members, contractors, advisors, and contracted parties interacting with GitLab computing resources and accessing company or customer data.

## Roles & Responsibilities

| Role | Responsibility |
| --- | --- |
| GitLab Team Members | Responsible for following the requirements in this document |
| People Operations | Responsible for implementing and executing this document |
| People Operations (Code Owners) | Responsible for approving significant changes and exceptions to this document |

## Offboarding Procedure

### Notice of Offboarding

Once the termination process has been approved and completed in Workday either by the departing team member’s [Direct Manager](https://docs.google.com/document/d/1Fr1G1i1kssfADgDf3D6LbZHR8RZmWKZYDNV8AfduZ1c/edit) (Voluntary) or by [Team Member Relations](https://docs.google.com/document/d/1nMokz03AiUQtb0XV5zpD9CjaQKcX5Lu8p5ASZy3cJVA/edit) (Involuntary), on the team member’s Last Working Day, at the pre-determined time, the Offboarding Parent and Child Cases are created automatically in [Compass](https://handbook.gitlab.com/handbook/eta/corporate-it/compass/), if within a valid offboarding window for the specified day. All system owners receive an email notifying them of their Child Case so that access revocation can begin. In the instance of a Voluntary Termination, this process will follow the [resignation process](https://docs.google.com/document/d/1AVHHBKd6dtyn0DOl4_UydbdEhectLpH5aMh17r9Sg_4/edit) initiated by the team member directly in Workday.

In alignment with the needs of both People Operations and IT Operations, scheduled offboardings will be opened between 4:00 - 5:00pm of the **team members’ local timezone** in Slack Monday-Friday.

**Note:** In instances where team members require deprovisioning initiated outside of these times, team members or their manager should reach out to IT Operations to arrange an alternate time.

Should the effective date fall on a day which People Operations team is unable to support e.g. a Family and Friends Day or Global Holiday, People Operations Specialist will reach out to the People Business Partner to discuss alternate offboarding options.

### Offboarding Assignments

Per the People Operations Rotation, the Offboarding Parent Case will be assigned directly in Compass.

### Creating the Offboarding Case

Offboarding Parent and Child Cases are created [automatically](https://theloop.gitlab.com/site/4455aa7f-24d9-41f2-b940-467b54962e4d/page/0fa19bf4-fd6a-41b9-9316-c2dcf3add854) in Compass using the data that is populated by Workday. System owners (Deprovisioners) receive a Child Case indicating that the departing team member’s access should be revoked.

Many teams work to deprovision access including the IT Operations, this should be regarded as urgent and all tasks expected to be completed within 5 working days (Child Cases close automatically after 5 days), with the exception of [laptop returns](https://handbook.gitlab.com/handbook/eta/corporate-it/end-user-services/laptop-management/), which can take 2-4 weeks.

**Note:** If the team member is temporarily transitioning to a [contractor or consultant role](https://handbook.gitlab.com/handbook/finance/procurement/contingent-worker-policy/), please proceed with the full offboarding process and create a separate onboarding issue to grant only specific temporary access for what they would need to fulfill their contractual obligations.

#### Creating the Offboarding Case Manually

**Note:** the steps below reference a `/pops run offboarding` Slack command that generates a GitLab issue. This process predates the move to Compass for offboarding tracking and needs to be confirmed or updated by IT Operations/People Engineering - flagged separately, not yet corrected here.

In the event that the offboarding case is not automatically opened or an urgent case is needed to be opened, the People Operations member can open the offboarding issue manually, by following the steps below:

1. In Slack, go to your profile as if you were going to send a Slack message to yourself. Type the command `/pops run offboarding <EMPLOYEE_NUMBER>`.
2. You will be pinged in Slack once the offboarding issue is created, which usually takes 30 seconds or so. The ping will include a link to the offboarding issue and merge request removing from team page.
3. You will need to check the Department, GitLab Email Address and GitLab Handle within the issue are correct.

### Offboarding Tools

#### Google Workspace

IT Ops will follow the below steps to set up an auto-response that notifies the sender that the team member they are trying to reach is no longer with GitLab and who to contact.

1. Navigate to the Google admin portal and search for the email account.
2. Unsuspend the account, reset sign in cookies, reset password, do not email the password.
3. Move account into the Former Team Members Organizational Unit.
4. Use GAM to set a Out of Office Message on the account
5. Add the [appropriate template](https://gitlab.com/gitlab-com/people-group/people-operations/employment-templates/-/blob/main/email_templates/offboarding_rejection.md) per team member’s department under the `Customize rejection notice`

The Out of Office message will stay on the account for 90 days, afterwards ITOPs will follow up and archive the account in the G-Suite vault.

#### Slack

- Bots

IT Ops check if the team member has created any bots before disabling the account. Go to [Slack](https://gitlab.slack.com/apps/manage) or on your admin Slack profile click Menu » Configure Apps » Custom Integrations » Bots and search through the bots’ list for the team member. If a bot exists, please DM the manager to confirm if the bot should be removed.

#### Team Page

As per the [automation](https://theloop.gitlab.com/site/4455aa7f-24d9-41f2-b940-467b54962e4d/page/0fa19bf4-fd6a-41b9-9316-c2dcf3add854) in place, a merge request is automatically created to remove the team member from the team page. This will update the following:

- Removing the individual file from the data/team\_members/person directory
- Removing the picture used in the previous file
- Adjusting the reports\_to in case the offboarded team member had reports
- Removing the pet picture in case the team member had any
- Removing the pet page entry
- Update the CODEOWNERS file: change to the manager or remove if the manager is already a codeowner for that file

The People Operations Team member will need to complete:

- Remove the team members ReadMe
  - If the ReadMe is in a private project, request assistance from the IT Ops team to delete (you can tag them in the team page MR and private Slack channel)
- Check for hardcoded references
  - The People Operations team member handling the offboarding should check to see whether the offboarded team members name is listed on any other public Handbook pages. This can be done by doing a Google search for the team members name and “GitLab” - this should pull up results that reflect any association with the team members name and GitLab (including a ReadMe).

### Offboarding Compliance

The People Operations Team ensures all offboarding cases are opened within each week of the offboarding effective date (the last day worked).

All offboarding tasks by all Departments need to be completed within 5 days of the offboarding date. For systems that are more critical and time sensitive, these will be completed within the first 24 hours (example 1Password, Slack) by the relevant Departments. Information about application & system deprovisioners can be found on the [Tech Stack](https://techstack.gtlb.com).

To ensure a successful completion of the offboarding case, it is important that all tasks are checked off, whether the system/tool is applicable to the offboarding team member or not. Checking the box indicates one of the following:

- I have revoked team member access to this particular system/tool
- I have checked and this team member was not given access to this particular the system/tool

## Exceptions

Exceptions to this policy must be approved by the People Operations team.

## References

- [Information Security Parent Policy](https://handbook.gitlab.com/handbook/security/)
- [GitLab Offboarding](https://handbook.gitlab.com/handbook/people-group/offboarding/)
- [GitLab Offboarding FAQ](https://handbook.gitlab.com/handbook/people-group/offboarding/faq/)
- [Offboarding Automation Flow](https://theloop.gitlab.com/site/4455aa7f-24d9-41f2-b940-467b54962e4d/page/0fa19bf4-fd6a-41b9-9316-c2dcf3add854/)
