"""VodLoft task workers.

Workers live behind the task registry so API, cron and event triggers all use the
same durable execution path.
"""
