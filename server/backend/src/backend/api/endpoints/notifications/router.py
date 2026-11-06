from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from backend.api.models.notifications import (
    AppriseServiceRead,
    DeliveryRead,
    DestinationCreate,
    DestinationInput,
    DestinationPreviewRead,
    DestinationRead,
    DestinationTest,
    DestinationUpdate,
    EventRead,
    PersonalNotificationsRead,
    PushDeviceStatusRead,
    PushEndpointInput,
    PushSubscriptionInput,
    RuleInput,
    RuleRead,
    ScriptsRead,
    TestRead,
    VapidKeyRead,
    WebhookExampleRead,
)
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Access, Area, Level
from backend.security.deps import SignedIn, requires
from backend.services.notifications import EVENTS
from backend.services.notifications.destinations import available_scripts, scripts_folder
from backend.services.notifications.senders import SCRIPT_VARIABLES

from . import service

router = APIRouter(
    prefix="/notifications", tags=["Messages and actions"], dependencies=[requires(Area.SETTINGS, Level.MANAGE)],
)
account_router = APIRouter(prefix="/account/notifications", tags=["Messages and actions"])
push_router = APIRouter(prefix="/push", tags=["Messages and actions"])
signed_in = SignedIn()


# ---------- Settings › Messages and actions ----------
@router.get("/events", response_model=list[EventRead])
def notification_events():
    return EVENTS


@router.get("/services", response_model=list[AppriseServiceRead])
def notification_services():
    """Every service Apprise can send to, with the fields to fill in."""
    return service.services()


@router.get("/scripts", response_model=ScriptsRead)
def notification_scripts():
    """The scripts VODLoft may run, and the variables they receive."""
    return {"folder": str(scripts_folder()), "scripts": available_scripts(), "variables": list(SCRIPT_VARIABLES)}


@router.get("/webhook-example", response_model=WebhookExampleRead)
def notification_webhook_example():
    """The exact JSON a webhook receives, filled from the newest download."""
    with db_session() as s:
        return service.webhook_example(s)


@router.get("/destinations", response_model=list[DestinationRead])
def notification_destinations():
    with db_session() as s:
        return service.destinations(s)


@router.post("/destinations/preview", response_model=DestinationPreviewRead)
def notification_destination_preview(body: DestinationInput):
    """Check what was entered and show it as it will be listed, without saving."""
    return service.preview(body)


@router.post("/destinations/test", response_model=TestRead)
def notification_destination_test_unsaved(body: DestinationTest):
    with db_session() as s:
        return service.test_unsaved(s, body.destination)


@router.post("/destinations", response_model=DestinationRead, status_code=status.HTTP_201_CREATED)
def notification_destination_create(body: DestinationCreate):
    return run_write_transaction(lambda s: service.add_destination(s, body))


@router.patch("/destinations/{destination_id}", response_model=DestinationRead)
def notification_destination_update(destination_id: int, body: DestinationUpdate):
    return run_write_transaction(lambda s: service.change_destination(s, destination_id, body))


@router.delete("/destinations/{destination_id}", status_code=status.HTTP_204_NO_CONTENT)
def notification_destination_delete(destination_id: int):
    run_write_transaction(lambda s: service.remove_destination(s, destination_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/destinations/{destination_id}/test", response_model=TestRead)
def notification_destination_test(destination_id: int):
    return service.test_saved(destination_id)


@router.get("/rules", response_model=list[RuleRead])
def notification_rules():
    with db_session() as s:
        return service.rules(s)


@router.post("/rules", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
def notification_rule_create(body: RuleInput):
    return run_write_transaction(lambda s: RuleRead.model_validate(service.add_rule(s, body)))


@router.put("/rules/{rule_id}", response_model=RuleRead)
def notification_rule_update(rule_id: int, body: RuleInput):
    return run_write_transaction(lambda s: RuleRead.model_validate(service.change_rule(s, rule_id, body)))


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def notification_rule_delete(rule_id: int):
    run_write_transaction(lambda s: service.remove_rule(s, rule_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/rules/restore-defaults", response_model=list[RuleRead])
def notification_rules_restore_defaults():
    """Bring back the default rules that were deleted."""
    return run_write_transaction(lambda s: [RuleRead.model_validate(rule) for rule in service.restore_defaults(s)])


@router.get("/history", response_model=list[DeliveryRead])
def notification_history():
    """What was sent lately, and what failed."""
    with db_session() as s:
        return service.history(s)


# ---------- Account › Notifications ----------
@account_router.get("", response_model=PersonalNotificationsRead)
def account_notifications(access: Access = Depends(signed_in)):
    # The person's own rules are made the first time they are asked for.
    return run_write_transaction(lambda s: PersonalNotificationsRead.model_validate(service.personal(s, access.user_id)))


@account_router.get("/events", response_model=list[EventRead])
def account_notification_events(access: Access = Depends(signed_in)):
    return [definition for definition in EVENTS if definition.personal]


@account_router.post("/rules", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
def account_notification_rule_create(body: RuleInput, access: Access = Depends(signed_in)):
    return run_write_transaction(
        lambda s: RuleRead.model_validate(service.add_rule(s, body, personal=True, user_id=access.user_id)),
    )


@account_router.put("/rules/{rule_id}", response_model=RuleRead)
def account_notification_rule_update(rule_id: int, body: RuleInput, access: Access = Depends(signed_in)):
    return run_write_transaction(
        lambda s: RuleRead.model_validate(service.change_rule(s, rule_id, body, personal=True, user_id=access.user_id)),
    )


@account_router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def account_notification_rule_delete(rule_id: int, access: Access = Depends(signed_in)):
    run_write_transaction(lambda s: service.remove_rule(s, rule_id, personal=True, user_id=access.user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@account_router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def account_notification_device_delete(device_id: int, access: Access = Depends(signed_in)):
    run_write_transaction(lambda s: service.remove_device(s, device_id, access.user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Push to the installed app ----------
@push_router.get("/vapid-key", response_model=VapidKeyRead)
def push_vapid_key(access: Access = Depends(signed_in)):
    # The key is made the first time it is asked for.
    return run_write_transaction(service.push_key)


@push_router.post("/subscribe", response_model=PushDeviceStatusRead)
def push_subscribe(body: PushSubscriptionInput, access: Access = Depends(signed_in)):
    device_id = run_write_transaction(lambda s: service.subscribe(s, body, access.user_id).id)
    return {"subscribed": True, "device_id": device_id}


@push_router.post("/lookup", response_model=PushDeviceStatusRead)
def push_lookup(body: PushEndpointInput, access: Access = Depends(signed_in)):
    """Whether this browser already gets push messages for whoever is signed in."""
    with db_session() as s:
        return service.lookup(s, body.endpoint, access.user_id)


@push_router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
def push_unsubscribe(body: PushEndpointInput, access: Access = Depends(signed_in)):
    run_write_transaction(lambda s: service.unsubscribe(s, body.endpoint, access.user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@push_router.post("/test", status_code=status.HTTP_204_NO_CONTENT)
def push_test(body: PushEndpointInput, access: Access = Depends(signed_in)):
    run_write_transaction(lambda s: service.push_test(s, body.endpoint, access.user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
