# Security Policy

`transcribe` processes **private audio**: calls, voice notes, interviews,
podcasts. A vulnerability here could expose the contents of recordings or
make media leave the machine — please report privately first.

## Supported versions

Only the latest released version on `main` is supported. Fixes ship as a new
release ([CHANGELOG.md](CHANGELOG.md)); there are no backports.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: the **Security** tab of this
repository → **Report a vulnerability**. That opens a private advisory
visible only to the maintainer.

If private reporting is unavailable to you, open a public issue that says
only that you have a security report and asks for a private channel — **no
details, no reproduction, no logs** in the public thread.

Please include, in the private report: the version (`git describe` or the
`version` field of `SKILL.md`), the exact invocation, what happens versus
what should happen, and the smallest reproduction you have. Expect a first
response within a few days; this is a single-maintainer project, not a
funded program.

## Never include in a report

Redact before sending, and never paste into a public issue or pull request:

- audio or video contents, transcripts, or excerpts of either;
- real names, phone numbers, or other personal data audible in a recording;
- paths or titles that identify a person or a private conversation
  (`~/Downloads/transcripts/<title>` names real sources);
- model cache material or raw engine JSON from `--keep-tmp` workdirs.

A synthetic reproduction on a generated test audio file is always preferred
over a real one.

## Scope

In scope — anything that lets a local process or a crafted input:

- exfiltrate media, transcripts, or model cache off the machine;
- bypass the local-only guarantee: upload audio or transcripts to a
  third party without the user's knowledge;
- write artifacts outside the requested output directory, or follow
  crafted source names/titles outside the out-root;
- crash the run without finalizing `progress.json` (a run must always end
  `done` or `error`, never hang silently);
- execute commands via crafted YouTube titles, file names, or media
  metadata (`yt-dlp` and `ffmpeg` arguments must stay quoted and
  controlled).

Out of scope:

- vulnerabilities in [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), the
  FluidAudio engine, or the NVIDIA Parakeet models — report upstream, and
  tell us so pins can move;
- macOS platform security: a user who can already read your home directory
  can read the artifacts the tool writes by design;
- YouTube access restrictions or rate limits imposed on `yt-dlp` by Google.

## Operational note

`transcribe` never runs in the background and never makes network calls of
its own. The only network activity in the whole tool is `yt-dlp` fetching
audio when the source is a YouTube URL. Media stays on the machine; the
artifacts it writes are world-`read`-by-your-user by default (normal file
permissions), so keep the output directories under a private path such as
`~/Downloads` rather than a shared volume.
