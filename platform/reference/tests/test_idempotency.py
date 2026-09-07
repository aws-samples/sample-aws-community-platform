from botocore.exceptions import ClientError

from reference.idempotency import IdempotencyStore


class _FakeDdb:
    """Minimal fake: first put for a key succeeds; subsequent puts raise the conditional error."""
    def __init__(self):
        self._keys = set()

    def put_item(self, TableName, Item, ConditionExpression):  # noqa: N803 (boto3 kwarg names)
        key = Item["eventId"]["S"]
        if key in self._keys:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}}, "PutItem"
            )
        self._keys.add(key)


def test_run_once_executes_first_time_only():
    store = IdempotencyStore("idem", client=_FakeDdb())
    calls = []

    executed_1 = store.run_once("evt-1", lambda: calls.append(1))
    executed_2 = store.run_once("evt-1", lambda: calls.append(1))

    assert executed_1 is True
    assert executed_2 is False   # duplicate skipped
    assert calls == [1]          # action ran exactly once
