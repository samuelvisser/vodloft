"""How VODLoft fetches Patreon: a creator's posts and collections from Patreon's own API, and each post through yt-dlp.

yt-dlp lists a creator's posts by their link alone and can't read Patreon's collections, which VODLoft calls
playlists. Patreon's API tells, for every post, its title, date, picture, kind and whether the signed-in account may
view it, and for every collection its posts in their order. So the implementation lists Patreon's pages itself, in
the shape of yt-dlp's flat listings, and only the posts the account may view are looked up with yt-dlp.

The API is asked through yt-dlp's own Patreon extractor, which gets past Patreon's bot check and sends the user's
Patreon cookies when there are any.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlsplit

from progress_plan import PlanTracker, StageSpec
from yt_dlp.utils import clean_html

from ... import ytdlp_runner as runner
from ...contract import LIST_TYPE, CreatorDetails, CreatorTier, SectionRef, Site
from .. import sites
from .other_sites import OtherSitesImplementation

logger = logging.getLogger(__name__)

_HOME = "https://www.patreon.com"
_HOSTS = frozenset({"patreon.com", "www.patreon.com"})
# Patreon's own pages, which are no creator's name.
_OWN_PAGES = frozenset({
    "api", "c", "cw", "m", "posts", "collection", "creation", "rss", "home", "search", "login", "signup", "settings",
    "messages", "notifications", "explore", "checkout", "join", "membership", "library", "file", "user", "bePatron",
})
_NAME = re.compile(r"^[\w.-]+$")
_POST = re.compile(r"/posts/(?:[^/]*-)?(\d+)/?$")
_COLLECTION = re.compile(r"^/collection/(\d+)/?$")
_ACCESS_INCLUDES = "access_rules.tier,campaign.rewards"
"""What tells which of the creator's tiers can view a post: its access rules, and the tiers of its creator."""
_ACCESS_FIELDS = {
    "fields[access_rule]": "access_rule_type,amount_cents,currency", "fields[reward]": "title,amount_cents,currency",
    "fields[campaign]": "name",
}
_POST_FIELDS = "title,post_type,published_at,current_user_can_view,teaser_text,thumbnail,image,url"
_PAGE_SIZE = 50
# Patreon's API gives some posts, such as embedded videos and links, a picture on its own media-u address, which
# answers with an error page to anyone who can't view the post.
_UNSERVED = "patreon.com/media-u/"
# The kinds of post Patreon has with a video or sound in them, such as video_embed, audio_file, livestream_youtube and
# podcast. Text, images, links and polls are left out.
_MEDIA_KINDS = ("video", "audio", "livestream", "podcast")


def _is_media(post_type: str) -> bool:
    """Whether a post of this kind has a video or sound in it; a post of no known kind might."""
    return not post_type or post_type.startswith(_MEDIA_KINDS)


def _parts(url: str) -> list[str]:
    return [part for part in urlsplit(url).path.split("/") if part]


def _picture(attributes: dict) -> str | None:
    """A post's or collection's picture, unless it is one Patreon only serves to those who can view the post."""
    for field, names in (("thumbnail", ("large", "default_large", "url", "original")), ("image", ("large_url", "url"))):
        found = attributes.get(field)
        if isinstance(found, dict):
            url = next((found[name] for name in names if isinstance(found.get(name), str) and found[name]), None)
            if url and _UNSERVED not in url:
                return url
    return None


def _count(value: object) -> int | None:
    """A number Patreon's API gives, which it sometimes gives as text."""
    return int(value) if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else None


def _timestamp(value: object) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).timestamp() if value else None
    except ValueError:
        return None


class _Included:
    """The records an API answer includes beside its posts, such as their access rules and the tiers those name."""

    def __init__(self, answer: dict) -> None:
        self._records = {
            (item.get("type"), str(item.get("id"))): item for item in answer.get("included") or [] if isinstance(item, dict)
        }

    def related(self, record: dict, name: str) -> list[dict]:
        data = ((record.get("relationships") or {}).get(name) or {}).get("data")
        found = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        return [self._records[key] for key in ((item.get("type"), str(item.get("id"))) for item in found) if key in self._records]


def post_access(site: Site, post: dict, included: _Included) -> str:
    """The key of the access a post the account may not view needs: the cheapest of the creator's tiers that unlocks
    it, or else any patron's."""
    found: dict[str, int] = {}
    campaign_tiers = [
        tier for campaign in included.related(post, "campaign") for tier in included.related(campaign, "rewards")
        if _paid(tier)
    ]
    for rule in included.related(post, "access_rules"):
        attributes = rule.get("attributes") or {}
        kind = attributes.get("access_rule_type")
        if kind == "tier":
            found |= {str(tier["id"]): _cents(tier) for tier in included.related(rule, "tier") if _paid(tier)}
        elif kind == "min_cents_pledged" and isinstance(cents := attributes.get("amount_cents"), int) and cents > 0:
            # A post for patrons who pledge at least an amount is for every tier that costs that much.
            enough = [tier for tier in campaign_tiers if _cents(tier) >= cents]
            if enough:
                cheapest = min(enough, key=_cents)
                found[str(cheapest["id"])] = _cents(cheapest)
    if site.creator_tiers is not None and found:
        return site.creator_tiers.key_of(min(found, key=lambda tier_id: found[tier_id]))
    return sites.MEMBERS_KEY


def _cents(tier: dict) -> int:
    cents = (tier.get("attributes") or {}).get("amount_cents")
    return cents if isinstance(cents, int) else 0


def _paid(tier: dict) -> bool:
    """A tier patrons pay for: not Patreon's own "Everyone", nor a creator's free tier."""
    return str(tier.get("id")) != "-1" and _cents(tier) > 0


_CURRENCY_SIGNS = {"usd": "$", "eur": "€", "gbp": "£", "cad": "CA$", "aud": "A$", "nzd": "NZ$"}


def _amount(cents: int, currency: str | None) -> str:
    """An amount as people write it, such as "$5", "€2.50" or "7 SEK"."""
    whole, part = divmod(cents, 100)
    number = f"{whole}" if part == 0 else f"{whole}.{part:02d}"
    code = (currency or "usd").lower()
    sign = _CURRENCY_SIGNS.get(code)
    return f"{sign}{number}" if sign else f"{number} {code.upper()}"


def creator_tier(tier: dict) -> CreatorTier:
    attributes = tier.get("attributes") or {}
    return CreatorTier(
        site_id=str(tier["id"]), name=str(attributes.get("title") or "").strip() or _amount(_cents(tier), attributes.get("currency")),
        amount=_amount(_cents(tier), attributes.get("currency")), rank=_cents(tier),
    )


class PatreonImplementation(OtherSitesImplementation):
    key = "patreon"
    list_keys = frozenset({LIST_TYPE})

    # The API

    @staticmethod
    def call(endpoint: str, query: dict[str, str]) -> dict:
        """Ask Patreon's API through yt-dlp's Patreon extractor, with the user's Patreon cookies."""
        from yt_dlp import YoutubeDL

        cookies = sites.cookies_for(_HOME)
        options = {"quiet": True, "no_warnings": True, **({"cookiefile": str(cookies)} if cookies else {})}
        try:
            with YoutubeDL(options) as ydl:
                extractor = ydl.get_info_extractor("PatreonCampaign")
                extractor.initialize()
                return extractor._call_api(endpoint, endpoint, query=query, note=False)
        except Exception as exc:
            raise runner.YtDlpError(f"Patreon's API did not answer: {exc}") from exc

    def _posts(self, campaign_id: str, *, collection_id: str | None = None, limit: int | None = None) -> tuple[list[dict], _Included]:
        """The campaign's posts, newest first, or a collection's: ``limit`` of them, else all."""
        posts: list[dict] = []
        included: dict = {"included": []}
        cursor = None
        while True:
            answer = self.call("posts", {
                "filter[campaign_id]": campaign_id, "filter[is_draft]": "false", "sort": "-published_at",
                **({"filter[collection_id]": collection_id} if collection_id else {}),
                "page[count]": str(min(limit or _PAGE_SIZE, _PAGE_SIZE)), "json-api-use-default-includes": "false",
                "fields[post]": _POST_FIELDS, "include": _ACCESS_INCLUDES, **_ACCESS_FIELDS,
                **({"page[cursor]": cursor} if cursor else {}),
            })
            posts += [post for post in answer.get("data") or [] if isinstance(post, dict) and post.get("id")]
            included["included"] += answer.get("included") or []
            cursor = (((answer.get("meta") or {}).get("pagination") or {}).get("cursors") or {}).get("next")
            if cursor is None or (limit is not None and len(posts) >= limit):
                return posts[:limit] if limit else posts, _Included(included)

    def _campaign(self, url: str) -> dict | None:
        """The campaign a creator's page is of, by the name in its link, or None when the link is no creator's page."""
        parts = _parts(url)
        if (urlsplit(url).hostname or "").lower() not in _HOSTS or not parts:
            return None
        if parts[0] in ("m",) and len(parts) >= 2 and parts[1].isdigit():
            campaign_id = parts[1]
        elif parts[0] == "api" and len(parts) >= 3 and parts[1] == "campaigns" and parts[2].isdigit():
            campaign_id = parts[2]
        else:
            name = self._name(url)
            if name is None:
                return None
            results = self.call("search", {"q": name, "page[size]": "5"}).get("data") or []
            campaign_id = next((
                str(result["id"]).removeprefix("campaign_") for result in results
                if result.get("type") == "campaign-document"
                and str((result.get("attributes") or {}).get("url") or "").lower().endswith(f"/{name.lower()}")
            ), None)
            if campaign_id is None:
                raise runner.YtDlpError(f"Patreon has no creator called {name}")
        answer = self.call(f"campaigns/{campaign_id}", {
            "json-api-use-default-includes": "false",
            "fields[campaign]": "name,summary,url,vanity,avatar_photo_url,cover_photo_url,patron_count",
        })
        return {"id": campaign_id, **((answer.get("data") or {}).get("attributes") or {})}

    def _name(self, url: str) -> str | None:
        """The creator's name in a link of their page, such as intothecast for patreon.com/c/intothecast/posts."""
        parts = _parts(url)
        if parts and parts[0] in ("c", "cw"):
            parts = parts[1:]
        if not parts or parts[0] in _OWN_PAGES or not _NAME.match(parts[0]) or parts[1:] not in ([], ["posts"]):
            return None
        return parts[0]

    # Listings

    def listing(self, url: str, limit: int | None = None) -> dict | None:
        """A creator's posts, newest first, or a playlist's in its order, with their video or sound only."""
        if (found := _COLLECTION.match(urlsplit(url).path)) and (urlsplit(url).hostname or "").lower() in _HOSTS:
            return self._playlist_listing(found.group(1), url, limit)
        campaign = self._campaign(url)
        if campaign is None:
            return None
        posts, included = self._posts(campaign["id"], limit=limit) if limit != 0 else ([], _Included({}))
        return {
            **self._channel_fields(campaign), "_type": "playlist", "id": campaign["id"], "title": campaign.get("name"),
            "description": _text(campaign.get("summary")), "webpage_url": self._root(campaign),
            "thumbnails": [{"url": campaign["avatar_photo_url"]}] if campaign.get("avatar_photo_url") else [],
            "entries": self._entries(posts, included, campaign),
        }

    def _collection(self, collection_id: str) -> tuple[dict, dict]:
        """A collection, and the campaign it is of."""
        answer = self.call(f"collection/{collection_id}", {
            "include": "campaign", "fields[collection]": "title,description,thumbnail,post_ids,post_sort_type",
            "fields[campaign]": "name,url,vanity,avatar_photo_url",
        })
        collection = (answer.get("data") or {}).get("attributes") or {}
        campaign_record = next((item for item in answer.get("included") or [] if item.get("type") == "campaign"), {})
        return collection, {"id": str(campaign_record.get("id") or ""), **(campaign_record.get("attributes") or {})}

    def _playlist_listing(self, collection_id: str, url: str, limit: int | None) -> dict:
        collection, campaign = self._collection(collection_id)
        if limit == 0:
            return self._playlist_info(collection_id, collection, campaign, [])
        posts, included = self._posts(campaign["id"], collection_id=collection_id)
        posts = self._in_playlist_order(posts, collection)
        entries = self._entries(posts, included, campaign)
        return self._playlist_info(collection_id, collection, campaign, entries[:limit] if limit else entries)

    def _playlist_info(self, collection_id: str, collection: dict, campaign: dict, entries: list[dict]) -> dict:
        return {
            **self._channel_fields(campaign), "_type": "playlist", "id": collection_id,
            "title": collection.get("title"), "description": _text(collection.get("description")),
            "webpage_url": f"{_HOME}/collection/{collection_id}",
            "thumbnails": [{"url": picture}] if (picture := _picture(collection)) else [],
            "entries": entries,
        }

    @staticmethod
    def _in_playlist_order(posts: list[dict], collection: dict) -> list[dict]:
        """A playlist's posts, the first first. Patreon keeps a playlist newest first, oldest first or in the
        creator's own order; an order of the creator's own that is just newest first counts as newest first."""
        dates = {str(post["id"]): (post.get("attributes") or {}).get("published_at") or "" for post in posts}
        by_date = sorted(posts, key=lambda post: dates[str(post["id"])])
        sort = collection.get("post_sort_type")
        if sort == "custom" and isinstance(collection.get("post_ids"), list):
            order = [str(post_id) for post_id in collection["post_ids"]]
            known = {post_id: post for post_id, post in ((str(post["id"]), post) for post in posts)}
            custom = [known[post_id] for post_id in order if post_id in known]
            custom += [post for post in by_date if str(post["id"]) not in order]
            listed = [dates[str(post["id"])] for post in custom]
            return custom if listed != sorted(listed, reverse=True) else by_date
        return by_date

    def _entries(self, posts: list[dict], included: _Included, campaign: dict) -> list[dict]:
        """The posts with a video or sound in them, as yt-dlp lists videos. A post the account may not view is
        complete, locked, so that it needs no lookup; any other one yt-dlp looks up."""
        entries = []
        for post in posts:
            attributes = post.get("attributes") or {}
            if not _is_media(str(attributes.get("post_type") or "")):
                continue
            post_url = attributes.get("url") or f"{_HOME}/posts/{post['id']}"
            entry = {
                **self._channel_fields(campaign), "_type": "url", "ie_key": "Patreon", "id": str(post["id"]),
                "url": post_url, "webpage_url": post_url, "title": attributes.get("title") or None,
                "description": _text(attributes.get("teaser_text")), "timestamp": _timestamp(attributes.get("published_at")),
                "thumbnail": _picture(attributes),
            }
            if attributes.get("current_user_can_view") is False:
                entry |= {"_access": post_access(self.site, post, included), "_access_refused": True}
            entries.append(entry)
        return entries

    def _channel_fields(self, campaign: dict) -> dict:
        root = self._root(campaign)
        return {"channel": campaign.get("name"), "uploader": campaign.get("name"), "channel_url": root, "uploader_url": root, "channel_id": campaign.get("id")}

    @staticmethod
    def _root(campaign: dict) -> str | None:
        return f"{_HOME}/{campaign['vanity']}" if campaign.get("vanity") else campaign.get("url") or None

    def refused_access(self, info: dict, key: str) -> str:
        """The cheapest of the creator's tiers that unlocks a post yt-dlp could not get, as Patreon's API tells it."""
        post_id = str(info.get("id") or "")
        if not post_id.isdigit():
            return key
        try:
            answer = self.call(f"posts/{post_id}", {
                "fields[post]": "current_user_can_view", "include": _ACCESS_INCLUDES, "json-api-use-default-includes": "false",
                **_ACCESS_FIELDS,
            })
        except runner.YtDlpError as exc:
            logger.info("Not telling what unlocks Patreon post %s: %s", post_id, exc)
            return key
        return post_access(self.site, answer.get("data") or {}, _Included(answer))

    def served_picture(self, url: str | None) -> str | None:
        return None if url and _UNSERVED in url else url

    def creator_tiers(self, url: str) -> tuple[CreatorTier, ...]:
        """The paid tiers of the creator of a page, a playlist or a post."""
        path = urlsplit(url).path
        if (urlsplit(url).hostname or "").lower() not in _HOSTS:
            return ()
        if found := _COLLECTION.match(path):
            campaign_id = self._collection(found.group(1))[1].get("id")
        elif found := _POST.search(path):
            answer = self.call(f"posts/{found.group(1)}", {
                "fields[post]": "title", "include": "campaign", "fields[campaign]": "name", "json-api-use-default-includes": "false",
            })
            campaign_id = next((item.get("id") for item in answer.get("included") or [] if item.get("type") == "campaign"), None)
        else:
            campaign_id = (self._campaign(url) or {}).get("id")
        if not campaign_id:
            return ()
        answer = self.call(f"campaigns/{campaign_id}", {
            "include": "rewards", "fields[campaign]": "name", "fields[reward]": "title,amount_cents,currency",
            "json-api-use-default-includes": "false",
        })
        tiers = [item for item in answer.get("included") or [] if item.get("type") == "reward" and _paid(item)]
        return tuple(creator_tier(tier) for tier in sorted(tiers, key=_cents))

    # Creators

    def creator_root(self, url: str) -> str | None:
        """The creator's page a link of theirs is on: their page or posts, or one of their playlists."""
        if (urlsplit(url).hostname or "").lower() not in _HOSTS:
            return None
        if found := _COLLECTION.match(urlsplit(url).path):
            return self._root(self._collection(found.group(1))[1])
        name = self._name(url)
        return f"{_HOME}/{name}" if name else None

    def is_creator_page(self, url: str) -> bool:
        return (urlsplit(url).hostname or "").lower() in _HOSTS and self._name(url) is not None

    def is_list(self, url: str) -> bool:
        return (urlsplit(url).hostname or "").lower() in _HOSTS and _COLLECTION.match(urlsplit(url).path) is not None

    def creator_details(self, ref: str, plan: PlanTracker) -> CreatorDetails:
        """A creator: their name and pictures, their posts and their playlists."""
        plan.add(
            StageSpec(id="page", code="read_page", label="Reading the creator's page"),
            StageSpec(id="playlists", code="read_lists", label=f"Reading the {self.site.section_list_names.plural}"),
        )
        with plan.running("page"):
            campaign = self._campaign(ref)
        if campaign is None:
            raise runner.YtDlpError("This link is not a Patreon creator")
        root = self._root(campaign) or ref
        with plan.running("playlists"):
            playlists = self._playlists(campaign["id"])
        feed = self.feed_types[0]
        name = campaign.get("vanity") or root.rsplit("/", 1)[-1]
        return CreatorDetails(
            ref=name, url=root, title=campaign.get("name") or name, handle=name, description=_text(campaign.get("summary")),
            avatar_url=campaign.get("avatar_photo_url") or None, banner_url=campaign.get("cover_photo_url") or None,
            sections=(SectionRef(ref=feed.path, url=f"{root}/{feed.path}", type=feed), *playlists),
        )

    def season_lists(self, url: str) -> list[SectionRef]:
        """The creator's playlists, newest first."""
        campaign = self._campaign(self.creator_root(url) or url)
        if campaign is None:
            raise runner.YtDlpError("This link is not a Patreon creator")
        return self._playlists(campaign["id"])

    def _playlists(self, campaign_id: str) -> list[SectionRef]:
        """The creator's collections, newest first, which VODLoft calls playlists. Only those with posts count."""
        answer = self.call("collection", {
            "filter[campaign_id]": campaign_id,
            "fields[collection]": "title,description,thumbnail,num_posts,created_at",
        })
        collections = [item for item in answer.get("data") or [] if isinstance(item, dict) and item.get("id")]
        collections.sort(key=lambda item: str((item.get("attributes") or {}).get("created_at") or ""), reverse=True)
        return [
            self.section(
                str(item["id"]), f"{_HOME}/collection/{item['id']}", LIST_TYPE,
                title=str(attributes.get("title") or "").strip() or f"Playlist {item['id']}",
                item_count=_count(attributes.get("num_posts")),
                image_url=_picture(attributes), description=_text(attributes.get("description")),
            )
            for item in collections
            if (attributes := item.get("attributes") or {}) and _count(attributes.get("num_posts")) != 0
        ]


def _text(html: str | None) -> str | None:
    """Patreon writes its descriptions in HTML; VODLoft shows them as text."""
    return clean_html(html).replace("\xa0", " ").strip() or None if html else None
