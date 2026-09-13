from uuid import uuid4

from task_manager.registry import get_task, on_event, on_interval, task


def test_event_trigger_decorator_works_outside_task_decorator() -> None:
    key = f"test.outer.{uuid4()}"

    @on_event("test.event", resource_type="video")
    @task(key, "Test task", allowed_resource_types=("video",))
    def worker(_context, _resource_type, _resource_id, _payload):
        return None

    meta, registered = get_task(key)
    assert registered is worker
    assert len(meta.triggers) == 1
    assert meta.triggers[0].event_name == "test.event"
    assert meta.triggers[0].resource_type == "video"


def test_trigger_decorator_works_inside_task_decorator() -> None:
    key = f"test.inner.{uuid4()}"

    @task(key, "Test interval", allowed_resource_types=("system",), max_concurrency=2)
    @on_interval(15)
    def worker(_context, _resource_type, _resource_id, _payload):
        return None

    meta, registered = get_task(key)
    assert registered is worker
    assert meta.max_concurrency == 2
    assert len(meta.triggers) == 1
    assert meta.triggers[0].trigger_type == "interval"
    assert meta.triggers[0].interval_minutes == 15
