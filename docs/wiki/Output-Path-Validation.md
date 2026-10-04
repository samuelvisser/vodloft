# Output templates and path validation

The profile editor provides syntax highlighting, completion, field hints, and a preview using a real example from the selected Domain and media type.

Start a template with `/downloads/` and finish with `.ext`. VodLoft substitutes the resulting container's extension. For example:

```jinja
/downloads/{{ domain }}/{{ collection or media_type }}/{{ title }} - {{ id }}.ext
```

Available fields include `domain`, `title`, `id`, `upstream_id`, `media_type`, `collection`, `group`, `episode_number`, `published_date`, `author`, `duration`, and `movie_year`.

The preview and server validate the template's supported fields, syntax, sanitized result, and containment under the configured download root. Paths cannot escape that root or use VodLoft's reserved artifact/feed directories. Conflicting destinations are rejected rather than silently overwriting another representation.

A title edit can change future presentation paths. Existing jobs keep their frozen output specification.
