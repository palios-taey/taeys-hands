#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRIMITIVES_PATH = ROOT / 'consultation_v2' / 'primitives.py'
ORCHESTRATOR_PATH = ROOT / 'consultation_v2' / 'orchestrator.py'
FAKE_DISPLAY = ':99'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeWatchError(Exception):
    pass


class FakePipeline:
    def __init__(self, client: 'FakeRedis') -> None:
        self.client = client
        self.watched_key = ''
        self.commands: list[tuple[str, str, str | None]] = []

    def __enter__(self) -> 'FakePipeline':
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def watch(self, key: str) -> None:
        self.watched_key = key

    def get(self, key: str) -> str | None:
        return self.client.data.get(key)

    def unwatch(self) -> None:
        self.watched_key = ''

    def multi(self) -> None:
        return None

    def delete(self, key: str) -> None:
        self.commands.append(('delete', key, None))

    def srem(self, key: str, value: str) -> None:
        self.commands.append(('srem', key, value))

    def execute(self) -> list[int]:
        if self.client.conflict_record is not None:
            self.client.data[self.watched_key] = self.client.conflict_record
            self.client.conflict_record = None
            self.commands.clear()
            raise FakeWatchError()
        results: list[int] = []
        for action, key, value in self.commands:
            if action == 'delete':
                results.append(int(self.client.data.pop(key, None) is not None))
            else:
                members = self.client.sets.setdefault(key, set())
                results.append(int(value in members))
                if value is not None:
                    members.discard(value)
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.conflict_record: str | None = None

    def set(self, key: str, value: str) -> bool:
        self.data[key] = value
        return True

    def sadd(self, key: str, value: str) -> int:
        members = self.sets.setdefault(key, set())
        added = int(value not in members)
        members.add(value)
        return added

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


def _load_primitives(client: FakeRedis):
    redis_module = types.ModuleType('redis')
    redis_exceptions = types.ModuleType('redis.exceptions')
    redis_exceptions.WatchError = FakeWatchError
    redis_module.exceptions = redis_exceptions

    storage_module = types.ModuleType('storage')
    storage_module.__path__ = []
    redis_pool = types.ModuleType('storage.redis_pool')
    redis_pool.NODE_ID = 'validator'
    redis_pool.node_key = lambda suffix: f'taey:validator:{suffix}'
    redis_pool.get_client = lambda: client

    runtime = types.ModuleType('consultation_v2.runtime')
    runtime.ConsultationRuntime = type('ConsultationRuntime', (), {})
    snapshot = types.ModuleType('consultation_v2.snapshot')
    snapshot.matches_spec = lambda *_args, **_kwargs: False
    snapshot.build_snapshot = lambda *_args, **_kwargs: None
    snapshot.build_menu_snapshot = lambda *_args, **_kwargs: None
    notify = types.ModuleType('consultation_v2.notify')
    notify.push_notification = lambda *_args, **_kwargs: None
    storage_policy = types.ModuleType('consultation_v2.storage_policy')
    types_module = types.ModuleType('consultation_v2.types')
    types_module.ElementRef = type('ElementRef', (), {})
    types_module.Snapshot = type('Snapshot', (), {})

    modules = {
        'redis': redis_module,
        'redis.exceptions': redis_exceptions,
        'storage': storage_module,
        'storage.redis_pool': redis_pool,
        'consultation_v2.runtime': runtime,
        'consultation_v2.snapshot': snapshot,
        'consultation_v2.notify': notify,
        'consultation_v2.storage_policy': storage_policy,
        'consultation_v2.types': types_module,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        spec = importlib.util.spec_from_file_location(
            'consultation_v2._terminal_monitor_cleanup_validator',
            PRIMITIVES_PATH,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError('could not load consultation_v2.primitives')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, prior in previous.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


def _foreign_record(record: dict[str, object]) -> str:
    foreign = dict(record)
    foreign['registration_owner_token'] = 'f' * 32
    foreign['registrar_pid'] = int(record['registrar_pid']) + 1
    return json.dumps(foreign)


def _assert_driver_finally_cleanup() -> None:
    tree = ast.parse(ORCHESTRATOR_PATH.read_text(encoding='utf-8'))
    run_consultation = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == 'run_consultation'
    )
    lifecycle_tries = [
        node
        for node in ast.walk(run_consultation)
        if isinstance(node, ast.Try)
        and any(
            isinstance(call.func, ast.Attribute) and call.func.attr == 'run'
            for statement in node.body
            for call in ast.walk(statement)
            if isinstance(call, ast.Call)
        )
    ]
    if len(lifecycle_tries) != 1:
        raise RuntimeError('run_consultation must have one guarded driver.run lifecycle')
    final_calls = [
        call
        for statement in lifecycle_tries[0].finalbody
        for call in ast.walk(statement)
        if isinstance(call, ast.Call)
    ]
    if not any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr == 'deregister_owned_monitor_session'
        for call in final_calls
    ):
        raise RuntimeError('driver.run lifecycle lacks terminal owned-monitor cleanup')
    if any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr == 'deregister_monitor_session'
        for call in ast.walk(run_consultation)
        if isinstance(call, ast.Call)
    ):
        raise RuntimeError('run_consultation retains unconditional monitor deletion')


def main() -> int:
    client = FakeRedis()
    primitives = _load_primitives(client)
    monitor_id = 'chatgpt:validator-request:selection:validator-selection'
    session_key = f'taey:validator:active_session:{monitor_id}'
    set_key = 'taey:validator:active_session_ids'
    poison_key = 'taey:validator:run_state:validator-request'
    client.data[poison_key] = json.dumps({'status': 'dead_session', 'dead_session': True})

    primitives.register_monitor_session(
        monitor_id,
        {
            'platform': 'chatgpt',
            'display': FAKE_DISPLAY,
            'request_id': 'validator-request',
            'durable_run_id': 'validator-request:selection:validator-selection',
        },
    )
    registered = json.loads(client.data[session_key])
    required_identity = {
        'monitor_id',
        'registration_owner_token',
        'registrar_pid',
        'registrar_starttime',
    }
    if not required_identity.issubset(registered):
        raise RuntimeError('monitor registration lacks exact process-owner identity')
    if not primitives.deregister_owned_monitor_session(monitor_id):
        raise RuntimeError('owned terminal registration was not removed')
    if session_key in client.data or session_key in client.sets.get(set_key, set()):
        raise RuntimeError('owned terminal registration was only partially removed')
    if json.loads(client.data[poison_key]).get('dead_session') is not True:
        raise RuntimeError('dead run-state poison was changed by monitor cleanup')

    primitives.register_monitor_session(
        monitor_id,
        {'platform': 'chatgpt', 'display': FAKE_DISPLAY},
    )
    client.data[session_key] = _foreign_record(json.loads(client.data[session_key]))
    try:
        primitives.deregister_owned_monitor_session(monitor_id)
    except primitives.MonitorRegistrationOwnershipError:
        pass
    else:
        raise RuntimeError('foreign monitor owner was not refused')
    if session_key not in client.data or session_key not in client.sets.get(set_key, set()):
        raise RuntimeError('foreign monitor registration was mutated')

    race_id = 'chatgpt:race-request:selection:race-selection'
    race_key = f'taey:validator:active_session:{race_id}'
    primitives.register_monitor_session(
        race_id,
        {'platform': 'chatgpt', 'display': FAKE_DISPLAY},
    )
    client.conflict_record = _foreign_record(json.loads(client.data[race_key]))
    try:
        primitives.deregister_owned_monitor_session(race_id)
    except primitives.MonitorRegistrationOwnershipError:
        pass
    else:
        raise RuntimeError('ownership change during cleanup was not refused')
    if race_key not in client.data or race_key not in client.sets.get(set_key, set()):
        raise RuntimeError('raced foreign monitor registration was mutated')
    if json.loads(client.data[poison_key]).get('dead_session') is not True:
        raise RuntimeError('dead run-state poison changed during refusal cases')

    _assert_driver_finally_cleanup()
    print('TERMINAL_MONITOR_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
