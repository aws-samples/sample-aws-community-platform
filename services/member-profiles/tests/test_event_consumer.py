"""EventConsumer tests — 6 consumed Identity & Access event types, idempotent
consumption, profile-extension record as an event-sourced cache (BR-9, plan Q1/Q9)."""
from _conventions.idempotency import IdempotencyStore
from event_consumer import EventConsumer


def _envelope(event_id, event_type, data):
    return {"id": event_id, "type": event_type, "data": data}


def test_user_provisioned_creates_profile(repo):
    consumer = EventConsumer(repo)
    consumer.handle(_envelope("e1", "UserProvisioned",
                              {"userId": "u1", "email": "a@x.com", "role": "Member"}))
    profile = repo.get_profile("u1")
    assert profile["email"] == "a@x.com"
    assert profile["role"] == "Member"
    assert profile["status"] == "active"


def test_user_role_changed_updates_role(repo):
    consumer = EventConsumer(repo)
    consumer.handle(_envelope("e1", "UserProvisioned", {"userId": "u1", "email": "a@x.com", "role": "Member"}))
    consumer.handle(_envelope("e2", "UserRoleChanged", {"userId": "u1", "oldRole": "Member", "newRole": "UserGroupLeader"}))
    assert repo.get_profile("u1")["role"] == "UserGroupLeader"


def test_user_deactivated_and_reactivated(repo):
    consumer = EventConsumer(repo)
    consumer.handle(_envelope("e1", "UserProvisioned", {"userId": "u1", "email": "a@x.com", "role": "Member"}))
    consumer.handle(_envelope("e2", "UserDeactivated", {"userId": "u1"}))
    assert repo.get_profile("u1")["status"] == "inactive"
    consumer.handle(_envelope("e3", "UserReactivated", {"userId": "u1"}))
    assert repo.get_profile("u1")["status"] == "active"


def test_member_joined_group_records_join_date(repo):
    consumer = EventConsumer(repo)
    consumer.handle(_envelope("e1", "UserProvisioned", {"userId": "u1", "email": "a@x.com", "role": "Member"}))
    consumer.handle(_envelope("e2", "MemberJoinedGroup", {"memberId": "u1", "groupId": "g1", "at": "2026-01-01"}))
    groups = repo.get_profile("u1")["groups"]
    assert groups == [{"groupId": "g1", "joinedAt": "2026-01-01"}]


def test_rejoin_overwrites_join_date(repo):
    """BR-G5 semantics preserved — rejoin resets displayed join date."""
    consumer = EventConsumer(repo)
    consumer.handle(_envelope("e1", "UserProvisioned", {"userId": "u1", "email": "a@x.com", "role": "Member"}))
    consumer.handle(_envelope("e2", "MemberJoinedGroup", {"memberId": "u1", "groupId": "g1", "at": "2026-01-01"}))
    consumer.handle(_envelope("e3", "MemberLeftGroup", {"memberId": "u1", "groupId": "g1"}))
    consumer.handle(_envelope("e4", "MemberJoinedGroup", {"memberId": "u1", "groupId": "g1", "at": "2026-06-01"}))
    groups = repo.get_profile("u1")["groups"]
    assert groups == [{"groupId": "g1", "joinedAt": "2026-06-01"}]


def test_member_removed_same_effect_as_left(repo):
    consumer = EventConsumer(repo)
    consumer.handle(_envelope("e1", "UserProvisioned", {"userId": "u1", "email": "a@x.com", "role": "Member"}))
    consumer.handle(_envelope("e2", "MemberJoinedGroup", {"memberId": "u1", "groupId": "g1", "at": "2026-01-01"}))
    consumer.handle(_envelope("e3", "MemberRemoved", {"memberId": "u1", "groupId": "g1"}))
    assert repo.get_profile("u1")["groups"] == []


def test_idempotent_consumption_skips_duplicate_event(repo, aws):
    idem = IdempotencyStore("member-profiles-idem-test")
    consumer = EventConsumer(repo, idem)
    env = _envelope("dup-1", "MemberJoinedGroup", {"memberId": "u1", "groupId": "g1", "at": "2026-01-01"})
    consumer.handle(env)
    # Redeliver the same event id with different data — must be a no-op (idempotent).
    consumer.handle(_envelope("dup-1", "MemberJoinedGroup", {"memberId": "u1", "groupId": "g2", "at": "2026-02-01"}))
    groups = repo.get_profile("u1")["groups"]
    assert groups == [{"groupId": "g1", "joinedAt": "2026-01-01"}]  # second call skipped
