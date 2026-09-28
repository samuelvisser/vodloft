"""Source accounts and anonymous connection contexts."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.db import get_session
from backend.db.models.vodloft import SourceConnection, SourceReference
from backend.source_manager import secrets as secret_store
from backend.source_manager.gateway import SourceGateway

router = APIRouter(prefix="/vodloft", tags=["VodLoft Source connections"])


class ConnectionInput(BaseModel):
    source_id: str
    name: str = Field(min_length=1, max_length=120)
    settings: dict[str, str | int | float] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


def _serialize(connection: SourceConnection) -> dict:
    return {"id": connection.id, "source_id": connection.source_id,
            "name": connection.name, "has_secret": bool(connection.secret_references),
            "secret_fields": sorted(connection.secret_references or {}),
            "settings": connection.settings or {}, "enabled": connection.enabled}


def _validate_source(source_id: str):
    manifest = next((s for s in SourceGateway().manifests() if s.source_id == source_id), None)
    if not manifest:
        raise HTTPException(422, "Choose an installed Source")
    return manifest


def _configuration(data: ConnectionInput, *, existing: SourceConnection | None = None) -> tuple[dict, dict]:
    fields = {field.name: field for field in _validate_source(data.source_id).configuration_schema}
    if set(data.settings) - fields.keys() or set(data.secrets) - fields.keys():
        raise HTTPException(422, "Source connection contains an undeclared setting")
    if set(data.settings) & set(data.secrets):
        raise HTTPException(422, "Source setting has an invalid type")
    for key, value in data.settings.items():
        field = fields[key]
        if (field.kind in {"secret", "credential_file"} or
            field.kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))) or
            field.kind in {"text", "select"} and not isinstance(value, str) or
            field.kind == "select" and value not in field.options):
            raise HTTPException(422, f"Invalid Source setting: {key}")
    for key in data.secrets:
        field = fields[key]
        if field.kind not in {"secret", "credential_file"}:
            raise HTTPException(422, f"Invalid Source secret: {key}")
        if field.kind == "credential_file" and (len(data.secrets[key].encode()) > 1024 * 1024 or
                                                 "\x00" in data.secrets[key]):
            raise HTTPException(422, f"Credential file is too large or invalid: {key}")
    for key, field in fields.items():
        if not field.required:
            continue
        if field.kind not in {"secret", "credential_file"}:
            value = data.settings.get(key)
        else:
            value = data.secrets.get(key) or (
                (existing.secret_references or {}).get(key) if existing else None)
        if value is None or value == "":
            raise HTTPException(422, f"Required Source setting is missing: {key}")
    return data.settings, {key: value for key, value in data.secrets.items() if value}


@router.get("/sources/connections")
def connections():
    with get_session() as session:
        return [_serialize(connection) for connection in session.scalars(select(SourceConnection)).all()]


@router.post("/sources/connections", status_code=201)
def create_connection(data: ConnectionInput):
    settings, supplied_secrets = _configuration(data)
    with get_session() as session:
        connection = SourceConnection(source_id=data.source_id, name=data.name,
            settings=settings,
            secret_references={key: secret_store.save(value) for key, value in supplied_secrets.items()},
            enabled=data.enabled)
        session.add(connection)
        session.commit()
        return _serialize(connection)


@router.put("/sources/connections/{connection_id}")
def update_connection(connection_id: int, data: ConnectionInput):
    with get_session() as session:
        connection = session.get(SourceConnection, connection_id)
        if not connection or connection.source_id != data.source_id:
            raise HTTPException(404, "Source connection not found")
        settings, supplied_secrets = _configuration(data, existing=connection)
        connection.name, connection.enabled = data.name, data.enabled
        connection.settings = settings
        previous = dict(connection.secret_references or {})
        for key, value in supplied_secrets.items():
            previous[key] = secret_store.save(value, previous.get(key))
        connection.secret_references = previous
        session.commit()
        return _serialize(connection)


@router.delete("/sources/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: int):
    with get_session() as session:
        connection = session.get(SourceConnection, connection_id)
        if not connection:
            raise HTTPException(404, "Source connection not found")
        if session.scalar(select(SourceReference.id).where(SourceReference.connection_id == connection_id)):
            raise HTTPException(409, "This account is used by library references; disable it instead")
        references = list((connection.secret_references or {}).values())
        session.delete(connection)
        session.commit()
    for reference in references:
        secret_store.remove(reference)


def source_options(session, source_id: str, connection_id: int | None) -> dict:
    if connection_id is None:
        return {}
    connection = session.get(SourceConnection, connection_id)
    if not connection or not connection.enabled or connection.source_id != source_id:
        raise ValueError("The selected Source connection is unavailable")
    options = dict(connection.settings or {})
    options.update({key: secret_store.read(reference) for key, reference in
        (connection.secret_references or {}).items()})
    return options
