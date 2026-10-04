# Local Media Profiles

A Local Media Profile describes the file you want for a **Domain**, independently of which Source retrieves it. Create/edit profiles in **Management**. A profile may be prepared before any item from that website is imported.

Choose a name, Domain, applicable playable types, quality or audio-only output, enabled state, output template, and delivery targets. Representation controls include audio languages and fallback, subtitle languages, container, video/audio codec, chapters, artwork, and embedded metadata. The form rejects combinations such as video subtitles in an audio-only profile.

A provider may not supply every requested track or format. With strict language selection, the Source reports an unavailable representation rather than silently choosing another language. Fallback allows the Source's compatible alternative.

Use **Preview** to inspect the output path for an example of the selected Domain and media type. Templates start with `/downloads/`; the actual configured media root replaces that prefix. See [Output path validation](Output-Path-Validation.md).

Profiles with compatible representations can share an acquired canonical file while keeping separate presentation paths. Another Source/account or incompatible representation receives a separate artifact.

Editing a profile affects new jobs. Already queued jobs keep their frozen profile specification. Disabling pauses new work; deleting retires the profile and cancels its queued work while preserving files still demanded by other profiles, policies, or playback sessions.
