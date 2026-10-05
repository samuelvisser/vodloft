"""Source accounts and anonymous connection contexts."""

import json
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from source_contracts import AuthenticationResult

from backend.db import get_session
from backend.db.models.vodloft import SourceConnection, SourceReference
from backend.source_manager import secrets as secret_store
from backend.source_manager.gateway import SourceGateway
from backend.security.permissions import principal

from backend.source_manager.connections import (source_options, _authentication,
    _save_authentication, _validated_authentication)

router = APIRouter(prefix="/vodloft", tags=["VodLoft Source connections"])


class ConnectionInput(BaseModel):
    source_id: str
    name: str = Field(min_length=1, max_length=120)
    settings: dict[str, str | int | float] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    remove_secret_fields: list[str] = Field(default_factory=list)
    enabled: bool = True


def _serialize(connection: SourceConnection) -> dict:
    auth = _authentication(connection)
    return {"id": connection.id, "source_id": connection.source_id,
            "name": connection.name, "has_secret": bool(connection.secret_references) or auth.get("status") == "authorized",
            "authentication_status": auth.get("status"),
            "capabilities": connection.capabilities, "domain_capabilities": connection.domain_capabilities,
            "authenticated": connection.authenticated, "last_capability_check_at": connection.last_capability_check_at,
            "secret_fields": sorted(connection.secret_references or {}),
            "settings": connection.settings or {}, "enabled": connection.enabled}




def _public_authentication(value: dict) -> dict:
    return {"status": value.get("status", "expired"), "challenge": value.get("challenge"),
        "interval": value.get("interval", 5)}



@router.post("/sources/connections/{connection_id}/authenticate")
def start_authentication(connection_id: int):
    with get_session() as session:
        connection = session.get(SourceConnection, connection_id)
        if not connection or not connection.enabled:
            raise HTTPException(404, "Source connection not found")
        if "authentication" not in _validate_source(connection.source_id).capabilities:
            raise HTTPException(409, "This Source uses credential fields instead of interactive authentication")
        gateway = SourceGateway()
        try:
            result = _validated_authentication(connection.source_id,
                gateway.call(connection.source_id, "auth_start", timeout=35))
        except Exception as exc:
            raise HTTPException(502, "Could not start Source authentication") from exc
        result["_command"] = gateway.commands[connection.source_id]
        result["_next_poll"] = time.time() + result["interval"]
        _save_authentication(connection, result)
        session.commit()
        return _public_authentication(result)


@router.get("/sources/connections/{connection_id}/authentication")
def poll_authentication(connection_id: int):
    with get_session() as session:
        connection = session.get(SourceConnection, connection_id)
        if not connection or not connection.enabled:
            raise HTTPException(404, "Source connection not found")
        value = _authentication(connection)
        if value.get("status") != "pending" or time.time() < value.get("_next_poll", 0):
            return _public_authentication(value)
        if value.get("expires_at", 0) <= time.time():
            result = {"status": "expired"}
        else:
            try:
                gateway = SourceGateway({connection.source_id: value["_command"]})
                result = _validated_authentication(connection.source_id, gateway.call(
                    connection.source_id, "auth_poll", timeout=35, private_state=value["private_state"]))
            except Exception as exc:
                raise HTTPException(502, "Source authentication is temporarily unavailable") from exc
        result["_command"] = value.get("_command")
        result["_next_poll"] = time.time() + result.get("interval", 5)
        if result["status"] == "pending" and not result.get("challenge"):
            result["challenge"] = value.get("challenge")
        _save_authentication(connection, result)
        session.commit()
        return _public_authentication(result)


@router.delete("/sources/connections/{connection_id}/authentication", status_code=204)
def clear_authentication(connection_id: int):
    with get_session() as session:
        connection = session.get(SourceConnection, connection_id)
        if not connection:
            raise HTTPException(404, "Source connection not found")
        secret_store.remove(connection.authentication_reference)
        connection.authentication_reference = None
        connection.capabilities, connection.domain_capabilities = None, {}
        connection.authenticated, connection.last_capability_check_at = None, None
        session.commit()


def _validate_source(source_id: str):
    manifest = next((s for s in SourceGateway().manifests() if s.source_id == source_id), None)
    if not manifest:
        raise HTTPException(422, "Choose an installed Source")
    return manifest


def _configuration(data: ConnectionInput, *, existing: SourceConnection | None = None) -> tuple[dict, dict]:
    fields = {field.name: field for field in _validate_source(data.source_id).configuration_schema}
    if set(data.settings) - fields.keys() or set(data.secrets) - fields.keys():
        raise HTTPException(422, "Source connection contains an undeclared setting")
    if any(key not in fields or fields[key].kind not in {"secret", "credential_file"}
           for key in data.remove_secret_fields) or set(data.remove_secret_fields) & data.secrets.keys():
        raise HTTPException(422, "Choose distinct declared credential fields to remove")
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
                (existing.secret_references or {}).get(key) if existing and key not in data.remove_secret_fields else None)
        if value is None or value == "":
            raise HTTPException(422, f"Required Source setting is missing: {key}")
    return data.settings, {key: value for key, value in data.secrets.items() if value}


@router.get("/sources/connections")
def connections(request: Request):
    with get_session() as session:
        return [_serialize(connection) for connection in session.scalars(select(SourceConnection)).all()
                if principal(request).can_use_connection(connection.id)]


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
        connection.capabilities = None
        connection.domain_capabilities = {}
        connection.authenticated = None
        connection.last_capability_check_at = None
        connection.settings = settings
        previous = dict(connection.secret_references or {})
        removed = [previous.pop(key) for key in data.remove_secret_fields if key in previous]
        for key, value in supplied_secrets.items():
            previous[key] = secret_store.save(value, previous.get(key))
        connection.secret_references = previous
        session.commit()
        for reference in removed:
            secret_store.remove(reference)
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
        references.append(connection.authentication_reference)
        session.delete(connection)
        session.commit()
    for reference in references:
        secret_store.remove(reference)


