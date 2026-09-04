# Security Policy

`transcribe` handles private audio and video. Processing stays local: there is
no hidden cloud upload. Network access is limited to the initial FluidAudio
model cache and `yt-dlp` for YouTube sources.

## Reporting

Use GitHub's private vulnerability reporting (repository **Security** tab →
**Report a vulnerability**). If unavailable, open a public issue requesting a
private channel without details, logs, media, or transcripts.

Include the version, exact invocation, observed and expected behavior, and the
smallest synthetic reproduction available. Never include recordings,
transcripts, personal data, identifying paths/titles, model caches, or raw
engine JSON.

## Scope

Report issues that could:

- exfiltrate media, transcripts, or model data;
- execute commands through crafted source names, titles, or metadata;
- write outside the requested output directory or bypass local-only behavior;
- hide failures or leave misleading standard artifacts.

The tool passes subprocess arguments as controlled argv and constrains output
to the requested directory. Vulnerabilities in `yt-dlp`, FluidAudio, Parakeet,
or macOS itself belong upstream.
