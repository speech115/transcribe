# Transcription backend quick reference

## OpenAI `gpt-4o-transcribe-diarize`
- Input formats: mp3, mp4, mpeg, mpga, m4a, wav, webm.
- Max file size: 25 MB per request.
- response_format options: text, json, diarized_json.
- For audio longer than ~30 seconds, pass chunking_strategy (use "auto" to split into chunks).
- Known speakers: up to 4 references via extra_body known_speaker_names + known_speaker_references (data URLs).
- Prompting is not supported for gpt-4o-transcribe-diarize.

## Deepgram `nova-3`
- Uses `POST /v1/listen` with raw audio bytes and `Authorization: Token ...`.
- Common options for this repo: `model=nova-3`, `smart_format=true`, `punctuate=true`.
- Use `diarize=true` and `utterances=true` when you need speaker-separated JSON.
- If language is unknown, use `detect_language=true`; otherwise pass `language=en` or `language=ru`.
