# Share meeting notes as Google Docs

**Date:** 2026-10-27
**Status:** Done — verified end-to-end 2026-10-27 (first share created folder + Doc; second share updated the same Doc in place)

## Goal

Colleagues should be able to read a meeting's notes properly formatted
(headings, bullet lists, the action-items table) instead of getting a raw
`notes.md` file. The chosen route is a Google Doc in my personal Google
Drive, created by `leus-notes` itself.

## How it is used

- Nothing is shared automatically. After a meeting, once I've read the notes,
  I run `leus-notes share [meeting]` (latest meeting by default) and that
  meeting's notes are uploaded as a Google Doc. The command prints the link.
- All Docs go into one Drive folder. I share that folder with my team once in
  Google Drive; every Doc the tool puts there is then visible to them without
  further steps.
- When the notes of a shared meeting change later (`leus-notes names`,
  `leus-notes process --notes`), the **same** Doc is updated: same link,
  colleagues see the new version.
- Running `share` again on an already shared meeting updates its Doc; it never
  creates a second one.
- A meeting I never share never leaves this machine.

## What goes into the Doc

- Only the notes. The transcript and the audio stay local.
- In the Doc I'm named **Lukas** instead of **Me**. (Changed the same day:
  `owner.name` now puts my name into the local notes and transcript too, so
  the Doc simply shows the notes as they are.)
- Doc title: meeting title and date, e.g. "New meeting – 2026-10-27".

## Google account

- My personal Gmail (`lukas.scharmitzer@gmail.com`) owns the folder and the
  Docs.
- One-time setup, guided step by step: allow the tool to sign in to Google,
  then log in once in the browser.
- The tool may only touch files it created itself — never the rest of my
  Drive.
- The login keeps working; no re-login every week.
- Login details stay inside the project folder, like everything else.

## Out of scope

- Sharing automatically for every meeting, or a `--share` flag on `start`.
- Sharing a Doc with individual email addresses per meeting.
- Uploading the transcript.
- The 2026-10-27 meeting's Doc was created by hand through Claude's Google
  connector; the tool can't see or update that file. Sharing that meeting with
  the tool creates a new Doc.

## Decisions taken during implementation

- "Me" becomes "Lukas" through one setting, `owner.name` (default "Lukas"),
  used everywhere instead of "Me" — transcript, notes and therefore the Doc.
  Claude is told that whoever mentions that name means the recorder. This
  replaced the first approach (swapping "Me" only at upload via
  `sharing.my_name`).
- Drive folder: **Meeting notes** (`sharing.folder`), created by the tool on
  the first `share`.
- Google unreachable or login expired while notes are rewritten: the local
  notes are still updated, the command reports that the Doc was not updated
  and how to retry (`leus-notes share <meeting>`), exit code 1.
