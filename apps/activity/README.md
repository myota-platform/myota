# Activity service

Activity owns activations, QSOs, ADIF imports, awards execution, certificates,
and participant statistics. The API and award routes share port `8004`; durable
jobs and notifications run in separate workers. Activity data and migrations
belong to `myota_activity`.

## Development

From this directory:

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 run_activity.py
```

The API listens on port `8004`. Durable operation uses PostgreSQL and NATS.
The notification tests need an isolated JetStream broker; the [Activity CI
workflow](../../.github/workflows/activity.yml) shows the complete test setup.

The schema baseline is in [`migrations/`](migrations/). Deploy owns migration
execution; see [database migration ownership](../../deploy/db/README.md).

## Further documentation

- [Activity job and award API](https://github.com/myota-platform/myota-docs/blob/main/docs/domain/api/phase3-activity-award-jobs.md)
- [Activity work queues](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/activity-work-queues.md)
- [Notification operations](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/activity-notification-consumer.md)
- [Award design](https://github.com/myota-platform/myota-docs/blob/main/docs/programme-and-award-design.md)
