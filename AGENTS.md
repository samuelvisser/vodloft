# AI agent and contributor guidance

## Git usage
When I ask you to implement a new feature, please follow these guidelines:
- Create a new branch from develop. If your are an OpenAI product create it inside
codex/, if you are a Anthropic product, place it inside claude/. If you are anything
else, use a relevant name to identify yourself within git.
- If I ask you to do follow-up work on that same feature, please continue to use the
same branch. Only base a new branch on develop again if you are implementing a new feature.
- When you are done, please squash your commits into a single commit and push to your branch.
- Only squash within a single request. After you are done with a commit, I add context or ask 
for another change, this should be its own new commit.

### OpenAI GitHub connector
If you are an OpenAI product, it is important to know the GitHub connector you use often stalls
for long sessions. It just stops responding, causing your work to stall as well.
To work around this, I found it is often better to create and push small commits through the connector 
while you are working, and only when done at the end squash all commits into a single commit.  

If the GitHub connector still stalls, please try to sleep for a little and then try again instead
of stalling the entire session.

## Migrations
VODLoft knows about two separate migration paths, each to serve a separate need:
- Database migrations
- Background migrations

Database migrations should be used strictly to change the database schema. It can move local data
around if needed, but it can never use external resources such as API calls or the filesystem.
Database migrations are expected to finish relatively quickly due to their local- only nature.
They run before VODLoft starts anything else.

Background migrations run in the background while VODLoft is running. They can use external resources
such as API calls or the filesystem if needed. They are designed specifically for migrations that are
expected to take longer and therefore do not interrupt the VODLoft startup process.
Background migrations do, however, pause all scheduled work while they are running.

### Initial database seed
Data that every brand-new VODLoft installation should start with belongs in
`server/backend/src/backend/db/initial_seed.py`. The initial seed runs only after a fresh database has
been migrated to the current schema. Add new first-install defaults there instead of putting them in
Alembic migrations. Database migrations may still transform or backfill data when an existing
installation needs a change to remain valid after a schema/application update.

Development/demo fixture data is separate and remains under `backend.db.fake_data` / `backend-api db seed`.

### Database migrations
If you need to do any database migrations to implement a feature, please follow these guidelines:
- Create a new alembic migration script in server/backend/src/backend/db/alembic/versions/
- Run `backend-api db history` to verify the new migration is the current head, and no multiple
migration heads exist.

### Background migrations
If you need to do any API/ filesystem or any other long- running migration work to implement a feature
or fix faulty data caused by a historical bug, please follow these guidelines:
- Create a new background migration script in server/backend/src/backend/db/background_migrations/versions/.
- Name it `<revision>_<description>.py`, using an opaque 12-character lowercase hexadecimal revision
  like Alembic. The description belongs only in the filename suffix/title; never encode migration
  semantics in the revision itself.
- Declare `revision` and `down_revision` in the migration module, just like Alembic.
- When consolidating prerelease background migrations for a release, keep the revision of the latest
  migration being replaced so development/test databases that already reached it remain current.
- Run `backend-api background-migrations history` to verify the new migration is the current head, and no multiple
migration heads exist.

### Legacy stored values
VODLoft is still in an early stage and application code should not contain compatibility handling
for legacy persisted values. If a change renames or otherwise changes the representation of a stored
configuration value, key, enum/string value, profile option, or other persisted database value, add
a data migration that rewrites existing stored data to the new canonical representation.

After that migration, frontend and backend application code must only know about the current canonical
values. Do not add aliases, legacy-value normalization, fallback branches, dual-read/dual-write logic,
or other runtime handling whose only purpose is to support values used by an older VODLoft version.
Legacy identifiers may appear in the migration file itself and in migration-specific tests or
fixtures needed to verify that migration, but not in normal application code. Treat legacy data
compatibility as a one-time migration concern rather than a permanent application-code concern.

## API model boundaries
VODLoft uses Pydantic as the API mapping and serialization boundary. Keep that boundary declarative:
- Prefer `model_validate()`, `from_attributes`, field aliases/`AliasPath`, discriminated unions, and small typed
  source envelopes over manually building dictionaries that mirror response models.
- Services should compute business facts and select data sources, but must not manually serialize enums/datetimes,
  duplicate response defaults, or validate -> dump -> rebuild another response model.
- Do not move a hand-written serializer into a Pydantic validator. Validators should express actual validation or
  small semantic derivations; straightforward source mapping belongs in Pydantic field aliases.
- Task manager and other lower-level packages must not import `backend.api.models`, `backend.api.endpoints`, or
  other API-layer modules. Shared application/domain behavior belongs below `backend.api` so both workers and
  endpoints can call it.
- API request models describe HTTP input. Do not reuse them as internal domain DTOs for Daily Wire records or worker
  data merely because the fields currently happen to overlap.

## Forms
VODLoft forms are configured within React Hook Form and Zod to ensure field validation in the frontend.
However, all backend API endpoints use Pydantic models to do their own validation. In most cases,
validation should always happen in both the frontend (user-friendly) and the backend for security.

To handle backend validation errors gracefully, VODLoft provides a ServerAwareSubmit helper that
makes sure backend validation errors still end up showing under fields that caused them, including a
fallback field as a 'catch all'. This goes not only for Pydantic validation errors, but also errors
thrown by the SQLAlchemy database layer. It even tries to map database field errors to the correct
RHF form fields.

Form default values, unless defined dynamically, should be defined through Zod defaults. Those should
then be picked up by React Hook Form and used as actual default values. Only deviate from this if the
default changes dynamically based on certain conditions.

Make sure to use this structure for any form adjustments and especially any new forms.

### React Select
Whenever you add a Select component anywhere, always use ReactSelect, or components using it like SimpleSelect. 
Enable search only if there are a lot of items. Keep most select components simple (SimpleSelect). 
Select options should always be build with a SelectRegistry.

## Wiki
When making big changes, you are allowed to update the VODLoft Wiki, too. 
However, keep in mind that the Wiki’s goal is user-facing: it should tell users things 
they might want to know for using VODLoft as a product. 
The wiki is not for documenting exact development implementations. 
It should also be easy to understand for a moderately tech-literate audience.

The wiki should document the big picture for VODLoft: code comments are for explaining 
programming implementation details.

## Sources
A Source is everything VODLoft knows about one service (The Daily Wire, later yt-dlp and NPO). Sources
live in the `sources` package (`server/sources`), one subpackage each, and register themselves in
`sources/__init__.py`.
- Application code reaches a service through the contract in `sources.contract` and the registry
  (`get_source(...)`), and checks a `Feature` rather than a Source id.
- Only the Daily Wire-only features listed in `tests/unit/test_source_boundaries.py` may import
  `sources.dailywire` directly. Do not add to that list; move code behind the contract instead.
- Add to the contract only what has a caller. A Source never imports the application, and the
  `downloader` package knows nothing about Sources.
- Collections and media items store their Source's id in `source_key`.

## Jinja analysis
Output template analysis lives in the `jinja_analysis` package (`server/jinja_analysis`), which only depends on
jinja2 and never imports VODLoft code; its tests use jinja2 and the package alone.
- Print expressions with `expression_source` and change templates with `TemplateEdits`, which edits only whole
  tags and verifies the result by parsing it again. Do not add another printer.
- What the analysis knows about a filter (pure, result type) lives in the one `FILTERS` table in
  `jinja_analysis.filters`.

## Importers
Importers live in the `importer` package (`server/importer`). An importer reads another program's data and returns
the neutral plans in `importer.contract`; it never imports VODLoft code (`test_ytdlp_template_conversion.py` checks
this), and the backend applies the plans.
- yt-dlp and Pinchflat templates go through `importer.ytdlp_templates`, which reports every part it could not
  convert exactly. Do not drop a part without a report entry.

## The Daily Wire
When referring to The Daily Wire, in most cases, use the full name, "The Daily Wire". 
However, in some contexts, it may read better to use "Daily Wire" instead. This is not the 'correct'
name though, so should only be used if "The Daily Wire" reads awkwardly in the sentence.

## Tests
You are allowed to create tests for your work. However, make sure to never add domain — level wiring
just to support tests. You can add test helpers, but those belong in the test files themselves.

Never add helpers or other domain-level functions just to support tests. Only use domain helpers
when they are necessary for the domain logic itself.

### Test your work
Before you push your branch, please run all appropriate tests to verify your work.  
Also be sure to launch both the backend and frontend servers and verify your work in the UI.
First, run `uv sync` and `npm install` from the repository root to install all dependencies.
The backend is started with: `backend-api run` and the frontend is started with `npm run dev` from the repository root.
If your environment is not able to run any of these tests, you can skip this step.

## Font Awesome pro and free icon versions
VODLoft uses Font Awesome for both its public Free icon packs and its paid kit. Access to the paid kit is not required for normal development, automated agents, CI, or public contributors.

Do not replace or remove an intended Pro icon merely because the paid kit is unavailable in your environment. Application code must reference icons through `ui/src/icons/faIcon.ts`; do not import Font Awesome icon packs directly or register icon families in feature code. The Vite compiler in `ui/scripts/font-awesome-compiler.mjs` scans those references, validates them, and bundles only the icon definitions VODLoft uses.

Keep both `faIcon()` arguments statically analyzable: use literal strings or conditional expressions whose branches are literal strings. When a Pro icon has no automatic Font Awesome Free equivalent, add a prefix-qualified mapping to `ui/src/icons/freeIconFallbacks.json`.

## Releasing a new version
Whenever we are about to release a new version, keep the following in mind.

### Release notes
Every release's notes end their **Upgrading** section with the step-by-step instructions that
`./release.py upgrade-steps --version X.Y.Z` prints (see RELEASING.md): a few lines that pin the release's own image
tag and link to the step-by-step guide in the wiki. Keep release notes short: write release-specific upgrade notes
above them, put longer explanations in the wiki, never replace them with a bare `docker compose pull`, and never point
an upgrade at `latest`.

### AGENT branches cleanup
All branches created by agents, for example `codex/*` branches, usually need a cleanup before a release.

When I ask you to clean them up, first up create a list of all the branches already merged into develop along with a command to delete those from origin.

Next, give me a list of branches who's functionality is available in develop, even if not its exact code. Give me a command to delete those too.

For the remaining branches, tell me what changed in them compared to develop, and how much they are ahead of and behind develop. I will then decide what to
do with those.

### Migration squashing
The Alembic history holds exactly one migration per VODLoft release, named
`<revision>_vodloft_<major>_<minor>_<patch>.py`. A patch release without schema changes has no migration of its own.
Between releases, new work adds ordinary migrations after the last release migration. When preparing a release,
always merge every Alembic migration added since the previous release into one, without asking: one big migration
from the previous VODLoft version into the next.

The merged migration keeps the revision id of the last migration it replaces, so testing environments that have been
upgrading through the smaller migrations know they are already up to date. Never change the revision id or the
`down_revision` of a migration that shipped in a release: installed databases store those ids. Add the new release
to `RELEASE_REVISIONS` in `tests/unit/test_db_migration.py`, which checks that the history is one migration per
release. Tests of data changes made by a replaced migration move to the merged one, starting from the previous
release's revision.

Background migrations stay separate and are not merged per release, unless I ask for it. If I ask you to prepare
for a new release and did not say anything about background migrations, ask me whether I want those merged too.
