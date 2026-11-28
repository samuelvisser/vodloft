import threading

from fastapi import APIRouter, HTTPException, Query

from backend.api.models.source import (
    DownloadOptionsAPIRead, DownloadProfileDefaultsAPIRead, SiteOptionsAPIRead, YtdlpOptionLineAPIRead, YtdlpOptionsAPIRead, YtdlpOptionsAPIUpdate, YtdlpOptionsCheckAPIRequest,
    ApiKeyAPIUpdate, ApiKeyNoteAPIIn, ApiKeyNoteAPIRead, ApiStatusAPIRead, EpisodeTagAPIRead, PublishStatusLabelAPIRead, SourceProblemAPIRead, CookiesAPIUpdate, ProgramStatusAPIRead, ResolveAPIRequest, ResolvedLinkAPIRead, MediaLinksAPIRequest, MediaLinksAPIRead, SearchResultsAPIRead,
    CollectionDetailsAPIRead, SourceAPIRead, SourceSiteAPIRead, SourceSiteAPIUpdate, UpgradeChecksAPIRead,
    SiteAddAPIRequest, SiteAddedAPIRead, SiteChoiceAPIRead, SitesPickAPIRequest, SiteApiValuesAPIUpdate, SiteAuthenticationAPIRead,
    AccountValuesAPIUpdate, CodeSignInAPIRead,
)
from backend.app import db_session
from backend.api.steps import STEPS_RESPONSE, plan_lines, stream_steps
from progress_plan import PlanTracker
from sources import ApiKeyRejected, Feature, SignInCodeEnded, SignInRejected, Source, UnknownSourceError, get_source, source_site
from sources.ytdlp_options import check_ytdlp_options
from backend.services.site_cookies import (
    SiteAuthentication, SiteNotKnownError, list_site_authentication, pick_sites, remove_known_site, remove_site_api, remove_site_cookies,
    save_site_api, save_site_cookies, test_site_api, cancel_code_sign_in, finish_code_sign_in, sign_in_account, sign_out_account,
    start_code_sign_in,
)
from backend.services.errors import ServiceError
from backend.services.sites import SiteLinkError, add_site, episode_tags_named, media_links, site_choices, site_of_link
from backend.types.collection_contracts import collection_contract
from backend.types.collection_types import CollectionType
from backend.services.access_checks import access_changed
from backend.services.site_settings import download_profile_defaults, offered_settings, profile_seasons
from backend.services.source_options import save_ytdlp_source_options, ytdlp_source_options
from config.settings.site_settings import SiteSettingGroup

from .service import (
    LinkNotRecognisedError, SourceFeatureMissingError, UnknownSiteError, api_key_notes, get_api_status, put_off_api_key_note, get_program_status,
    list_source_problems, list_source_sites,
    link_preview, link_question, list_sources, lookup_show_details, sources_in_use, resolve_link, search_source, set_site_preference, source_with,
    update_source_program,
)
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, requires_any, signed_in
from backend.db.core import run_write_transaction


router = APIRouter(tags=["Sources"])


def _source(source_id: str, feature: Feature) -> Source:
    try:
        return source_with(source_id, feature)
    except SourceFeatureMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sources", dependencies=[signed_in()], response_model=list[SourceAPIRead])
def source_list():
    """List every Source with the Features it supports."""
    with db_session() as s:
        return list_sources(s)


@router.get("/sources/in-use", dependencies=[signed_in()], response_model=list[str])
def source_in_use_list():
    """The Sources the Library has media from, so the UI can leave out which Source an item comes from while there is one."""
    with db_session() as s:
        return sources_in_use(s)


@router.get("/sources/problems", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=list[SourceProblemAPIRead])
def source_problems():
    """What the user should fix about any Source, such as an API key that stopped working."""
    return list_source_problems()


@router.get("/sources/api-key-notes", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=list[ApiKeyNoteAPIRead])
def get_api_key_notes():
    """The Sites whose API key would speed up collections or creators in the Library while there is none, for the note
    on Home that asks for one."""
    with db_session() as s:
        return api_key_notes(s)


@router.post("/sources/api-key-notes", dependencies=[requires(Area.SOURCES, Level.MANAGE)], status_code=204)
def put_off_api_key_notes(body: ApiKeyNoteAPIIn):
    """Remind me later, or never show the note on Home that asks for an API key again."""
    run_write_transaction(lambda s: put_off_api_key_note(s, body.action), concurrent=True)


@router.get("/sources/sites", dependencies=[signed_in()], response_model=list[SourceSiteAPIRead])
def source_sites():
    """Every Site a Source is made for, with the Sources that can handle its links."""
    with db_session() as s:
        return list_source_sites(s)


@router.get("/sources/site-choices", dependencies=[signed_in()], response_model=list[SiteChoiceAPIRead])
def source_site_choices():
    """The popular Sites VODLoft suggests, then every other Site it knows, each with whether it is added: what the
    user picks the Sites they use from, such as in onboarding."""
    with db_session() as s:
        return [SiteChoiceAPIRead.model_validate(choice, from_attributes=True) for choice in site_choices(s)]


@router.put("/sources/site-choices", status_code=204, dependencies=[requires_any((Area.SOURCES, Level.MANAGE), (Area.SETTINGS, Level.MANAGE))])
def pick_source_sites(body: SitesPickAPIRequest):
    """Make the picked Sites the ones VODLoft knows: add the suggested ones it does not know yet, and remove every
    other Site that has nothing in VODLoft. At least one Site is picked."""
    pick_sites(body.keys)


@router.post("/sources/sites", dependencies=[requires_any((Area.SOURCES, Level.MANAGE), (Area.SETTINGS, Level.MANAGE))], response_model=SiteAddedAPIRead)
def add_site_by_link(body: SiteAddAPIRequest):
    """Add the Site of a link before VODLoft has anything from it, so it gets its own settings and authentication."""
    with db_session() as s:
        try:
            site = site_of_link(s, body.url.strip())
        except SiteLinkError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return run_write_transaction(lambda s: SiteAddedAPIRead.model_validate(add_site(s, site)))


@router.delete("/sources/sites/{key}", status_code=204, dependencies=[requires_any((Area.SOURCES, Level.MANAGE), (Area.SETTINGS, Level.MANAGE))])
def remove_site_by_key(key: str):
    """Remove a Site that has nothing in VODLoft, such as one added by a link, with its cookies file."""
    try:
        remove_known_site(key)
    except SiteNotKnownError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.put("/sources/sites/{key}", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SourceSiteAPIRead)
def update_source_site(key: str, body: SourceSiteAPIUpdate):
    """Choose the Source to ask first for links on a Site."""
    def work(s):
        try:
            result = set_site_preference(s, key, body.preferred_source_key)
        except UnknownSiteError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result

    return run_write_transaction(work)


@router.post(
    "/resolve", dependencies=[requires_any((Area.ADD_MEDIA, Level.VIEW), (Area.QUICK_DOWNLOADS, Level.VIEW))],
    responses=STEPS_RESPONSE,
)
def resolve(body: ResolveAPIRequest, access: Access = signed_in()):
    """Find the Source that recognises a link, and what the link points to.

    Asking the Site takes a while, so the answer is sent as it goes, a line of JSON each: ``{"plan": ...}`` each time
    the plan of looking the link up changes, then ``{"link": ResolvedLinkAPIRead}`` or ``{"error": "..."}``. A link
    no Source the user may use handles is refused before anything is asked.
    """
    with db_session() as s:
        try:
            question = link_question(s, access, body.url, body.source_key)
        except LinkNotRecognisedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def look_up(send) -> dict:
        # A quick first look, such as YouTube's title and thumbnail, is sent beside the plan when it comes before the
        # full lookup is done; never after it, which ends the answer.
        lock = threading.Lock()
        done = False

        def first_look() -> None:
            preview = link_preview(question)
            with lock:
                if preview is not None and not done:
                    send(preview=preview.model_dump(mode="json", by_alias=True))

        threading.Thread(target=first_look, name="link-preview", daemon=True).start()
        plan = PlanTracker(sink=plan_lines(send))
        try:
            with db_session() as s:
                try:
                    link = resolve_link(s, access, question, plan)
                except LinkNotRecognisedError as exc:
                    return {"error": str(exc)}
            return {"link": link.model_dump(mode="json", by_alias=True)}
        finally:
            with lock:
                done = True

    return stream_steps(look_up, "Could not look up this link")


@router.post("/media-links", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=MediaLinksAPIRead)
def known_media_links(body: MediaLinksAPIRequest, access: Access = signed_in()):
    """Which links of a description are on a Site VODLoft knows for media, so the UI links only those to Add media."""
    with db_session() as s:
        return MediaLinksAPIRead(urls=media_links(s, access, body.urls))


@router.get("/sources/{source_id}/episode-tags", dependencies=[requires_any((Area.LIBRARY, Level.VIEW), (Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW))], response_model=list[EpisodeTagAPIRead])
def episode_tags(
    source_id: str, url: str | None = Query(default=None, max_length=2048), collection_type: CollectionType | None = None,
):
    """The tags a Source gives episodes, such as Video, Short and Livestream, for the collection at ``url`` or for any
    collection. With ``collection_type``, the main one is named as a collection of that type names its episodes."""
    try:
        source = get_source(source_id)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tags = source.episode_tags_for(url)
    if collection_type is not None:
        audio = source_site(url, source_id).audio_only if url else False
        tags = episode_tags_named(tags, collection_contract(collection_type).words_for(audio))
    return [EpisodeTagAPIRead.model_validate(tag) for tag in tags]


@router.get("/sources/{source_id}/publish-statuses", dependencies=[signed_in()], response_model=list[PublishStatusLabelAPIRead])
def publish_statuses(source_id: str):
    """What the Source calls each publish status, such as Scheduled or Published (still contains countdown)."""
    try:
        source = get_source(source_id)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [PublishStatusLabelAPIRead.model_validate(label) for label in source.publish_status_labels]


@router.get("/sources/{source_id}/site-options", dependencies=[requires_any((Area.LIBRARY, Level.VIEW), (Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.STREAM_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW))], response_model=SiteOptionsAPIRead)
def site_options(source_id: str, url: str = Query(min_length=1, max_length=2048)):
    """Choices only some sites of a Source offer, such as YouTube's auto-generated subtitles, for the collection at ``url``."""
    try:
        source = get_source(source_id)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    site = source_site(url, source.id)
    return SiteOptionsAPIRead(
        settings=offered_settings(site, SiteSettingGroup.DOWNLOAD_PROFILE),
        profile_defaults=DownloadProfileDefaultsAPIRead.model_validate(download_profile_defaults(site)),
        profile_seasons=profile_seasons(site, source),
        upgrade_checks=UpgradeChecksAPIRead.model_validate(site.upgrade_checks), site_key=site.key, site_name=site.name,
        stream_methods=site.stream_methods,
        stream_video_heights=site.stream_video_heights, stream_file_height=site.stream_file_height,
            stream_proxy_choice=site.stream_proxy_choice,
        video_output_help=site.video_output_help,
        downloads=DownloadOptionsAPIRead.model_validate(site.downloads),
    )


@router.post("/sources/ytdlp-options/check", dependencies=[requires_any((Area.SOURCES, Level.MANAGE), (Area.LIBRARY, Level.MANAGE))], response_model=list[YtdlpOptionLineAPIRead])
def ytdlp_options_check(body: YtdlpOptionsCheckAPIRequest):
    """Check your own yt-dlp options line by line with yt-dlp's parser, before they are saved."""
    return [YtdlpOptionLineAPIRead.model_validate(line) for line in check_ytdlp_options(body.text)]


@router.get("/sources/{source_id}/ytdlp-options", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=YtdlpOptionsAPIRead)
def ytdlp_options(source_id: str):
    """The yt-dlp options the Source gives every download."""
    _source(source_id, Feature.YTDLP_OPTIONS)
    with db_session() as s:
        return YtdlpOptionsAPIRead(text=ytdlp_source_options(s))


@router.put("/sources/{source_id}/ytdlp-options", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=YtdlpOptionsAPIRead)
def save_ytdlp_options(source_id: str, body: YtdlpOptionsAPIUpdate):
    _source(source_id, Feature.YTDLP_OPTIONS)
    def work(s):
        text = save_ytdlp_source_options(s, body.text)
        return YtdlpOptionsAPIRead(text=text)

    return run_write_transaction(work)


@router.get("/sources/{source_id}/collection", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=CollectionDetailsAPIRead)
def collection_details(source_id: str, url: str = Query(min_length=1, max_length=2048), access: Access = signed_in()):
    """Look up a collection to add, at a Source that lists its episodes."""
    return lookup_show_details(access, _source(source_id, Feature.EPISODE_LISTS), url)


@router.get("/sources/{source_id}/search", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=SearchResultsAPIRead)
def search(
    source_id: str, site: str = Query(min_length=1, max_length=100), q: str = Query(min_length=1, max_length=200),
    access: Access = signed_in(),
):
    """Find collections and videos by name on one of the Sites a Source searches."""
    try:
        return search_source(access, _source(source_id, Feature.SEARCH), site, q)
    except SourceFeatureMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sources/{source_id}/program", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ProgramStatusAPIRead)
def program_status(source_id: str):
    """The program a Source runs, such as yt-dlp, and when it was last updated."""
    return get_program_status(_source(source_id, Feature.PROGRAM_UPDATES))


@router.post("/sources/{source_id}/program/update", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ProgramStatusAPIRead)
def update_program(source_id: str):
    """Fetch the latest version of a Source's program now."""
    return update_source_program(_source(source_id, Feature.PROGRAM_UPDATES))


@router.get("/sources/authentication", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=list[SiteAuthenticationAPIRead])
def site_authentication():
    """Every Site VODLoft knows, with its sign-in, its cookies file and its API key."""
    with db_session() as s:
        return [SiteAuthenticationAPIRead.model_validate(listing) for listing in list_site_authentication(s)]


@router.put("/sources/authentication/{site_key}/cookies", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SiteAuthenticationAPIRead)
def save_site_cookie_file(site_key: str, body: CookiesAPIUpdate):
    """Store the Site's cookies of a cookies.txt file, which every Source uses for lookups and downloads on the Site."""
    with db_session() as s:
        try:
            listing = save_site_cookies(s, site_key, body.content.encode())
        except SiteNotKnownError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise _field_refused("content", exc) from exc
    _sign_in_changed(listing)
    return SiteAuthenticationAPIRead.model_validate(listing)


def _field_refused(field: str, exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=[{"loc": ["body", field], "msg": str(exc), "type": "value_error"}])


@router.delete("/sources/authentication/{site_key}/cookies", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SiteAuthenticationAPIRead)
def remove_site_cookie_file(site_key: str):
    with db_session() as s:
        try:
            listing = remove_site_cookies(s, site_key)
        except SiteNotKnownError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    _sign_in_changed(listing)
    return SiteAuthenticationAPIRead.model_validate(listing)


def _site_api_rejected(exc: ApiKeyRejected) -> HTTPException:
    """Under the value it is about, or under the form as a whole."""
    loc = ["body", "values", exc.field] if exc.field else ["body"]
    return HTTPException(status_code=422, detail=[{"loc": loc, "msg": str(exc), "type": "value_error"}])


@router.put("/sources/authentication/{site_key}/api", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SiteAuthenticationAPIRead)
def save_site_api_values(site_key: str, body: SiteApiValuesAPIUpdate):
    """Test the values of the Site's own API, such as Twitch's client ID and secret, and store them when the Site
    accepts them."""
    try:
        return SiteAuthenticationAPIRead.model_validate(save_site_api(site_key, body.values))
    except SiteNotKnownError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApiKeyRejected as exc:
        raise _site_api_rejected(exc) from exc


@router.post("/sources/authentication/{site_key}/api/test", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SiteAuthenticationAPIRead)
def test_site_api_values(site_key: str):
    try:
        return SiteAuthenticationAPIRead.model_validate(test_site_api(site_key))
    except SiteNotKnownError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApiKeyRejected as exc:
        raise _api_key_rejected(exc) from exc


@router.delete("/sources/authentication/{site_key}/api", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SiteAuthenticationAPIRead)
def remove_site_api_values(site_key: str):
    try:
        return SiteAuthenticationAPIRead.model_validate(remove_site_api(site_key))
    except SiteNotKnownError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _sign_in_rejected(exc: SignInRejected) -> HTTPException:
    """Under the value it is about, or under the form as a whole."""
    loc = ["body", "values", exc.field] if exc.field else ["body"]
    return HTTPException(status_code=422, detail=[{"loc": loc, "msg": str(exc), "type": "value_error"}])


@router.put("/sources/authentication/{site_key}/account", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SiteAuthenticationAPIRead)
def sign_in_with_account(site_key: str, body: AccountValuesAPIUpdate):
    """Sign in with the user's account on the Site, with what they filled in, such as an email address and password,
    and keep the sign-in for every lookup and download on the Site."""
    try:
        listing = sign_in_account(site_key, body.values)
    except SiteNotKnownError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SignInRejected as exc:
        raise _sign_in_rejected(exc) from exc
    _sign_in_changed(listing)
    return SiteAuthenticationAPIRead.model_validate(listing)


@router.post("/sources/authentication/{site_key}/account/code", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=CodeSignInAPIRead)
def start_sign_in_with_code(site_key: str):
    """Ask the Site for a code the user enters on its own page, such as twitch.tv/activate."""
    try:
        return CodeSignInAPIRead.model_validate(start_code_sign_in(site_key))
    except SiteNotKnownError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SignInRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sources/authentication/{site_key}/account/code/{flow_id}", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SiteAuthenticationAPIRead)
def finish_sign_in_with_code(site_key: str, flow_id: str):
    """Wait until the user entered the code, then keep the sign-in. Answers 410 when the code ran out, was turned
    down, or the sign-in was cancelled."""
    try:
        listing = finish_code_sign_in(site_key, flow_id)
    except SiteNotKnownError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SignInCodeEnded as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except SignInRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _sign_in_changed(listing)
    return SiteAuthenticationAPIRead.model_validate(listing)


@router.delete("/sources/authentication/{site_key}/account/code/{flow_id}", status_code=204, dependencies=[requires(Area.SOURCES, Level.MANAGE)])
def cancel_sign_in_with_code(site_key: str, flow_id: str):
    """Stop waiting for the code, such as when the user chose Cancel."""
    cancel_code_sign_in(site_key, flow_id)


@router.delete("/sources/authentication/{site_key}/account", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SiteAuthenticationAPIRead)
def sign_out_of_account(site_key: str):
    try:
        listing = sign_out_account(site_key)
    except SiteNotKnownError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _sign_in_changed(listing)
    return SiteAuthenticationAPIRead.model_validate(listing)


def _sign_in_changed(listing: SiteAuthentication) -> None:
    # The new sign-in may give videos VODLoft could not download before.
    for source_key in dict.fromkeys((*listing.cookie_source_keys, *filter(None, (listing.account_source_key,)))):
        access_changed(source_key)


def _api_key_rejected(exc: ApiKeyRejected) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": str(exc), "fixUrl": exc.fix_url})


@router.get("/sources/{source_id}/api", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ApiStatusAPIRead)
def api_status(source_id: str):
    """The Source's API key and how much of today's quota it spent."""
    source = _source(source_id, Feature.API_KEY)
    with db_session() as s:
        return get_api_status(s, source)


@router.put("/sources/{source_id}/api/key", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ApiStatusAPIRead)
def save_api_key(source_id: str, body: ApiKeyAPIUpdate):
    """Test an API key with one call, and store it when the service accepts it."""
    source = _source(source_id, Feature.API_KEY)
    try:
        source.save_api_key(body.key)
    except ApiKeyRejected as exc:
        raise _api_key_rejected(exc) from exc
    with db_session() as s:
        return get_api_status(s, source)


@router.post("/sources/{source_id}/api/key/test", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ApiStatusAPIRead)
def test_api_key(source_id: str):
    source = _source(source_id, Feature.API_KEY)
    try:
        source.test_api_key()
    except ApiKeyRejected as exc:
        raise _api_key_rejected(exc) from exc
    with db_session() as s:
        return get_api_status(s, source)


@router.delete("/sources/{source_id}/api/key", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ApiStatusAPIRead)
def remove_api_key(source_id: str):
    source = _source(source_id, Feature.API_KEY)
    source.remove_api_key()
    with db_session() as s:
        return get_api_status(s, source)
