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
    access_token: str | None = None
    enabled: bool = True


def _serialize(connection: SourceConnection) -> dict:
    return {"id": connection.id, "source_id": connection.source_id,
            "name": connection.name, "has_secret": bool(connection.secret_reference),
            "enabled": connection.enabled}


def _validate_source(source_id: str):
    if source_id not in {s.source_id for s in SourceGateway().manifests()}:
        raise HTTPException(422, "Choose an installed Source")


@router.get("/sources/connections")
def connections():
    with get_session() as session:
        return [_serialize(connection) for connection in session.scalars(select(SourceConnection)).all()]


@router.post("/sources/connections", status_code=201)
def create_connection(data: ConnectionInput):
    _validate_source(data.source_id)
    with get_session() as session:
        reference = secret_store.save(data.access_token) if data.access_token else None
        connection = SourceConnection(source_id=data.source_id, name=data.name,
            secret_reference=reference, enabled=data.enabled)
        session.add(connection)
        session.commit()
        return _serialize(connection)


@router.put("/sources/connections/{connection_id}")
def update_connection(connection_id: int, data: ConnectionInput):
    _validate_source(data.source_id)
    with get_session() as session:
        connection = session.get(SourceConnection, connection_id)
        if not connection or connection.source_id != data.source_id:
            raise HTTPException(404, "Source connection not found")
        connection.name, connection.enabled = data.name, data.enabled
        if data.access_token:
            connection.secret_reference = secret_store.save(data.access_token, connection.secret_reference)
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
        reference = connection.secret_reference
        session.delete(connection)
        session.commit()
    secret_store.remove(reference)


def access_token(session, source_id: str, connection_id: int | None) -> str | None:
    if connection_id is None:
        return None
    connection = session.get(SourceConnection, connection_id)
    if not connection or not connection.enabled or connection.source_id != source_id:
        raise ValueError("The selected Source connection is unavailable")
    return secret_store.read(connection.secret_reference)
