"""Private account configuration shared by Source operations and background work."""
import json
import time
from urllib.parse import urlsplit
from source_contracts import AuthenticationResult
from backend.db.models.vodloft import SourceConnection
from backend.source_manager import secrets as secret_store
from backend.source_manager.gateway import SourceGateway


def _validate_source(source_id: str):
    manifest = next((m for m in SourceGateway().manifests() if m.source_id == source_id), None)
    if manifest is None:
        raise ValueError("The selected Source runtime is unavailable")
    return manifest


def _authentication(connection: SourceConnection) -> dict:
    value = secret_store.read(connection.authentication_reference)
    return json.loads(value) if value else {}



def _save_authentication(connection: SourceConnection, value: dict) -> None:
    connection.authentication_reference = secret_store.save(json.dumps(value), connection.authentication_reference)
    connection.capabilities = None
    connection.domain_capabilities = {}
    connection.authenticated = None
    connection.last_capability_check_at = None



def _validated_authentication(source_id: str, result: dict) -> dict:
    try:
        result = AuthenticationResult.model_validate(result).model_dump(mode="json")
    except ValueError:
        raise ValueError("Source returned an invalid authentication result") from None
    fields = {field.name: field for field in _validate_source(source_id).configuration_schema}
    if set(result["configuration"]) - set(fields):
        raise ValueError("Source authentication returned undeclared configuration")
    challenge = result.get("challenge")
    if challenge and challenge.get("verification_url"):
        parsed = urlsplit(challenge["verification_url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid Source authentication verification URL")
    return result



def source_options(session, source_id: str, connection_id: int | None) -> dict:
    if connection_id is None:
        return {}
    connection = session.get(SourceConnection, connection_id)
    if not connection or not connection.enabled or connection.source_id != source_id:
        raise ValueError("The selected Source connection is unavailable")
    options = dict(connection.settings or {})
    options.update({key: secret_store.read(reference) for key, reference in
        (connection.secret_references or {}).items()})
    auth = _authentication(connection)
    if auth.get("status") == "authorized":
        if auth.get("expires_at") is not None and auth["expires_at"] < time.time() + 60:
            gateway = SourceGateway({source_id: auth["_command"]}) if auth.get("_command") else SourceGateway()
            renewed = _validated_authentication(source_id, gateway.call(source_id, "auth_refresh",
                timeout=35, private_state=auth["private_state"]))
            renewed["_command"] = auth.get("_command")
            _save_authentication(connection, renewed)
            session.commit()
            auth = renewed
        if auth["status"] != "authorized":
            raise ValueError("This Source account needs authentication again")
        options.update(auth["configuration"])
    return options

