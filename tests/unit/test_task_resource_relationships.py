from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_deleting_collection_cascades_scheduler_work_and_exposes_relationships(tmp_path):
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base
    from backend.db.models import Collection
    from task_manager.scheduler.db import (
        TaskDefinition,
        TaskOperation,
        TaskOperationTarget,
        TaskRun,
        TaskSchedule,
    )
    from task_manager.scheduler.types import OperationSource, OperationStatus, ResourceType, TaskStatus

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'resource-task-relations.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            collection = Collection(
                source_key="dailywire",
                uuid="collection-uuid",
                slug="collection-slug",
                title="Collection title",
                description=None,
                sharing_url="https://example.test/collection",
                membership_level="FREE",
                type="podcast",
                episode_identifier="numbered",
                author_name="Host",
                author_slug="host",
                author_headshot_path=None,
                background_image_path=None,
                logo_image_path=None,
                thumbnail_landscape_path=None,
                thumbnail_portrait_path=None,
                thumbnail_square_path=None,
            )
            session.add(collection)
            session.flush()

            definition = TaskDefinition(
                key="resource_relationship_worker",
                title="Resource relationship worker",
                description=None,
                allowed_resource_types=["collection"],
                default_max_retries=0,
            )
            session.add(definition)
            session.flush()

            schedule = TaskSchedule(
                definition_id=definition.id,
                resource_type=ResourceType.COLLECTION,
                resource_id=collection.id,
                trigger="interval",
                trigger_args={"minutes": 5},
                active=True,
                max_retries=0,
            )
            run = TaskRun(
                schedule_id=None,
                definition_id=definition.id,
                resource_type=ResourceType.COLLECTION,
                resource_id=collection.id,
                status=TaskStatus.RUNNING,
                progress=35,
                message="Working",
                meta=None,
                result=None,
                attempt_count=1,
                max_retries=0,
                last_error=None,
                next_retry_at=None,
                started_at=datetime.now(timezone.utc),
                finished_at=None,
                runtime_ms=None,
            )
            operation = TaskOperation(
                id="collection-operation",
                kind="collection.sync",
                source=OperationSource.UI.value,
                resource_type="collection",
                resource_id=collection.id,
                title=collection.title,
                status=OperationStatus.RUNNING.value,
                progress=35,
                message="Working",
                result=None,
                context={},
                error=None,
                notification_seen_at=None,
                started_at=datetime.now(timezone.utc),
                finished_at=None,
            )
            target = TaskOperationTarget(
                operation=operation,
                task_key=definition.key,
                resource_type="collection",
                resource_id=collection.id,
                slot_key="collection",
                task_kwargs={},
                recover_on_restart=True,
            )
            session.add_all([schedule, run, operation, target])
            session.commit()

            collection_id = collection.id
            schedule_id = schedule.id
            run_id = run.id
            operation_id = operation.id
            target_id = target.id

            assert [item.id for item in collection.task_schedules] == [schedule_id]
            assert [item.id for item in collection.task_runs] == [run_id]
            assert [item.id for item in collection.task_operations] == [operation_id]
            assert [item.id for item in collection.task_operation_targets] == [target_id]

            session.delete(collection)
            session.commit()

            assert session.get(Collection, collection_id) is None
            assert session.get(TaskSchedule, schedule_id) is None
            assert session.get(TaskRun, run_id) is None
            assert session.get(TaskOperation, operation_id) is None
            assert session.get(TaskOperationTarget, target_id) is None
    finally:
        engine.dispose()


def test_deleting_a_download_profile_takes_the_same_few_statements_however_much_it_has(tmp_path):
    """Its task history goes and its downloads stay, without a statement per row."""
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from conftest import available_artifact
    from sqlalchemy import event, func, select
    from backend.db import Base
    from backend.db.models import (
        Collection, DownloadProfile, Episode, EpisodeMediaDownload, LocalMediaProfile, Season, Site,
    )
    from task_manager.scheduler.db import TaskDefinition, TaskOperation, TaskOperationRun, TaskOperationTarget, TaskRun
    from task_manager.scheduler.types import ResourceType, TaskStatus

    engine = create_engine(f"sqlite:///{(tmp_path / 'profile.db').as_posix()}")
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)

    def statements_to_delete_a_profile(index: int, rows: int) -> int:
        with Session(engine) as session:
            if session.get(Site, "dailywire") is None:
                session.add(Site(key="dailywire", name="The Daily Wire", domains=["dailywire.com"]))
                session.add(TaskDefinition(key="worker", title="Worker", default_max_retries=0))
                session.flush()
            definition_id = session.scalar(select(TaskDefinition.id))
            profile = LocalMediaProfile(
                slug=f"audio-{index}", name=f"Audio {index}", preferred_format="format_audio_only",
                output_template=f"/downloads/{index}/{{{{ episode }}}}.ext",
            )
            collection = Collection(
                source_key="dailywire", site_key="dailywire", uuid=f"collection-{index}", slug=f"show-{index}",
                title="Show", description=None, membership_level="FREE", sharing_url=f"https://example.test/show/{index}",
                type="podcast", episode_identifier="numbered", author_name="Host", author_slug="host",
            )
            season = Season(collection=collection, index=1, slug="season-1", name="Season 1")
            session.add_all([profile, collection, season])
            session.flush()
            download_profile = DownloadProfile(collection_id=collection.id, local_media_profile_id=profile.id)
            session.add(download_profile)
            session.flush()
            for row in range(rows):
                episode = Episode(
                    source_key="dailywire", uuid=f"episode-{index}-{row}", type="episode", collection=collection,
                    season=season, index=row, episode_identifier=f"ep{row}", slug=f"episode-{index}-{row}", title="Episode",
                    description="", duration=60, publish_status="published_final", sharing_url="https://example.test/e",
                )
                run = TaskRun(
                    definition_id=definition_id, resource_type=ResourceType.DOWNLOAD_PROFILE,
                    resource_id=download_profile.id, status=TaskStatus.SUCCEEDED,
                )
                operation = TaskOperation(
                    id=f"operation-{index}-{row}", kind="kind", source="user", resource_type="download_profile",
                    resource_id=download_profile.id, title="Operation", status="succeeded",
                )
                session.add_all([episode, run, operation])
                session.flush()
                target = TaskOperationTarget(
                    operation_id=operation.id, task_key="worker", resource_type="download_profile",
                    resource_id=download_profile.id, slot_key="slot",
                )
                session.add(target)
                session.add(EpisodeMediaDownload(
                    type="episode", media_item_id=episode.id, local_media_profile_id=profile.id,
                    download_profile_id=download_profile.id, file_path=f"/downloads/{index}/{row}.mp3",
                    **(available_artifact() | {"artifact_stat_ino": f"{index}-{row}"}),
                ))
                session.flush()
                session.add(TaskOperationRun(target_id=target.id, task_run_id=run.id, operation_id=operation.id))
            session.commit()
            profile_id = download_profile.id

        count = 0

        def counted(*_arguments) -> None:
            nonlocal count
            count += 1

        event.listen(engine, "before_cursor_execute", counted)
        try:
            with Session(engine) as session:
                session.delete(session.get(DownloadProfile, profile_id))
                session.commit()
        finally:
            event.remove(engine, "before_cursor_execute", counted)

        with Session(engine) as session:
            downloads = session.scalars(
                select(EpisodeMediaDownload.download_profile_id)
                .where(EpisodeMediaDownload.file_path.like(f"/downloads/{index}/%"))
            ).all()
            assert downloads == [None] * rows
            for model in (TaskRun, TaskOperation, TaskOperationTarget, TaskOperationRun):
                assert session.scalar(select(func.count()).select_from(model)) == 0
        return count

    try:
        assert statements_to_delete_a_profile(1, rows=2) == statements_to_delete_a_profile(2, rows=40)
    finally:
        engine.dispose()
