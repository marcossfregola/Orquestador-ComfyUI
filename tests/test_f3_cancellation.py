import unittest

from orquestador.adapters import (
    BackendJobRef,
    CancellationAction,
    CancellationClassification,
    CancellationIssueKind,
    CancellationPhase,
    CancellationPreflight,
    CancellationResult,
    CancellationState,
    ComfyUIClient,
    ComfyUIProtocolError,
    ComfyUIRejectedError,
    ComfyUIServerError,
    ComfyUITransportError,
    ComfyUITimeoutError,
    HistoryResult,
    HistoryState,
    QueueSnapshot,
    QueueState,
    ComfyUICancellationAdapter,
)


def refs(values):
    return tuple(value if isinstance(value, BackendJobRef) else BackendJobRef(value) for value in values)


def queue(*, running=(), pending=(), state=None):
    running = refs(running)
    pending = refs(pending)
    if state is None:
        state = QueueState.RUNNING if running else QueueState.PENDING if pending else QueueState.EMPTY
    return QueueSnapshot(running, pending, state)


def history(ref, state, *, raw=None, error=None):
    return HistoryResult(ref, state, raw=raw, error=error)


class FakeClient:
    """Scripted client; every observed call is retained for safety assertions."""

    def __init__(self, queues=(), histories=(), *, delete_error=None):
        self.queues = list(queues)
        self.histories = list(histories)
        self.delete_error = delete_error
        self.delete_calls = []
        self.interrupt_calls = []
        self.queue_calls = 0
        self.history_calls = 0

    def queue(self):
        self.queue_calls += 1
        value = self.queues.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def history(self, ref):
        self.history_calls += 1
        value = self.histories.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def delete_pending(self, prompt_ids):
        self.delete_calls.append(prompt_ids)
        if self.delete_error is not None:
            raise self.delete_error

    def interrupt_running_native_non_atomic(self, prompt_id):
        self.interrupt_calls.append(prompt_id)
        raise AssertionError("safe cancellation must never call /interrupt")


class CancellationPreflightTests(unittest.TestCase):
    def assert_classification(self, queue_value, history_state, expected):
        ref = BackendJobRef("target")
        client = FakeClient([queue_value], [history(ref, history_state)])
        result = ComfyUICancellationAdapter(client).preflight(ref)
        self.assertEqual(result.classification, expected)
        self.assertIs(result.target, ref)
        self.assertEqual(client.delete_calls, [])

    def test_pending_with_queued_history_is_target_pending(self):
        self.assert_classification(queue(pending=("target",)), HistoryState.QUEUED, CancellationClassification.TARGET_PENDING)

    def test_pending_with_not_found_history_is_f1_compatible(self):
        self.assert_classification(queue(pending=("target",)), HistoryState.NOT_FOUND, CancellationClassification.TARGET_PENDING)

    def test_pending_with_running_history_is_contradictory(self):
        self.assert_classification(queue(pending=("target",)), HistoryState.RUNNING, CancellationClassification.CONTRADICTORY)

    def test_pending_with_terminal_history_is_contradictory(self):
        for state in (HistoryState.SUCCEEDED, HistoryState.FAILED):
            with self.subTest(state=state):
                self.assert_classification(queue(pending=("target",)), state, CancellationClassification.CONTRADICTORY)

    def test_pending_with_unknown_history_fails_closed(self):
        self.assert_classification(queue(pending=("target",)), HistoryState.UNKNOWN, CancellationClassification.UNKNOWN)

    def test_running_with_running_history_is_target_running(self):
        self.assert_classification(queue(running=("target",)), HistoryState.RUNNING, CancellationClassification.TARGET_RUNNING)

    def test_running_with_queued_history_is_contradictory(self):
        self.assert_classification(queue(running=("target",)), HistoryState.QUEUED, CancellationClassification.CONTRADICTORY)

    def test_running_with_not_found_history_is_ambiguous(self):
        self.assert_classification(queue(running=("target",)), HistoryState.NOT_FOUND, CancellationClassification.AMBIGUOUS)

    def test_running_with_unknown_history_fails_closed(self):
        self.assert_classification(queue(running=("target",)), HistoryState.UNKNOWN, CancellationClassification.UNKNOWN)

    def test_queue_absent_terminal_history_is_already_terminal(self):
        for state in (HistoryState.SUCCEEDED, HistoryState.FAILED):
            with self.subTest(state=state):
                self.assert_classification(queue(), state, CancellationClassification.ALREADY_TERMINAL)

    def test_queue_absent_not_found_history_is_not_found(self):
        self.assert_classification(queue(), HistoryState.NOT_FOUND, CancellationClassification.NOT_FOUND)

    def test_queue_absent_nonterminal_history_is_ambiguous(self):
        for state in (HistoryState.RUNNING, HistoryState.QUEUED):
            with self.subTest(state=state):
                self.assert_classification(queue(), state, CancellationClassification.AMBIGUOUS)

    def test_queue_absent_unknown_history_is_unknown(self):
        self.assert_classification(queue(), HistoryState.UNKNOWN, CancellationClassification.UNKNOWN)

    def test_target_in_both_queues_is_contradictory(self):
        self.assert_classification(queue(running=("target",), pending=("target",)), HistoryState.RUNNING, CancellationClassification.CONTRADICTORY)

    def test_unknown_queue_never_becomes_terminal(self):
        self.assert_classification(queue(state=QueueState.UNKNOWN), HistoryState.SUCCEEDED, CancellationClassification.UNKNOWN)

    def test_malformed_queue_fails_closed(self):
        ref = BackendJobRef("target")
        malformed = QueueSnapshot(("target",), (), QueueState.RUNNING)
        client = FakeClient([malformed], [history(ref, HistoryState.QUEUED)])
        result = ComfyUICancellationAdapter(client).preflight(ref)
        self.assertEqual(result.classification, CancellationClassification.UNKNOWN)
        self.assertEqual(result.issue_kind, CancellationIssueKind.PROTOCOL)
        self.assertEqual(client.history_calls, 0)

    def test_inconsistent_queue_state_fails_closed(self):
        ref = BackendJobRef("target")
        malformed = QueueSnapshot((), (ref,), QueueState.EMPTY)
        client = FakeClient([malformed], [history(ref, HistoryState.QUEUED)])
        result = ComfyUICancellationAdapter(client).preflight(ref)
        self.assertEqual(result.classification, CancellationClassification.UNKNOWN)
        self.assertEqual(client.history_calls, 0)

    def test_mismatched_history_reference_fails_closed(self):
        target = BackendJobRef("target")
        other = BackendJobRef("other")
        client = FakeClient([queue(pending=(target,))], [history(other, HistoryState.QUEUED)])
        result = ComfyUICancellationAdapter(client).preflight(target)
        self.assertEqual(result.classification, CancellationClassification.UNKNOWN)
        self.assertEqual(result.issue_kind, CancellationIssueKind.PROTOCOL)

    def test_malformed_history_payload_fails_closed(self):
        target = BackendJobRef("target")
        client = FakeClient([queue(pending=(target,))], [history(target, HistoryState.QUEUED, raw="not-an-object")])
        result = ComfyUICancellationAdapter(client).preflight(target)
        self.assertEqual(result.classification, CancellationClassification.UNKNOWN)
        self.assertEqual(result.issue_kind, CancellationIssueKind.PROTOCOL)

    def test_read_error_is_unknown_and_does_not_mutate(self):
        target = BackendJobRef("target")
        client = FakeClient([ComfyUITimeoutError("queue timeout")], [])
        result = ComfyUICancellationAdapter(client).cancel(target)
        self.assertEqual(result.state, CancellationState.UNKNOWN)
        self.assertEqual(result.issue_kind, CancellationIssueKind.TIMEOUT)
        self.assertEqual(result.phase, CancellationPhase.PREFLIGHT)
        self.assertEqual(client.delete_calls, [])


class CancellationMutationTests(unittest.TestCase):
    def test_pending_delete_uses_exact_target_and_confirms_not_found(self):
        target = BackendJobRef("target")
        client = FakeClient(
            [queue(pending=(target,)), queue()],
            [history(target, HistoryState.QUEUED), history(target, HistoryState.NOT_FOUND)],
        )
        result = ComfyUICancellationAdapter(client).cancel(target)
        self.assertIs(result.target, target)
        self.assertEqual(result.state, CancellationState.CONFIRMED)
        self.assertEqual(result.action, CancellationAction.QUEUE_DELETE)
        self.assertEqual(result.phase, CancellationPhase.POST_VERIFICATION)
        self.assertEqual(client.delete_calls, [(target,)])
        self.assertEqual(client.interrupt_calls, [])

    def test_pending_delete_still_present_is_requested_not_confirmed(self):
        target = BackendJobRef("target")
        client = FakeClient(
            [queue(pending=(target,)), queue(pending=(target,))],
            [history(target, HistoryState.QUEUED), history(target, HistoryState.QUEUED)],
        )
        result = ComfyUICancellationAdapter(client).cancel(target)
        self.assertEqual(result.state, CancellationState.REQUESTED)
        self.assertEqual(result.phase, CancellationPhase.POST_VERIFICATION)
        self.assertEqual(len(client.delete_calls), 1)

    def test_terminal_race_is_distinct_from_already_terminal(self):
        target = BackendJobRef("target")
        client = FakeClient(
            [queue(pending=(target,)), queue()],
            [history(target, HistoryState.QUEUED), history(target, HistoryState.SUCCEEDED)],
        )
        result = ComfyUICancellationAdapter(client).cancel(target)
        self.assertEqual(result.state, CancellationState.RACED_TERMINAL)
        self.assertNotEqual(result.state, CancellationState.ALREADY_TERMINAL)

    def test_pending_to_running_race_is_unsafe_and_never_interrupts(self):
        target = BackendJobRef("target")
        client = FakeClient(
            [queue(pending=(target,)), queue(running=(target,))],
            [history(target, HistoryState.QUEUED), history(target, HistoryState.RUNNING)],
        )
        result = ComfyUICancellationAdapter(client).cancel(target)
        self.assertEqual(result.state, CancellationState.RUNNING_INTERRUPT_UNSAFE)
        self.assertEqual(result.phase, CancellationPhase.POST_VERIFICATION)
        self.assertEqual(client.interrupt_calls, [])

    def test_running_target_refuses_without_delete_or_interrupt(self):
        target = BackendJobRef("target")
        client = FakeClient([queue(running=(target,))], [history(target, HistoryState.RUNNING)])
        result = ComfyUICancellationAdapter(client).cancel(target)
        self.assertEqual(result.state, CancellationState.RUNNING_INTERRUPT_UNSAFE)
        self.assertEqual(result.action, CancellationAction.NONE)
        self.assertEqual(client.delete_calls, [])
        self.assertEqual(client.interrupt_calls, [])

    def test_contradictory_preflight_never_deletes(self):
        target = BackendJobRef("target")
        client = FakeClient([queue(pending=(target,))], [history(target, HistoryState.SUCCEEDED)])
        result = ComfyUICancellationAdapter(client).cancel(target)
        self.assertEqual(result.state, CancellationState.CONTRADICTORY)
        self.assertEqual(client.delete_calls, [])

    def test_already_terminal_and_not_found_are_noops(self):
        for state, expected in (
            (HistoryState.SUCCEEDED, CancellationState.ALREADY_TERMINAL),
            (HistoryState.FAILED, CancellationState.ALREADY_TERMINAL),
            (HistoryState.NOT_FOUND, CancellationState.NOT_FOUND),
        ):
            with self.subTest(state=state):
                target = BackendJobRef("target")
                client = FakeClient([queue()], [history(target, state)])
                result = ComfyUICancellationAdapter(client).cancel(target)
                self.assertEqual(result.state, expected)
                self.assertEqual(client.delete_calls, [])

    def test_definitive_delete_rejection_is_failed_before_mutation(self):
        target = BackendJobRef("target")
        client = FakeClient([queue(pending=(target,))], [history(target, HistoryState.QUEUED)], delete_error=ComfyUIRejectedError("rejected", 409))
        result = ComfyUICancellationAdapter(client).cancel(target)
        self.assertEqual(result.state, CancellationState.FAILED)
        self.assertEqual(result.issue_kind, CancellationIssueKind.REJECTED)
        self.assertEqual(result.phase, CancellationPhase.BEFORE_MUTATION)
        self.assertEqual(len(client.delete_calls), 1)

    def test_delete_errors_are_uncertain_and_not_retried(self):
        errors = (
            (ComfyUITimeoutError("timeout"), CancellationIssueKind.TIMEOUT),
            (ComfyUITransportError("transport"), CancellationIssueKind.TRANSPORT),
            (ComfyUIProtocolError("protocol"), CancellationIssueKind.PROTOCOL),
            (ComfyUIServerError("server", 503), CancellationIssueKind.SERVER),
        )
        for error, kind in errors:
            with self.subTest(kind=kind):
                target = BackendJobRef("target")
                client = FakeClient([queue(pending=(target,))], [history(target, HistoryState.QUEUED)], delete_error=error)
                result = ComfyUICancellationAdapter(client).cancel(target)
                self.assertEqual(result.state, CancellationState.UNKNOWN)
                self.assertEqual(result.action, CancellationAction.QUEUE_DELETE)
                self.assertEqual(result.issue_kind, kind)
                self.assertEqual(result.phase, CancellationPhase.MUTATION_ATTEMPTED_UNCERTAIN)
                self.assertEqual(len(client.delete_calls), 1)

    def test_post_verification_read_error_is_requested_and_not_retried(self):
        target = BackendJobRef("target")
        client = FakeClient(
            [queue(pending=(target,)), ComfyUITimeoutError("history timeout")],
            [history(target, HistoryState.QUEUED), history(target, HistoryState.QUEUED)],
        )
        result = ComfyUICancellationAdapter(client).cancel(target)
        self.assertEqual(result.state, CancellationState.REQUESTED)
        self.assertEqual(result.action, CancellationAction.QUEUE_DELETE)
        self.assertEqual(result.issue_kind, CancellationIssueKind.TIMEOUT)
        self.assertEqual(result.phase, CancellationPhase.POST_VERIFICATION)
        self.assertEqual(len(client.delete_calls), 1)


class CancellationContractTests(unittest.TestCase):
    def test_low_level_delete_payload_and_empty_response_contract(self):
        client = ComfyUIClient("http://127.0.0.1:8188")
        calls = []

        def request(method, path, payload=None, **kwargs):
            calls.append((method, path, payload, kwargs))
            return None

        client._request = request
        first = BackendJobRef("a")
        client.delete_pending((first, "b"))
        self.assertEqual(calls, [("POST", "/queue", {"delete": ["a", "b"]}, {"allow_empty": True})])

    def test_low_level_delete_rejects_empty_or_malformed_ids(self):
        client = ComfyUIClient("http://127.0.0.1:8188")
        client._request = lambda *args, **kwargs: None
        for values in ((), [], "target", ("",), (object(),)):
            with self.subTest(values=values):
                with self.assertRaises(ComfyUIProtocolError):
                    client.delete_pending(values)

    def test_native_interrupt_is_explicitly_low_level_and_non_atomic(self):
        client = ComfyUIClient("http://127.0.0.1:8188")
        calls = []

        def request(method, path, payload=None, **kwargs):
            calls.append((method, path, payload, kwargs))
            return None

        client._request = request
        client.interrupt_running_native_non_atomic(BackendJobRef("run"))
        self.assertEqual(calls, [("POST", "/interrupt", {"prompt_id": "run"}, {"allow_empty": True})])

    def test_result_and_preflight_are_frozen_and_enums_are_machine_readable(self):
        target = BackendJobRef("target")
        preflight = CancellationPreflight(target, CancellationClassification.NOT_FOUND, queue(), history(target, HistoryState.NOT_FOUND))
        result = CancellationResult(target, CancellationState.NOT_FOUND, CancellationAction.NONE, preflight=preflight)
        with self.assertRaises((AttributeError, TypeError)):
            preflight.classification = CancellationClassification.UNKNOWN
        with self.assertRaises((AttributeError, TypeError)):
            result.state = CancellationState.UNKNOWN
        self.assertEqual(CancellationIssueKind.TIMEOUT.value, "timeout")
        self.assertEqual(CancellationPhase.MUTATION_ATTEMPTED_UNCERTAIN.value, "mutation_attempted_uncertain")

    def test_invalid_target_is_rejected_before_any_client_read(self):
        client = FakeClient()
        adapter = ComfyUICancellationAdapter(client)
        with self.assertRaises(TypeError):
            adapter.cancel("target")
        self.assertEqual(client.queue_calls, 0)


if __name__ == "__main__":
    unittest.main()
